# Build status

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
