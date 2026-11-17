#!/usr/bin/env bash
# Usage: GITLAB_TOKEN=<token with read_api> ./gitlab-clone-short.sh <gitlab-hostname>
# Clone or update all non-archived projects of the groups listed below (incl. subgroups)
# via SSH into ./gitlab/<host>/<group>/...
# Needs: curl, jq, git, SSH key registered in GitLab.
# Optional client certificate (mTLS) for the API calls:
#   GITLAB_CERT  PEM file, "file.p12:password", or a keychain identity name (macOS system curl)
#   GITLAB_KEY   private key file, only if it is not part of GITLAB_CERT
set -euo pipefail

# Edit this list: full group paths as they appear in the GitLab URL.
GITLAB_GROUPS=(
  plattform
)

host="${1:?Usage: $0 <gitlab-hostname>}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is not set}"

curl_args=()
[ -z "${GITLAB_CERT:-}" ] || curl_args+=(--cert "$GITLAB_CERT")
[ -z "${GITLAB_KEY:-}" ] || curl_args+=(--key "$GITLAB_KEY")

for group in "${GITLAB_GROUPS[@]}"; do
  echo "== $group"
  for ((page = 1; ; page++)); do
    resp="$(curl -sS ${curl_args[@]+"${curl_args[@]}"} -H "PRIVATE-TOKEN: $GITLAB_TOKEN" -w $'\n%{http_code}' \
      "https://$host/api/v4/groups/${group//\//%2F}/projects?include_subgroups=true&archived=false&per_page=100&page=$page")" ||
      { echo "FAILED  group $group (curl error)" >&2; break; }
    code="${resp##*$'\n'}"
    json="${resp%$'\n'*}"
    if [ "$code" != 200 ] || ! jq -e 'type == "array"' <<<"$json" >/dev/null 2>&1; then
      echo "FAILED  group $group page $page: HTTP $code: $(head -c 300 <<<"$json")" >&2
      break
    fi
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
    done < <(jq -r '.[] | select(.archived == false) | "\(.path_with_namespace) \(.ssh_url_to_repo)"' <<<"$json")
  done
done
