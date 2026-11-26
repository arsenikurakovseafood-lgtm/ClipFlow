# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 clipflow \
    && useradd --uid 10001 --gid 10001 --no-create-home clipflow \
    && install -d -m 0700 -o clipflow -g clipflow /var/lib/clipflow
WORKDIR /app
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=build-ca \
    if [ -r /run/secrets/build-ca ]; then export PIP_CERT=/run/secrets/build-ca; fi; \
    pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=10001:10001 clipflow /app/clipflow
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001

CMD ["python", "-m", "clipflow.render_preview"]
