#!/usr/bin/env bash
# Usage: GITLAB_TOKEN=<token with read_api> ./gitlab-clone-short.sh <gitlab-hostname>
# Clone or update all non-archived projects of the groups listed below (incl. subgroups)
# via SSH into ./gitlab/<host>/<group>/...
# Needs: curl, jq, git, SSH key registered in GitLab.
set -euo pipefail

# Edit this list: full group paths as they appear in the GitLab URL.
GITLAB_GROUPS=(
  plattform
)

host="${1:?Usage: $0 <gitlab-hostname>}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is not set}"

for group in "${GITLAB_GROUPS[@]}"; do
  echo "== $group"
  for ((page = 1; ; page++)); do
    json="$(curl -fsS -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
      "https://$host/api/v4/groups/${group//\//%2F}/projects?include_subgroups=true&archived=false&simple=true&per_page=100&page=$page")" ||
      { echo "FAILED  group $group (API error)" >&2; break; }
    [ "$(jq length <<<"$json")" -eq 0 ] && break
    while read -r path repo; do
      dest="gitlab/$host/$path"
      if [ -d "$dest/.git" ]; then
        echo "update  $path"
        git -C "$dest" fetch --all --prune --quiet </dev/null || echo "FAILED  $path" >&2
      else
        echo "clone   $path"
        mkdir -p "$(dirname "$dest")"
        git clone --quiet "$repo" "$dest" </dev/null || echo "FAILED  $path" >&2
      fi
    done < <(jq -r '.[] | "\(.path_with_namespace) \(.ssh_url_to_repo)"' <<<"$json")
  done
done
