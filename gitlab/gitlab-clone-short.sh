#!/usr/bin/env bash
# Usage: ./gitlab-clone-short.sh <gitlab-hostname>
# Clone or update all projects of one GitLab via SSH into ./gitlab/<host>/<group>/<project>.
# Needs: git, jq, glab (logged in for that host), SSH key registered in GitLab.
set -euo pipefail

host="${1:?Usage: $0 <gitlab-hostname>}"

glab api --hostname "$host" --paginate "projects?membership=true&archived=false&simple=true&per_page=100" |
  jq -r '.[] | "\(.path_with_namespace) \(.ssh_url_to_repo)"' |
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
