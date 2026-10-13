#!/usr/bin/env bash
# gitlab-clone-all.sh - clone or update all GitLab projects, keeping the group hierarchy.
#
# Every project ends up at <target>/<full/path/with/subgroups>. Projects that
# already exist locally are updated with "git fetch --all --prune" instead.
#
# Requirements: bash, curl, jq, git
#
# Usage:
#   export GITLAB_TOKEN=glpat-xxxx            # needs read_api (+ read_repository for HTTPS)
#   ./gitlab-clone-all.sh [options]
#
# Options:
#   -u URL      GitLab base URL (default: $GITLAB_URL or https://gitlab.com)
#   -g GROUP    only this group (ID or full path), including all subgroups
#   -t DIR      target directory (default: ./gitlab)
#   -s          clone via SSH instead of HTTPS
#   -a          include archived projects (skipped by default)
#   -n          dry run: only print what would be done
#   -h          show this help

set -euo pipefail

GITLAB_URL="${GITLAB_URL:-https://gitlab.com}"
TARGET="./gitlab"
GROUP=""
USE_SSH=0
INCLUDE_ARCHIVED=0
DRY_RUN=0

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while getopts "u:g:t:sanh" opt; do
  case "$opt" in
    u) GITLAB_URL="$OPTARG" ;;
    g) GROUP="$OPTARG" ;;
    t) TARGET="$OPTARG" ;;
    s) USE_SSH=1 ;;
    a) INCLUDE_ARCHIVED=1 ;;
    n) DRY_RUN=1 ;;
    h) usage 0 ;;
    *) usage 1 ;;
  esac
done

GITLAB_URL="${GITLAB_URL%/}"

for tool in curl jq git; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

if [ -z "${GITLAB_TOKEN:-}" ]; then
  echo "GITLAB_TOKEN is not set" >&2
  exit 1
fi

urlencode() {
  jq -rn --arg v "$1" '$v|@uri'
}

if [ -n "$GROUP" ]; then
  endpoint="$GITLAB_URL/api/v4/groups/$(urlencode "$GROUP")/projects?include_subgroups=true"
else
  endpoint="$GITLAB_URL/api/v4/projects?membership=true"
fi
endpoint="$endpoint&per_page=100&simple=true"
if [ "$INCLUDE_ARCHIVED" -eq 0 ]; then
  endpoint="$endpoint&archived=false"
fi

# The token is passed as a header so that it never lands in .git/config or the process list.
auth_header="Authorization: Basic $(printf 'oauth2:%s' "$GITLAB_TOKEN" | base64 | tr -d '\n')"

fetch_all_projects() {
  local page=1 headers body next
  headers="$(mktemp)"
  trap 'rm -f "$headers"' RETURN
  while [ -n "$page" ]; do
    body="$(curl -fsS -D "$headers" -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$endpoint&page=$page")"
    printf '%s\n' "$body" | jq -c '.[]'
    next="$(grep -i '^x-next-page:' "$headers" | tr -d '\r' | awk '{print $2}' || true)"
    page="$next"
  done
}

ok=0
failed=()

while IFS= read -r project; do
  path="$(jq -r '.path_with_namespace' <<<"$project")"
  if [ "$USE_SSH" -eq 1 ]; then
    url="$(jq -r '.ssh_url_to_repo' <<<"$project")"
  else
    url="$(jq -r '.http_url_to_repo' <<<"$project")"
  fi
  dest="$TARGET/$path"

  if [ -d "$dest/.git" ]; then
    echo "update  $path"
    [ "$DRY_RUN" -eq 1 ] && continue
    if [ "$USE_SSH" -eq 1 ]; then
      git -C "$dest" fetch --all --prune --quiet || { failed+=("$path"); continue; }
    else
      git -C "$dest" -c "http.extraHeader=$auth_header" fetch --all --prune --quiet || { failed+=("$path"); continue; }
    fi
  else
    echo "clone   $path"
    [ "$DRY_RUN" -eq 1 ] && continue
    mkdir -p "$(dirname "$dest")"
    if [ "$USE_SSH" -eq 1 ]; then
      git clone --quiet "$url" "$dest" || { failed+=("$path"); continue; }
    else
      git -c "http.extraHeader=$auth_header" clone --quiet "$url" "$dest" || { failed+=("$path"); continue; }
    fi
  fi
  ok=$((ok + 1))
done < <(fetch_all_projects)

echo
echo "Done: $ok ok, ${#failed[@]} failed"
if [ "${#failed[@]}" -gt 0 ]; then
  printf '  failed: %s\n' "${failed[@]}"
  exit 1
fi
