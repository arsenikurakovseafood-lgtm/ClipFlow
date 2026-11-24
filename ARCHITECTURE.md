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
