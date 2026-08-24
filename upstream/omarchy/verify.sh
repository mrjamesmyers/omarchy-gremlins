#!/bin/bash
#
# Checks the upstream contribution two ways:
#
#   1. files/ still matches what input-sharing.patch would write. The patch is
#      the deliverable; files/ is a readable copy, and a copy that has drifted
#      is worse than no copy at all. Needs nothing but git.
#
#   2. The patch still applies to basecamp/omarchy and its tests still pass
#      there. Needs the network, so it is skipped unless --full is passed.
#
# Usage: upstream/omarchy/verify.sh [--full]

set -uo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PATCH="$HERE/input-sharing.patch"
UPSTREAM=https://github.com/basecamp/omarchy
BRANCH=quattro

failures=0

pass() { printf 'ok - %s\n' "$1"; }
fail() {
  printf 'not ok - %s\n' "$1" >&2
  [[ -n ${2:-} ]] && printf '%s\n' "$2" >&2
  failures=$((failures + 1))
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# --- 1. files/ matches the patch --------------------------------------------

# Replay the patch into an empty repo. Every file it touches is new except the
# three it edits in place, which have no copy under files/ and are skipped.
git -C "$work" init -q .
git -C "$work" apply --include='bin/*' --include='default/systemd/*' --include='test/*' "$PATCH" ||
  fail "the patch applies to an empty tree for the files it creates"

while IFS= read -r copy; do
  relative=${copy#"$HERE/files/"}
  source="$work/$relative"

  if [[ ! -f $source ]]; then
    fail "files/$relative comes from the patch"
    continue
  fi

  if ! diff -q "$source" "$copy" >/dev/null; then
    fail "files/$relative matches the patch" "$(diff -u "$source" "$copy")"
    continue
  fi

  pass "files/$relative matches the patch"
done < <(find "$HERE/files" -type f | sort)

# Nothing the patch creates should be missing from files/.
while IFS= read -r created; do
  relative=${created#"$work/"}
  [[ -f $HERE/files/$relative ]] || fail "files/$relative exists for a file the patch creates"
done < <(find "$work" -type f -not -path '*/.git/*' | sort)

# --- 2. the patch still applies upstream -------------------------------------

if [[ ${1:-} == "--full" ]]; then
  clone="$work/omarchy"

  if git clone -q --depth 1 --branch "$BRANCH" "$UPSTREAM" "$clone" 2>/dev/null; then
    if git -C "$clone" apply --check "$PATCH" 2>/dev/null; then
      pass "the patch applies to $UPSTREAM@$BRANCH"

      git -C "$clone" apply "$PATCH"
      if bash "$clone/test/shell.d/input-sharing-test.sh" >/dev/null 2>&1; then
        pass "the contributed tests pass in the upstream tree"
      else
        fail "the contributed tests pass in the upstream tree"
      fi
    else
      fail "the patch applies to $UPSTREAM@$BRANCH" "$BRANCH has moved; rebase the patch"
    fi
  else
    printf 'skip - could not clone %s\n' "$UPSTREAM"
  fi
else
  printf 'skip - pass --full to check the patch against %s\n' "$UPSTREAM"
fi

if (( failures > 0 )); then
  printf '\n%d check(s) failed\n' "$failures" >&2
  exit 1
fi

printf '\nAll checks passed.\n'
