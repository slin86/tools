#!/usr/bin/env bash
# Clone or update all GitLab projects via SSH into ./gitlab/<group>/<subgroup>/<project>.
# Needs: git, jq, glab (logged in once with "glab auth login"), SSH key registered in GitLab.
# GitLab cannot list projects over SSH, so glab uses its locally stored login for the project list.
set -euo pipefail

glab api --paginate "projects?membership=true&archived=false&simple=true&per_page=100" |
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
