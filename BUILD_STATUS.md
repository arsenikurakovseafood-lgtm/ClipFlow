# Build status

The standalone renderer accepts bounded staged media and source-relative captions. It produces fast-start 720 × 1280 H.264 MP4 with optional AAC audio, a center crop, and burned-in subtitles. It checks the rendered video format and duration before replacing the requested output. Stage files are cleaned on normal completion and handled failures.

The cloud test suite generates a synthetic source, encodes and decodes real media, checks subtitle timing at sampled frames, and checks output preservation on validation failure. This synthetic fixture does not establish browser upload, R2 preview, production performance, or commercial margins.

Pending work includes cloud upload and preview, transcription, clip selection, original and music workflows, Supabase Auth and isolated persistence, campaign planning and approval, queue recovery and cancellation, budgets and accounting, private storage retention and quotas, publishing, metrics, owner dashboard, billing, and deployment. There is no running service. Provider credentials and founder payment approval are absent. Public pricing is pending a production benchmark and billing verification.
