#!/usr/bin/env bash
# Clone or update all GitLab projects via SSH into ./gitlab/<group>/<subgroup>/<project>.
# Needs: curl, jq, git. Env: GITLAB_TOKEN (read_api), GITLAB_URL (default https://gitlab.com).
set -euo pipefail

url="${GITLAB_URL:-https://gitlab.com}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is not set}"

page=1
while [ -n "$page" ]; do
  headers="$(mktemp)"
  curl -fsS -D "$headers" -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
    "${url%/}/api/v4/projects?membership=true&archived=false&simple=true&per_page=100&page=$page" |
    jq -r '.[] | "\(.path_with_namespace) \(.ssh_url_to_repo)"' |
    while read -r path repo; do
      dest="gitlab/$path"
      if [ -d "$dest/.git" ]; then
        echo "update  $path"
        git -C "$dest" fetch --all --prune --quiet || echo "FAILED  $path" >&2
      else
        echo "clone   $path"
        mkdir -p "$(dirname "$dest")"
        git clone --quiet "$repo" "$dest" || echo "FAILED  $path" >&2
      fi
    done
  page="$(grep -i '^x-next-page:' "$headers" | tr -d '\r' | awk '{print $2}' || true)"
  rm -f "$headers"
done
