FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/bash sluice
USER sluice

ENV SLUICE_DATA_DIR=/data
VOLUME /data

ENTRYPOINT ["sluice"]
