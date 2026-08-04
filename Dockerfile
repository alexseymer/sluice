FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    bash \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /bin/bash sluice \
    && mkdir -p /data/home \
    && chown -R sluice:sluice /data \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

# Persist CLI binaries + subscription credentials on the /data volume.
ENV SLUICE_DATA_DIR=/data
ENV SLUICE_DATABASE_URL=sqlite+aiosqlite:////data/sluice.db
ENV SLUICE_WORKTREE_BASE_DIR=/data/worktrees
ENV HOME=/data/home
ENV PATH="/data/home/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV GEMINI_FORCE_FILE_STORAGE=true
ENV NO_OPEN_BROWSER=1

VOLUME /data

ENTRYPOINT ["docker-entrypoint.sh"]
# Default: run the daemon (`sluice` with no subcommand).
CMD []
