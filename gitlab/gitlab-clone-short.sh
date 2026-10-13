#!/usr/bin/env bash
# Usage: ./gitlab-clone-short.sh <gitlab-hostname> [group-or-project-path]
# Clone or update all projects of one GitLab, a group incl. subgroups, or a single project via SSH
# into ./gitlab/<host>/<group>/<project>.
# Needs: git, jq, glab (logged in for that host), SSH key registered in GitLab.
set -euo pipefail

host="${1:?Usage: $0 <gitlab-hostname> [group-or-project-path]}"

if [ -n "${2:-}" ]; then
  enc="${2//\//%2F}"
  if glab api --hostname "$host" "groups/$enc" >/dev/null 2>&1; then
    endpoint="groups/$enc/projects?include_subgroups=true&archived=false&simple=true&per_page=100"
  else
    endpoint="projects/$enc"
  fi
else
  endpoint="projects?membership=true&archived=false&simple=true&per_page=100"
fi

glab api --hostname "$host" --paginate "$endpoint" |
  jq -r 'if type == "array" then .[] else . end | "\(.path_with_namespace) \(.ssh_url_to_repo)"' |
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
  done
