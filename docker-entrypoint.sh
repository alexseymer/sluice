#!/bin/sh
set -e

data_dir="${SLUICE_DATA_DIR:-/data}"
mkdir -p "$data_dir/worktrees" "$data_dir/matrix-store"

if [ "$(id -u)" = "0" ]; then
  chown -R sluice:sluice "$data_dir" 2>/dev/null || true
  # Interactive setup may need to rewrite a bind-mounted host .env.
  if [ "${1:-}" = "setup" ]; then
    exec sluice "$@"
  fi
  exec runuser -u sluice -- sluice "$@"
fi

exec sluice "$@"
