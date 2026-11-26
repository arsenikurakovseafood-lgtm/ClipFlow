# ClipFlow

ClipFlow is an AI Content Autopilot under development. The private owner workspace connects guided campaign planning, batch rendering, clip review, manual publishing and performance tracking.

## Test the owner workspace in a browser

Open the [ClipFlow owner preview](https://clipflow-h09b.onrender.com/signin) with the existing owner password. In **AI Agent**, prepare and review a draft. Approve the campaign and select **Create clips for this campaign**. Pick **Use the ClipFlow walkthrough sample** to test with built-in footage and prepared subtitles or a sample track. The render worker produces real vertical MP4s. Review and approve the clips in **Content**, then schedule them in **Campaigns**. After publishing externally, record the post URL and checkpoints. **Revenue** separates confirmed cash, pending and estimated amounts. **Settings** controls the global processing pause.

The published preview has temporary storage and a manual publishing queue. Live OpenAI, durable deployments, social publishing and public billing require the prerequisites documented in [build status](BUILD_STATUS.md).

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

The `Deploy private ClipFlow to VPS` GitHub Actions workflow is a manual deployment path for reviewed `main` commits. In the `clipflow-production` GitHub environment, configure required reviewers where supported, `CLIPFLOW_DEPLOY_ENABLED=true`, `CLIPFLOW_SSH_TARGET`, `CLIPFLOW_SSH_KEY` and a pinned `CLIPFLOW_SSH_KNOWN_HOSTS` entry. The authorized cloud host needs Docker Compose, the repository at `/srv/clipflow/repo`, and `/srv/clipflow/owner.env` outside Git. An optional `/srv/clipflow/enable-owner-integrations` marker selects the Supabase Auth/R2 variant. The deployer preserves the Compose project and its data volume. This workflow requires an approved VPS and has not deployed one.

## Enable owner sign-in and direct private media on a configured cloud server

For this mode, use an HTTPS hostname and provide the Supabase and R2 settings
listed in `.env.example` in the cloud secret store. Provision the single owner
in Supabase Auth and use their UUID. Browser login uses that user's password
and the server accepts only that UUID. Use a dedicated random session secret
and rotate it to invalidate outstanding studio sessions.

Set the R2 bucket to private. Scope the key to this bucket and configure CORS
only for the exact studio origin, permitting PUT and the Content-Type header.
Set lifecycle expiry for abandoned media under the owners prefix as a backstop.
The app keeps normal source and output durations in the retention settings.
Batch source media, track and caption files share one bounded signed private upload. The worker stages the pinned bundle and stores each resulting clip separately in R2. The integration test uses a fixture S3 endpoint with real FFmpeg output. Verify CORS and signatures on the live bucket before owner use.

Run on the authorized cloud host:

```sh
docker compose -f compose.yaml -f compose.integrations.yaml up -d --build
```

The integration variant uses the application login and HTTPS gateway. Keep
`CLIPFLOW_PAID_WORKLOADS_ENABLED=false` until the owner approves spend. To enable
captions, provide the worker-only OpenAI key and a positive monthly USD budget
in microdollars. Usage estimates reserve one full billed minute per six-second
window at the documented model rate. Estimate precision and provider access
still need validation with the live account.
When captions are enabled, linked campaign jobs also require an explicit USD cap in the campaign draft. A zero cap prevents campaign transcription charges. The worker reserves both budgets atomically before the call.

- [Supabase owner authentication](https://supabase.com/docs/reference/javascript/auth-signinwithpassword)
- [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text)
- [GPT-Transcribe pricing](https://developers.openai.com/api/docs/models/gpt-transcribe)

To enable the AI Agent, set a positive `CLIPFLOW_PLANNING_MONTHLY_MICRO_USD`
cap and the worker-only OpenAI key after approving paid workloads. Each draft
reserves a conservative $0.002. It remains a suggestion until the owner reviews
it, creates a draft, and separately approves the campaign.

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)

## Temporary owner preview on Render

Create a Docker Web Service from this repo and point Render at the branch
containing the preview launcher. Leave Root Directory blank and use
`./Dockerfile`. Set the instance type to Free and generate a random
`CLIPFLOW_PREVIEW_PASSWORD` in Render's Environment Variables section.
Use `/healthz` as the health check path. The Docker image starts the web
process and FFmpeg worker together on a managed Render service. Open the
service's HTTPS URL and sign in with the generated password.

Only authorized test footage belongs in this preview. Its maximum source
size is 8 MiB, source duration is two minutes, and clip duration is 10 seconds.
Render Free can sleep and discard local files between restarts. For a durable
studio, use the private owner deployment with persistent storage. No paid
integration runs in the Free preview.

## Batch Studio

Choose **Spoken highlights** for authorized source footage and an SRT or
WebVTT file. Describe the goal, choose how many clips to prepare (up to ten),
select a subtitle color, and set a release window. Selection favors complete,
non-overlapping passages with more words related to the goal. The studio
reports if the source has fewer suitable passages than requested.

Choose **Music promos** to add an authorized audio file. The worker prepares
distinct excerpts around scene changes where available, replacing the
footage audio with excerpts from the uploaded track. Each clip is rendered
as its own vertical MP4. Each source or audio file is limited to 8 MiB,
source video to two minutes, and exported clips to 10 seconds. The free
preview uses timestamped subtitles from the owner.

Review the renders, approve a campaign, and select **Schedule entire batch**
with a first release time. The queue spreads the clips across the selected
release days. Campaign handoff remains manual.

Spotify URLs can be stored as campaign references. Audio for editing
comes from the uploaded track file.

- [YouTube API developer policies](https://developers.google.com/youtube/terms/developer-policies/)
- [Spotify developer policy](https://developer.spotify.com/policy)

Studio opens from the left sidebar. **Quick clips** takes a video without a
subtitle file. **Podcast highlights** needs speech timestamps, supplied by
SRT/WebVTT in the free preview or by an enabled transcription integration.
The **Import from YouTube or Cloudflare R2** option accepts a direct HTTPS
link to an R2 object or a single public YouTube video/Short. The experimental
YouTube importer is for videos the owner is authorized to edit. It uses a
compatible MP4 stream, with a limit of two minutes and 8 MiB. The preview
does not ingest playlists, live streams, Spotify audio or streaming movie
pages. Source access can fail on cloud hosts. Upload the source directly
when an import is unavailable.

**Original promo** uses approved footage with an independent opening hook and closing call-to-action overlay. Hooks are categorized for comparisons. Campaign analytics only compare owner-entered snapshots with the same time window and sufficient clips and recorded views. When the server has a restricted `CLIPFLOW_YOUTUBE_DATA_API_KEY`, a recorded public YouTube post can also show on-demand official view, like and comment counts. These observations are timestamped, short-lived and displayed independently from historical owner-entered checkpoints. [YouTube `videos.list`](https://developers.google.com/youtube/v3/docs/videos/list)

### Automatic subtitles on Render

Automatic speech and vocal subtitles use the existing OpenAI transcription adapter.
The Render launcher only enables paid calls with a writable persistent disk
mounted at `/var/data`. Render Free has ephemeral storage, so a local spend
ledger on Free would reset on restart. Enable only after budget approval.

In Render Environment, set `OPENAI_API_KEY`, set
`CLIPFLOW_PAID_WORKLOADS_ENABLED=true`, and set a positive
`CLIPFLOW_TRANSCRIPTION_MONTHLY_MICRO_USD` (for example, `1000000` for a $1
monthly reservation cap). Keep the key in Render, never in Git or chat.
Studio will offer **Generate subtitles from audio**. Spoken clips use
source speech. Music promos use vocals from the uploaded track excerpt.
Approximate six-second captions are generated from audio windows; word-level
alignment and live accuracy have not been validated.

- [Render persistent disks](https://render.com/docs/disks)
- [OpenAI transcription model and pricing](https://developers.openai.com/api/docs/models/gpt-transcribe)
