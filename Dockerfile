FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /bin/bash sluice \
    && mkdir -p /data \
    && chown -R sluice:sluice /data \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV SLUICE_DATA_DIR=/data
ENV SLUICE_DATABASE_URL=sqlite+aiosqlite:////data/sluice.db
ENV SLUICE_WORKTREE_BASE_DIR=/data/worktrees

VOLUME /data

ENTRYPOINT ["docker-entrypoint.sh"]
# Default: run the daemon (`sluice` with no subcommand).
CMD []
