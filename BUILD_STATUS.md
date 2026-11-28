# Build status

## YouTube owner connection

On an authorized persistent deployment, Accounts can start the Google OAuth consent screen and connect the configured YouTube channel. Enrollment uses a one-time browser-bound state, PKCE, encrypted refresh-token storage and channel verification. Disconnecting stops new scheduled uploads and attempts revocation with Google. The Render Free preview cannot run publication continuously. Connection and publication require a real Google OAuth application and channel owner consent. The tests use simulated Google responses and do not assert live publication.

After a failed source import, Content can take the full original and extract the selected time range on the worker. Already trimmed replacements still work. This recovery does not establish that Render can fetch a YouTube page's video stream.

## Reelattice campaign workspace · 28 November 2026

The new brand and black, lime and white UI cover the landing page, sign-in and owner workspace. Campaign templates supply a starting goal, workflow, hook and publishing cadence. An approved plan can open Studio with its settings filled in. Approved renders in a planned campaign are queued once at the configured cadence. The Analytics view separates owner-reported numbers from official observations and compares hook formats only when the campaign has sufficient comparable measurements.

The cloud browser test rendered and played two vertical MP4s from uploaded footage with fixture subtitles and verified automatic insertion into the release schedule after approval. Backend tests used a simulated YouTube response to check that an uploaded private video is never marked published and that a confirmed public video supplies a checkpoint. This does not establish a live Google connection. The deployed owner preview uses manual handoff and temporary storage. Live YouTube source conversion, public publishing and automated analytics against actual channels need independent verification. TikTok and Instagram publishing automation, external generative video, automatic strategy changes and public SaaS billing remain unavailable.

## Built-in YouTube conversion

The Render owner preview defaults to an in-worker yt-dlp and FFmpeg converter.
It accepts the existing time-range form without a VidFetch key, bounds the
subprocess and output, and surfaces YouTube access refusals as source failures.
Automated coverage injects the source-acquisition step and renders an actual
vertical MP4. Live YouTube availability depends on the cloud host's access.

## Free-only YouTube setup on Render

The private Render Free preview can use a VidFetch key without attaching a
paid disk. The configuration requires an explicit free-only flag. The worker
checks the provider's Free plan, remaining allowance and unfunded balance
before posting a time-range conversion. This mode is verified with provider
fixtures. An authenticated live conversion still requires a configured key
and a Free account whose API permits trim.

## Studio simplification and automatic captions

Studio puts the source, goal, clip count and subtitle controls first. A
separate Advanced settings section holds the optional subtitle-file override.
The cloud image ships hash-pinned English and Russian Vosk models. Speech is
recognized in a separate bounded process on the worker. The sample and files
can be edited within an optional range. The container smoke check renders a
sample range and verifies generated cues and playable output. The unauthenticated
VidFetch homepage demo exposes a URL and output format in its public API
schema. That schema exposes no time-range parameter. The configured VidFetch
range API remains gated by credentials and durable accounting.

## YouTube segment conversion

The earlier direct YouTube importer has been removed. Studio now requests both
timecodes and source permission. When connected, the cloud worker asks VidFetch
for just that range, verifies the resulting MP4 and shifts source-relative
subtitle timestamps before producing clips. The provider fixture verifies the
range request and real FFmpeg output. A cloud browser fixture verifies the
range form, failed conversion, and replacement with a pre-cut source while
preserving the existing track. No live provider account or trim entitlement
has been verified. The temporary Render Free deployment shows the converter
as disabled. No provider subscription was purchased or activated.

## Integrated owner release · 26 November 2026

The owner preview has one browser workflow from a guided goal draft through campaign approval, linked source rendering, per-clip approval, scheduled manual handoff, an owner-reported post URL, performance checkpoints and a EUR cash ledger. Studio supports spoken highlights, music promos, original promos with separate text overlays, and a ClipFlow-authored walkthrough sample that the worker renders without external assets or calls. Global processing pause, campaign pause/stop, and audit events persist in the owner database. A synthetic browser test verifies an actual playable render, and browser-restart evidence is produced by CI. An optional YouTube Data API reader has fixture coverage only and needs a restricted project key.

The Render Free service is a temporary private owner preview. Direct YouTube extraction failed on Render. OpenAI planning and automatic subtitles require approved spend, a provider key and durable accounting storage. The live social OAuth publishing flows, automatic analytics ingestion, a persistent cloud deployment, full Supabase/Postgres customer isolation and public trial, Stripe and subscription entitlements are still pending. The R2 integration for both single clips and batches uses signed uploads, size/ETag verification, bounded worker staging, and private output. Its cloud tests exercise real video encoding against a fixture S3 client. The live bucket and browser CORS are unverified. The persistent VPS workflow requires configuration and approval. No paid launch or commercial benchmark has been completed.

## Earlier verification and milestones

The standalone renderer accepts bounded staged media and source-relative captions. It produces fast-start 720 × 1280 H.264 MP4 with optional AAC audio, a center crop, and burned-in subtitles. It checks the rendered video format and duration before replacing the requested output. Stage files are cleaned on normal completion and handled failures.

The cloud test suite generates a synthetic source, encodes and decodes real media, checks subtitle timing at sampled frames, and checks output preservation on validation failure. This synthetic fixture does not establish browser upload, R2 preview, production performance, or commercial margins.

Pending work includes cloud upload and preview, transcription, clip selection, original and music workflows, Supabase Auth and isolated persistence, campaign planning and approval, queue recovery and cancellation, budgets and accounting, private storage retention and quotas, publishing, metrics, owner dashboard, billing, and deployment. There is no running service. Provider credentials and founder payment approval are absent. Public pricing is pending a production benchmark and billing verification.

## Owner demo update

The browser can upload an authorized file to temporary Cloud storage, queue processing in SQLite, see live counts and failures, and play or explicitly download the encoded clip. The separate worker handles the upload after the browser session closes. This build uses manual start/end and optional user-supplied captions. It does not include transcription or automatic selection.

Cloud Chromium verified browser upload, closing the submitting tab, reopening the dashboard, playback of a 4-second 720 × 1280 H.264 MP4, byte-range streaming, and layout at 390 pixels. Four Python tests cover subtitle timing, real encoding, concurrent budget reservation, idempotency, and stale lease recovery across queue instances. GitHub Actions is configured to run the Python tests when GitHub delivery becomes available.

No authenticated hosted HTTP preview port was configured during verification. GitHub Actions runs the repeatable browser test and attaches synthetic demo screenshots. Production Supabase Auth/Postgres, direct signed R2 upload and preview, transcription, retention and orphan sweeping, and always-on deployment are pending.

## Campaign workflow update

Owner Studio now persists reviewed campaign drafts with a goal, channel, cadence, duration, and budget target. Approval is required before a ready clip can be added to the manual queue. Pausing holds outstanding items, resuming restores their scheduled or due status, and stopping cancels outstanding handoffs. Completed handoffs are evidence of owner action only. Nothing is sent to platform APIs. The cadence and budget are reviewed planning values. The current campaign form uses rule-based counts and manual setup.

A Supabase migration prepares tenant-scoped campaign data and legal state transitions. The R2 media adapter prepares scoped signed PUT/GET requests and object metadata checks. The demo remains on SQLite and cloud scratch storage. Apply and verify the migration in an authorized Supabase project and run live R2 browser CORS, size enforcement, and conditional reads before changing the demo backend.

## Private container deployment

Docker Compose packages the owner studio, isolated FFmpeg worker, and
password-protected Caddy gateway with a shared persistent volume. The Framer
landing uses the updated pink, red, blue, black and white palette. The old
studio screenshot, stock carousel, and developer navigation links were removed
from the landing. The Framer Free hosting badge is platform-managed.

## Owner integration milestone

The Framer page is published on the original ClipCut copy with pink, red, blue,
light blue, black and white. Orange accent fills in the workflow were updated.
The landing shows the synthetic render and remains separate from the owner app.

The app now implements an owner login through Supabase Auth, signed HTTP-only
session cookies, owner identity binding, direct browser uploads using signed
R2 PUT URLs, metadata verification plus conditional reads, lease-fenced R2
outputs, and private streaming and download redirects. These flows use SQLite
for the owner queue. The Supabase Postgres campaign migration is separate.

Optional OpenAI file transcription generates captions for the selected source
range using six-second windows. Captions are window-aligned. The system makes
no claim of word-level synchronization or automatic clip selection. A global
USD reservation is atomic and conservative, and failed paid attempts are
fenced against automatic retry. Owner/session, R2 and transcription contracts
are tested with fixtures, including a real local CPU render. Live provider
credentials, CORS, OAuth/API reviews, TLS routing, and public production
deployment remain unverified. No paid service was activated.

Timed cleanup removes completed sources and then expires finished outputs.
Expiry releases the reserved storage quota and preserves a historical job row.
R2 needs lifecycle rules as a backstop for abandoned or interrupted uploads.

The AI Agent now stores planning requests in a durable queue, generates a
strict-schema suggestion when the separately capped planning budget is enabled,
and lets the owner copy the suggestion into the editable campaign draft. The
provider cannot create, approve, or publish a campaign. Recovery fences out
unconfirmed paid attempts. This planning contract is tested with fixtures.

Batch Studio adds a bounded local-media workflow for the private Render
preview. It generates separate independently leased vertical exports with
selected subtitle colors, optional authorized music and proposed release days.
Speech selection is rule-based on subtitle text and timestamps. The batch
planner prioritizes the maximum number of non-overlapping excerpts before
ranking goal relevance. The same batch can be scheduled into the approved
campaign's manual handoff queue. R2 batch upload, publishing APIs, social
analytics ingestion and creative feedback remain pending.

Owner Preview includes an experimental YouTube source adapter. Tests cover
input normalization, staging, size guards, and access-error handling using
fixtures. A metadata-only request from Codex Cloud was rejected by the cloud
proxy. The Render owner preview also reported a provider rejection. Successful
network ingestion on Render remains unverified.

When the provider rejects access or an R2 import fails, Content offers a source
replacement on the existing batch while its staged assets are retained. A new
video file or a direct R2 file link requeues the same job and keeps its track,
goal, clip settings and budget reservation. The cloud browser test simulates a
YouTube 403, checks authorization and URL validation, and plays a real FFmpeg
export after replacing the source with a test MP4. Render's free preview uses
temporary storage, so redeployments and restarts can discard existing batches.
