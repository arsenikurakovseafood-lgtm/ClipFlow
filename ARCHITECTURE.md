# Architecture

The renderer receives cloud-staged file paths and source-relative subtitle cues. It performs bounded file and format checks, invokes FFmpeg with argument lists and restricted input protocols, and stages output on the same filesystem for atomic replacement. Deploy the eventual renderer in a resource-limited worker with dedicated scratch space and periodic orphan cleanup. The current temporary directory cleanup does not cover hard termination.

The intended next boundary is a private web API backed by Supabase Auth and Postgres. The owner requests scoped signed R2 upload URLs, the worker verifies objects before use, and the API signs preview and download URLs separately. Media remains private. A separate worker and scheduler on an always-on VPS will claim durable Postgres jobs with leases. Campaign approval, enrollment, monthly quota reservations and publish confirmation belong in Postgres transactions. Add a persistent global emergency pause before enabling paid provider calls.

GitHub Actions runs the test suite. Production delivery will require a protected GitHub environment and an approved cloud host. Supply credentials via cloud or GitHub environment secrets. Never commit credentials or deploy a paid resource without founder approval.

## Cost inputs

Budget target is €15–50 per month before workload validation. The fixed baseline includes a VPS, backups, and database. Hetzner pricing varies with location, IPv4, and VAT. Supabase Free can pause after a week of inactivity. Supabase Pro starts at $25 monthly. R2 Standard lists $0.015 per GB-month, $4.50 per million Class A operations, and $0.36 per million Class B operations, with free internet egress. OpenAI use and Stripe fees add usage-based charges. USD conversion, applicable tax, storage and API usage, and render CPU capacity need to be measured before selling subscriptions.

- [Hetzner Cloud](https://www.hetzner.com/cloud/)
- [Supabase pricing](https://supabase.com/pricing)
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing)
- [Stripe Estonia pricing](https://stripe.com/en-ee/pricing)

## Cloud demonstration boundary

The demonstration uses a Python web process and a separate FFmpeg worker. It stages uploads in a Cloud scratch directory and stores job metadata in SQLite. Queue mutations use immediate transactions. Job IDs and lease tokens determine output paths. A stale worker cannot publish over a newer claim. A crash after claiming a job can be recovered after the lease expires.

Budget reservations use simulated integer micro-euros for a global monthly ceiling. The reservation is atomic with submission and idempotent for a given request key. The demo makes no paid API calls and does not reconcile actual expenses. Storage allocation includes headroom for two outputs per job. This is a bounded single-owner demonstration. Abandoned uploads after hard termination, retention, user and campaign budgets, and storage lifecycle rules still require additional work.

## Integration boundaries

The campaign owner path currently uses the demo queue's SQLite transaction to validate campaign state and ready clip state before scheduling. A due item allows manual handoff only while the campaign is active. The production schema adds row-level isolation for campaign records through Supabase Auth. The database migration and R2 SDK contract can be reviewed without live credentials.

R2 object keys get owner and asset UUIDs from server authorization. Before signing PUT, persist the quota reservation and configure bucket CORS for the exact app origin. Check HEAD after upload, then probe the actual file in a resource-limited worker. Pin processing to a verified object revision or copy the object to an immutable worker key. Sign playback and explicit download separately after ownership checks.

- [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
- [Supabase row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security)
