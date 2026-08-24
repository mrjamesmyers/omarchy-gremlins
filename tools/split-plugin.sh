#!/usr/bin/env bash
# Split one plugin out of this repository into its own, which is what
# `omarchy plugin add` needs: it clones a git URL and expects manifest.json at
# the root of what it cloned, not in a subdirectory.
#
#   tools/split-plugin.sh omarchy-beam ../omarchy-beam
#
# History for that subdirectory is preserved. Nothing is pushed; the new
# repository is left on disk with a commit and no remote, so you can look at it
# before deciding where it goes.

set -euo pipefail

plugin="${1:-}"
destination="${2:-}"

if [[ -z "$plugin" || -z "$destination" ]]; then
  echo "usage: $0 <plugin-directory-name> <destination-path>" >&2
  echo "plugins available:" >&2
  ls -1 "$(dirname "$0")/../plugins" >&2
  exit 64
fi

root="$(cd "$(dirname "$0")/.." && pwd)"
source_dir="$root/plugins/$plugin"

if [[ ! -f "$source_dir/manifest.json" ]]; then
  echo "no manifest.json in plugins/$plugin" >&2
  exit 66
fi

if [[ -e "$destination" ]]; then
  echo "$destination already exists; refusing to write into it" >&2
  exit 73
fi

# git subtree split rewrites the subdirectory's history so the plugin's own
# commits survive the move rather than arriving as one opaque "initial commit".
branch="split/$plugin"
git -C "$root" subtree split --prefix="plugins/$plugin" -b "$branch" >/dev/null

git init -q "$destination"
git -C "$destination" fetch -q "$root" "$branch"
git -C "$destination" checkout -q -b main FETCH_HEAD
git -C "$root" branch -q -D "$branch"

echo "wrote $destination"
echo
echo "next:"
echo "  cd $destination"
echo "  git remote add origin git@github.com:YOU/$plugin.git"
echo "  git push -u origin main"
echo
echo "then, on the machine running Omarchy:"
echo "  omarchy plugin add https://github.com/YOU/$plugin.git --enable"
