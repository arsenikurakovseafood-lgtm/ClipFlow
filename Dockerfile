FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 clipflow \
    && useradd --uid 10001 --gid 10001 --no-create-home clipflow \
    && install -d -m 0700 -o clipflow -g clipflow /var/lib/clipflow
WORKDIR /app
COPY --chown=10001:10001 clipflow /app/clipflow
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
