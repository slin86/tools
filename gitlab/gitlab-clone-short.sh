#!/usr/bin/env bash
# Usage: ./gitlab-clone-short.sh <gitlab-hostname> <group>
# Clone or update all projects of a group (incl. subgroups) via SSH into ./gitlab/<host>/<group>/...
# Needs: git, jq, glab (logged in for that host), SSH key registered in GitLab.
set -euo pipefail

host="${1:?Usage: $0 <gitlab-hostname> <group>}"
group="${2:?Usage: $0 <gitlab-hostname> <group>}"

glab api --hostname "$host" --paginate "groups/${group//\//%2F}/projects?include_subgroups=true&archived=false&simple=true&per_page=100" |
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
