#!/bin/sh
set -e

data_dir="${SLUICE_DATA_DIR:-/data}"
mkdir -p "$data_dir/worktrees" "$data_dir/matrix-store" "$data_dir/home" \
  "$data_dir/home/.local/bin" "$data_dir/home/.gemini/antigravity-cli" \
  "$data_dir/home/.cursor"

export HOME="${HOME:-$data_dir/home}"
export PATH="$HOME/.local/bin:${PATH}"
export GEMINI_FORCE_FILE_STORAGE="${GEMINI_FORCE_FILE_STORAGE:-true}"
export NO_OPEN_BROWSER="${NO_OPEN_BROWSER:-1}"

if [ "$(id -u)" = "0" ]; then
  chown -R sluice:sluice "$data_dir" 2>/dev/null || true
  # Interactive setup may need to rewrite a bind-mounted host .env.
  if [ "${1:-}" = "setup" ]; then
    exec sluice "$@"
  fi
  exec runuser -u sluice -- env HOME="$HOME" PATH="$PATH" \
    GEMINI_FORCE_FILE_STORAGE="$GEMINI_FORCE_FILE_STORAGE" \
    NO_OPEN_BROWSER="$NO_OPEN_BROWSER" \
    sluice "$@"
fi

exec sluice "$@"
