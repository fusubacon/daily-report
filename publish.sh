#!/usr/bin/env bash
set -euo pipefail

SITE_DIR="${1:-site}"
BRANCH="gh-pages"

if [ ! -d "$SITE_DIR" ]; then
  echo "Site directory not found: $SITE_DIR" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git repository. Initialize git first." >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Missing git remote 'origin'. Add it first." >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git worktree add --force "$TMP_DIR" "$BRANCH"
else
  git worktree add --detach "$TMP_DIR"
  (cd "$TMP_DIR" && git checkout --orphan "$BRANCH")
fi

rsync -av --delete --exclude .git "$SITE_DIR"/ "$TMP_DIR"/

pushd "$TMP_DIR" >/dev/null

git add -A
if git diff --cached --quiet; then
  echo "No changes to publish."
else
  git commit -m "Publish site $(date -u +%F)"
  git push origin "$BRANCH"
fi

popd >/dev/null

git worktree remove "$TMP_DIR" --force
