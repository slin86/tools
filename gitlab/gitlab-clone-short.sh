#!/usr/bin/env bash
# Clone or update all GitLab projects of every glab-configured GitLab host via SSH
# into ./gitlab/<host>/<group>/<subgroup>/<project>.
# Needs: git, jq, glab (logged in once per host with "glab auth login"), SSH keys registered in GitLab.
# GitLab cannot list projects over SSH, so glab uses its locally stored login for the project list.
set -euo pipefail

config="${XDG_CONFIG_HOME:-$HOME/.config}/glab-cli/config.yml"
hosts="$(awk '/^hosts:/ {in_hosts=1; next} /^[^ ]/ {in_hosts=0} in_hosts && /^  [^ ]+:/ {gsub(/[ :]/, ""); print}' "$config")"

for host in $hosts; do
  echo "== $host"
  glab api --hostname "$host" --paginate "projects?membership=true&archived=false&simple=true&per_page=100" |
    jq -r '.[] | "\(.path_with_namespace) \(.ssh_url_to_repo)"' |
    while read -r path repo; do
      dest="gitlab/$host/$path"
      if [ -d "$dest/.git" ]; then
        echo "update  $path"
        git -C "$dest" fetch --all --prune --quiet || echo "FAILED  $host/$path" >&2
      else
        echo "clone   $path"
        mkdir -p "$(dirname "$dest")"
        git clone --quiet "$repo" "$dest" || echo "FAILED  $host/$path" >&2
      fi
    done
done
