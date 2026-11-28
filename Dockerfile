# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm AS speech-models
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip
WORKDIR /models
RUN curl --fail --silent --show-error --max-time 120 -o en.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip \
    && curl --fail --silent --show-error --max-time 120 -o ru.zip https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip \
    && printf '%s\n' '30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498  en.zip' \
       '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4  ru.zip' | sha256sum -c - \
    && unzip -q en.zip && unzip -q ru.zip && rm en.zip ru.zip

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 clipflow \
    && useradd --uid 10001 --gid 10001 --no-create-home clipflow \
    && install -d -m 0700 -o clipflow -g clipflow /var/lib/clipflow
WORKDIR /app
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=speech-models /models /opt/clipflow-speech
COPY requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=build-ca \
    if [ -r /run/secrets/build-ca ]; then export PIP_CERT=/run/secrets/build-ca; fi; \
    pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=10001:10001 clipflow /app/clipflow
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001

CMD ["python", "-m", "clipflow.render_preview"]
