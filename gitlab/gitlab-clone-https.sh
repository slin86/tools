#!/usr/bin/env bash
# Usage: GITLAB_TOKEN=<token with read_api + read_repository> ./gitlab-clone-https.sh <gitlab-hostname>
# Clone or update all non-archived projects of the groups listed below (incl. subgroups)
# via HTTPS into ./gitlab/<host>/<group>/...
# Needs: curl, jq, git (2.31+). The token is also used for git, passed via environment, not via argv.
# Optional client certificate (mTLS) for the API calls and for git:
#   GITLAB_CERT  PEM file (best: certificate and private key combined in one file)
#   GITLAB_KEY   private key file, only if it is not part of GITLAB_CERT
# A .p12 file can be converted with: openssl pkcs12 -in c.p12 -out c.pem -nodes
set -euo pipefail

# Edit this list: full group paths as they appear in the GitLab URL.
GITLAB_GROUPS=(
  plattform
)

host="${1:?Usage: $0 <gitlab-hostname>}"
: "${GITLAB_TOKEN:?GITLAB_TOKEN is not set}"

git_cfg=0
add_git_cfg() {
  export "GIT_CONFIG_KEY_$git_cfg=$1" "GIT_CONFIG_VALUE_$git_cfg=$2"
  git_cfg=$((git_cfg + 1))
  export GIT_CONFIG_COUNT=$git_cfg
}
add_git_cfg http.extraHeader "Authorization: Basic $(printf 'oauth2:%s' "$GITLAB_TOKEN" | base64 | tr -d '\n')"
[ -z "${GITLAB_CERT:-}" ] || add_git_cfg http.sslCert "$GITLAB_CERT"
[ -z "${GITLAB_KEY:-}" ] || add_git_cfg http.sslKey "$GITLAB_KEY"

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
    done < <(jq -r '.[] | select(.archived == false) | "\(.path_with_namespace) \(.http_url_to_repo)"' <<<"$json")
  done
done
