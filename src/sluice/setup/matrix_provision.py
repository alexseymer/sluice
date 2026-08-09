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


class BotAlreadyExistsError(MatrixSetupError):
    """Bot localpart is already registered on the homeserver."""

    def __init__(self, localpart: str) -> None:
        self.localpart = localpart
        super().__init__(f"Bot user @{localpart} already exists on the homeserver")


class RegistrationDisabledError(MatrixSetupError):
    """Homeserver rejected open registration."""

    def __init__(self, localpart: str) -> None:
        self.localpart = localpart
        super().__init__(
            f"Open registration is disabled; cannot create @{localpart} without "
            "Synapse registration_shared_secret (or an existing bot password/token)."
        )


@dataclass(frozen=True)
class MatrixProvisionResult:
    homeserver: str
    bot_user_id: str
    bot_access_token: str
    room_id: str
    allowed_sender: str
    bot_password: str | None = None


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


def is_user_already_taken(message: str) -> bool:
    lower = message.lower()
    return (
        "already taken" in lower
        or "user_in_use" in lower
        or "m_user_in_use" in lower
    )


def is_registration_disabled(message: str) -> bool:
    lower = message.lower()
    return (
        "registration has been disabled" in lower
        or "registration is disabled" in lower
        or "registrations are disabled" in lower
    )


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


async def whoami(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    access_token: str,
) -> str | None:
    response = await client.get(
        f"{homeserver}/_matrix/client/v3/account/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code >= 400:
        return None
    return str(response.json().get("user_id") or "") or None


async def verify_matrix_bot(
    *,
    homeserver: str,
    access_token: str,
    room_id: str | None = None,
    expected_localpart: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Return bot user_id if token is valid (and room joined when room_id set)."""
    hs = normalize_homeserver(homeserver)

    async def _run(http: httpx.AsyncClient) -> str | None:
        user_id = await whoami(http, homeserver=hs, access_token=access_token)
        if not user_id:
            return None
        if expected_localpart and localpart_from_mxid(user_id) != expected_localpart:
            return None
        if room_id and not await room_joined(
            http, homeserver=hs, bot_token=access_token, room_id=room_id
        ):
            return None
        return user_id

    if client is not None:
        return await _run(client)
    async with httpx.AsyncClient(timeout=30.0) as http:
        return await _run(http)


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
        message = _error_message(response)
        if is_user_already_taken(message):
            raise BotAlreadyExistsError(username)
        if is_registration_disabled(message):
            raise RegistrationDisabledError(username)
        raise MatrixSetupError(f"Bot registration failed ({response.status_code}): {message}")
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

        payload = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        message = _error_message(response)
        if is_user_already_taken(message) or (
            isinstance(payload, dict) and payload.get("errcode") == "M_USER_IN_USE"
        ):
            raise BotAlreadyExistsError(username)
        if is_registration_disabled(message):
            raise RegistrationDisabledError(username)
        if response.status_code == 401 and "session" in payload:
            session = str(payload["session"])
            flows = payload.get("flows") or []
            completed = set(payload.get("completed") or [])
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
            f"Bot registration failed ({response.status_code}): {message}"
        )
    raise MatrixSetupError("Bot registration failed after multiple auth attempts.")


async def resolve_bot_account(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    bot_localpart: str,
    shared_secret: str | None,
    registration_token: str | None,
    existing_bot_token: str | None,
    bot_password: str | None,
) -> tuple[str, str, str | None]:
    """Register bot or reuse an existing account. Returns (user_id, token, password)."""
    new_password = generate_bot_password()
    register_error: BotAlreadyExistsError | RegistrationDisabledError | None = None
    try:
        if shared_secret:
            bot_id, bot_token = await register_bot_shared_secret(
                client,
                homeserver=homeserver,
                shared_secret=shared_secret,
                username=bot_localpart,
                password=new_password,
            )
        else:
            bot_id, bot_token = await register_bot_client_api(
                client,
                homeserver=homeserver,
                username=bot_localpart,
                password=new_password,
                registration_token=registration_token,
            )
        return bot_id, bot_token, new_password
    except (BotAlreadyExistsError, RegistrationDisabledError) as exc:
        register_error = exc

    if existing_bot_token:
        user_id = await whoami(
            client, homeserver=homeserver, access_token=existing_bot_token
        )
        if user_id and localpart_from_mxid(user_id) == bot_localpart:
            return user_id, existing_bot_token, bot_password

    if bot_password:
        bot_id, bot_token = await login_password(
            client,
            homeserver=homeserver,
            user=bot_localpart,
            password=bot_password,
        )
        return bot_id, bot_token, bot_password

    # Surface the original failure so the CLI can prompt for shared secret
    # or existing bot credentials (not a misleading "already exists" when
    # open registration is simply closed).
    if register_error is not None:
        raise register_error
    raise BotAlreadyExistsError(bot_localpart)


async def room_joined(
    client: httpx.AsyncClient,
    *,
    homeserver: str,
    bot_token: str,
    room_id: str,
) -> bool:
    response = await client.get(
        f"{homeserver}/_matrix/client/v3/joined_rooms",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    if response.status_code >= 400:
        return False
    return room_id in (response.json().get("joined_rooms") or [])


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
                "Sluice is connected. Accept the invite if you have not already. "
                "Chat here anytime — say `/jour-fixe` when you want a planning session "
                "to shape forge issues."
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
    existing_bot_token: str | None = None,
    existing_room_id: str | None = None,
    bot_password: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> MatrixProvisionResult:
    """Log in as operator, ensure bot + private room, return bot credentials."""
    hs = normalize_homeserver(homeserver)

    async def _run(http: httpx.AsyncClient) -> MatrixProvisionResult:
        operator_id, _operator_token = await login_password(
            http,
            homeserver=hs,
            user=operator_user,
            password=operator_password,
        )
        bot_id, bot_token, stored_password = await resolve_bot_account(
            http,
            homeserver=hs,
            bot_localpart=bot_localpart,
            shared_secret=shared_secret,
            registration_token=registration_token,
            existing_bot_token=existing_bot_token,
            bot_password=bot_password,
        )

        room_id = existing_room_id
        if not (
            room_id
            and await room_joined(http, homeserver=hs, bot_token=bot_token, room_id=room_id)
        ):
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
            bot_password=stored_password,
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
