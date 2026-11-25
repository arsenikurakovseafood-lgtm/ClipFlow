# Build status

The standalone renderer accepts bounded staged media and source-relative captions. It produces fast-start 720 × 1280 H.264 MP4 with optional AAC audio, a center crop, and burned-in subtitles. It checks the rendered video format and duration before replacing the requested output. Stage files are cleaned on normal completion and handled failures.

The cloud test suite generates a synthetic source, encodes and decodes real media, checks subtitle timing at sampled frames, and checks output preservation on validation failure. This synthetic fixture does not establish browser upload, R2 preview, production performance, or commercial margins.

Pending work includes cloud upload and preview, transcription, clip selection, original and music workflows, Supabase Auth and isolated persistence, campaign planning and approval, queue recovery and cancellation, budgets and accounting, private storage retention and quotas, publishing, metrics, owner dashboard, billing, and deployment. There is no running service. Provider credentials and founder payment approval are absent. Public pricing is pending a production benchmark and billing verification.

## Owner demo update

The browser can upload an authorized file to temporary Cloud storage, queue processing in SQLite, see live counts and failures, and play or explicitly download the encoded clip. The separate worker handles the upload after the browser session closes. This build uses manual start/end and optional user-supplied captions. It does not include transcription or automatic selection.

Cloud Chromium verified browser upload, closing the submitting tab, reopening the dashboard, playback of a 4-second 720 × 1280 H.264 MP4, byte-range streaming, and layout at 390 pixels. Four Python tests cover subtitle timing, real encoding, concurrent budget reservation, idempotency, and stale lease recovery across queue instances. GitHub Actions is configured to run the Python tests when GitHub delivery becomes available.

The public GitHub repository is empty and the cloud identity's push previously returned HTTP 403. No authenticated hosted HTTP preview port was configured during verification. Production Supabase Auth/Postgres, direct signed R2 upload and preview, transcription, retention and orphan sweeping, and always-on deployment are pending.
