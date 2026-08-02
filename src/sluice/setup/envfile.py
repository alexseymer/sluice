"""Read/write helpers for `.env` without clobbering unrelated keys."""

from __future__ import annotations

from pathlib import Path


def upsert_env_file(path: Path, values: dict[str, str]) -> None:
    """Create or update `path`, setting each key in `values` (SLUICE_* names)."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated.append(line)
            continue
        key, _, _ = stripped.partition("=")
        key = key.strip()
        if key in remaining:
            updated.append(f"{key}={_format_value(remaining.pop(key))}")
        else:
            updated.append(line)

    if remaining:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append("# Written by `sluice setup`")
        for key, value in remaining.items():
            updated.append(f"{key}={_format_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(updated)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _format_value(value: str) -> str:
    if any(ch in value for ch in ' \n\t#"\'\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
