#!/usr/bin/env bash
set -euo pipefail

revision=${1:?Expected a Git revision}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]

cd /srv/clipflow/repo
[[ "$(git remote get-url origin)" == https://github.com/arsenikurakovseafood-lgtm/ClipFlow.git ]]
[[ -z "$(git status --porcelain)" ]]
git fetch origin main:refs/remotes/origin/main
git merge-base --is-ancestor "$revision" refs/remotes/origin/main
git checkout --detach "$revision"

compose=(docker compose --project-name clipflow --env-file /srv/clipflow/owner.env -f compose.yaml)
if [[ -f /srv/clipflow/enable-owner-integrations ]]; then
    compose+=(-f compose.integrations.yaml)
fi
"${compose[@]}" config --quiet
"${compose[@]}" up --detach --build --wait --wait-timeout 90
