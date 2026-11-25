# ClipFlow

ClipFlow is an AI Content Autopilot under development. This milestone implements the CPU clip renderer.

Run the media checks from a Codex Cloud checkout or from GitHub Actions. The cloud image must provide Python 3, FFmpeg, FFprobe, libx264, libass, and DejaVu Sans.

```sh
python3 -m unittest discover -s tests -v
python3 -m clipflow source.mp4 clip.mp4 --start 10 --end 30 --captions captions.json
```

Caption input is a JSON array with `start` and `end` in source-relative seconds and a `text` string on each entry. Use authorized media staged on the cloud worker. The command writes an H.264 MP4 to the cloud filesystem and reports duration, dimensions, and bytes.

See [build status](BUILD_STATUS.md) and [architecture](ARCHITECTURE.md).

## Cloud constraints

Development, dependencies, builds, verification, and runtime are cloud-only. GitHub Actions runs checks and will handle approved deployments. The application, scheduler, workers, and FFmpeg belong on remote infrastructure. Production design uses Supabase Auth/Postgres, private R2 media, signed browser-direct upload, streamed preview, and explicit download.

Production must enforce spending limits, storage quotas, retention, and temporary-file cleanup. The initial €15–50 monthly target requires validation. Paid services require explicit founder approval. Codex Cloud is the development environment.

## Private owner demo

Run the following in two processes on Codex Cloud, sharing a Cloud-only state directory with mode `0700`.

```sh
python3 -m clipflow.web /workspace/scratch/clipflow-demo/media
python3 -m clipflow.worker /workspace/scratch/clipflow-demo/media
```

The server defaults to Cloud loopback port 3000. For an owner-only hosted preview, first configure port 3000 under Edit Environment → HTTP Previews and apply it to the chat. Once the authenticated gateway is configured, start the web process with `--bind 0.0.0.0 --authenticated-gateway` and use the URL advertised by the environment. This flag assumes the surrounding network restricts access to the authenticated gateway. The demo has no application login and must never be exposed directly.

Choose an authorized MP4, MOV or WebM, enter the clip range and optionally add a caption. Queue the render, then play it in the library. Downloading requires clicking **Download MP4**.

## Run a private owner preview on an authorized cloud server

The repository includes a Docker Compose package for a single owner. It runs a
public-facing Caddy gateway, a private web container, and an offline FFmpeg
worker. The worker and web share a persistent Docker volume. Only Caddy exposes
ports. The gateway requires the owner username and password for all routes.

On the cloud server, check out the reviewed commit and provide the settings from
`.env.example` through the server's secret store. Set `CLIPFLOW_SITE` to the real
DNS hostname and point its records at the server. Set `CLIPFLOW_BIND_IP=0.0.0.0`
only after DNS, TLS ingress on ports 80 and 443, and the owner hash are configured.
Use Caddy's `hash-password` command to create the bcrypt hash and store the
password separately. Run `docker compose up -d --build` on the server. Keep the
named volume when updating the containers. The browser URL is the configured
HTTPS hostname.

This deployment package uses the demo's SQLite and private on-server storage.
Use authorized media and keep the hostname private to the owner. Before real
customer traffic, configure production authentication and media storage, and
complete retention, cleanup, and usage enforcement.
