"""Provision a Matrix bot user and private Sluice room during setup."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class MatrixSetupError(RuntimeError):
    """Raised when Matrix provisioning fails."""


@dataclass(frozen=True)
class MatrixProvisionResult:
    homeserver: str
    bot_user_id: str
    bot_access_token: str
    room_id: str
    allowed_sender: str


def normalize_homeserver(url: str) -> str:
    raw = url.strip().rstrip("/")
    if not raw:
        raise MatrixSetupError("Homeserver URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MatrixSetupError(f"Invalid homeserver URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def localpart_from_mxid(mxid: str) -> str:
    value = mxid.strip()
    if value.startswith("@"):
        value = value[1:]
    if ":" in value:
        value = value.split(":", maxsplit=1)[0]
    if not value:
        raise MatrixSetupError("Matrix user id is required")
    return value


def generate_bot_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def synapse_registration_mac(
    *,
    shared_secret: str,
    nonce: str,
    username: str,
    password: str,
    admin: bool = False,
) -> str:
    """HMAC-SHA1 MAC for Synapse shared-secret registration."""
    mac = hmac.new(shared_secret.encode("utf-8"), digestmod=hashlib.sha1)
    mac.update(nonce.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(username.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(password.encode("utf-8"))
    mac.update(b"\x00")
    mac.update(b"admin" if admin else b"notadmin")
    return mac.hexdigest()


async def login_password(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    user: str,
    password: str,
) -> tuple[str, str]:
    """Return (user_id, access_token) for a password login."""
    identifier = user if user.startswith("@") else user
    response = await client.post(
        f"{homeserver}/_matrix/client/v3/login",
        json={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": localpart_from_mxid(identifier)},
            "password": password,
        },
    )
    if response.status_code >= 400:
        raise MatrixSetupError(
            f"Matrix login failed ({response.status_code}): {_error_message(response)}"
        )
    payload = response.json()
    return str(payload["user_id"]), str(payload["access_token"])


async def register_bot_shared_secret(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    shared_secret: str,
    username: str,
    password: str,
    displayname: str = "Sluice",
) -> tuple[str, str]:
    """Register a bot via Synapse `/_synapse/admin/v1/register`."""
    nonce_response = await client.get(f"{homeserver}/_synapse/admin/v1/register")
    if nonce_response.status_code >= 400:
        raise MatrixSetupError(
            "Shared-secret registration is not available on this homeserver "
            f"(HTTP {nonce_response.status_code}). Provide a working "
            "registration_shared_secret from Synapse, or register the bot manually."
        )
    nonce = str(nonce_response.json()["nonce"])
    mac = synapse_registration_mac(
        shared_secret=shared_secret,
        nonce=nonce,
        username=username,
        password=password,
    )
    response = await client.post(
        f"{homeserver}/_synapse/admin/v1/register",
        json={
            "nonce": nonce,
            "username": username,
            "password": password,
            "displayname": displayname,
            "admin": False,
            "mac": mac,
        },
    )
    if response.status_code >= 400:
        raise MatrixSetupError(
            f"Bot registration failed ({response.status_code}): {_error_message(response)}"
        )
    payload = response.json()
    return str(payload["user_id"]), str(payload["access_token"])


async def register_bot_client_api(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    username: str,
    password: str,
    registration_token: str | None = None,
) -> tuple[str, str]:
    """Try Client-Server `/register` (open registration or registration token)."""
    session: str | None = None
    auth: dict[str, object]
    if registration_token:
        auth = {"type": "m.login.registration_token", "token": registration_token}
    else:
        auth = {"type": "m.login.dummy"}

    for _ in range(3):
        body: dict[str, object] = {
            "username": username,
            "password": password,
            "auth": {**auth, **({"session": session} if session else {})},
        }
        response = await client.post(
            f"{homeserver}/_matrix/client/v3/register",
            json=body,
        )
        if response.status_code < 400:
            payload = response.json()
            return str(payload["user_id"]), str(payload["access_token"])

        payload = response.json() if response.headers.get("content-type", "").startswith(
            "application/json"
        ) else {}
        if response.status_code == 401 and "session" in payload:
            session = str(payload["session"])
            flows = payload.get("flows") or []
            completed = set(payload.get("completed") or [])
            # Prefer registration_token flow when available and provided.
            chosen = None
            for flow in flows:
                stages = flow.get("stages") or []
                pending = [s for s in stages if s not in completed]
                if not pending:
                    continue
                if registration_token and "m.login.registration_token" in pending:
                    chosen = "m.login.registration_token"
                    break
                if "m.login.dummy" in pending:
                    chosen = "m.login.dummy"
                    break
            if chosen == "m.login.registration_token" and registration_token:
                auth = {
                    "type": "m.login.registration_token",
                    "token": registration_token,
                    "session": session,
                }
                continue
            if chosen == "m.login.dummy":
                auth = {"type": "m.login.dummy", "session": session}
                continue
            raise MatrixSetupError(
                "Homeserver registration requires interactive auth that Sluice "
                "cannot complete automatically. Prefer Synapse "
                "registration_shared_secret during setup."
            )
        raise MatrixSetupError(
            f"Bot registration failed ({response.status_code}): {_error_message(response)}"
        )
    raise MatrixSetupError("Bot registration failed after multiple auth attempts.")


async def create_sluice_room(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    bot_token: str,
    invite_user_id: str,
    room_name: str = "Sluice",
) -> str:
    response = await client.post(
        f"{homeserver}/_matrix/client/v3/createRoom",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={
            "name": room_name,
            "topic": "Jour fixe planning and status updates from Sluice",
            "preset": "private_chat",
            "invite": [invite_user_id],
            "is_direct": False,
            "initial_state": [
                {
                    "type": "m.room.guest_access",
                    "state_key": "",
                    "content": {"guest_access": "forbidden"},
                }
            ],
        },
    )
    if response.status_code >= 400:
        raise MatrixSetupError(
            f"Room creation failed ({response.status_code}): {_error_message(response)}"
        )
    return str(response.json()["room_id"])


async def send_setup_notice(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    bot_token: str,
    room_id: str,
) -> None:
    await client.post(
        f"{homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={
            "msgtype": "m.notice",
            "body": (
                "Sluice is connected. Accept the invite if you have not already, "
                "then run `/jourfixe` here when you are ready to plan."
            ),
        },
    )


async def provision_matrix(
    *,
    homeserver: str,
    operator_user: str,
    operator_password: str,
    shared_secret: str | None = None,
    registration_token: str | None = None,
    bot_localpart: str = "sluice-bot",
    client: httpx.AsyncClient | None = None,
) -> MatrixProvisionResult:
    """Log in as operator, create bot + private room, return bot credentials."""
    hs = normalize_homeserver(homeserver)

    async def _run(http: httpx.AsyncClient) -> MatrixProvisionResult:
        operator_id, _operator_token = await login_password(
            http,
            homeserver=hs,
            user=operator_user,
            password=operator_password,
        )
        bot_password = generate_bot_password()
        if shared_secret:
            bot_id, bot_token = await register_bot_shared_secret(
                http,
                homeserver=hs,
                shared_secret=shared_secret,
                username=bot_localpart,
                password=bot_password,
            )
        else:
            try:
                bot_id, bot_token = await register_bot_client_api(
                    http,
                    homeserver=hs,
                    username=bot_localpart,
                    password=bot_password,
                    registration_token=registration_token,
                )
            except MatrixSetupError as exc:
                raise MatrixSetupError(
                    f"{exc} Tip: pass the Synapse registration_shared_secret so "
                    "setup can create @sluice-bot without open registration."
                ) from exc

        room_id = await create_sluice_room(
            http,
            homeserver=hs,
            bot_token=bot_token,
            invite_user_id=operator_id,
        )
        with contextlib.suppress(Exception):
            await send_setup_notice(
                http,
                homeserver=hs,
                bot_token=bot_token,
                room_id=room_id,
            )

        return MatrixProvisionResult(
            homeserver=hs,
            bot_user_id=bot_id,
            bot_access_token=bot_token,
            room_id=room_id,
            allowed_sender=operator_id,
        )

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient(timeout=30.0) as http:
        return await _run(http)


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text[:300]
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("errcode") or payload)[:300]
    return str(payload)[:300]
