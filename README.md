# ClipFlow

Cloud-first AI content production and campaign automation. Implementation is in progress in Codex Cloud; this initialization commit is not a deployed product.

## Architecture constraints

- Develop, install dependencies, build, and test only in cloud environments.
- Source in GitHub; automated checks and approved deployments through GitHub Actions.
- Application, persistent scheduler, background workers, and FFmpeg run remotely.
- Supabase authentication/PostgreSQL and private Cloudflare R2 media storage.
- Browser-direct signed uploads, streamed previews, explicit downloads only.
- No founder-local dependency installation, Docker Desktop, AI models, or media caches.
- Enforce spending limits, storage quotas, configurable retention, and temporary-file cleanup.
- EUR 15–50 initial monthly infrastructure/API budget is a target to validate.
- Paid services require explicit founder approval.

Verified functionality, test results, deployment instructions, environment variables, costs, and external blockers will be documented as implementation proceeds. Codex is the development tool, not the production runtime.
