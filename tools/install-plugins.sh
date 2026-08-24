#!/bin/bash
#
# Install every plugin in this repo onto this Omarchy machine.
#
# Run this ON the Omarchy box, from a clone of this repo:
#
#   tools/install-plugins.sh              # symlink (a git pull then updates them all)
#   tools/install-plugins.sh --copy       # copy instead, if you want them frozen
#   tools/install-plugins.sh --only lens,mixer
#   tools/install-plugins.sh --remove     # uninstall everything this script installed
#
# Symlinks are the default because Omarchy's plugin catalog scans with `find -L`,
# so a link is followed exactly like a real directory -- and then updating every
# plugin is one `git pull` rather than nine copies.

set -uo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PLUGINS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
MODE=link
ONLY=""
REMOVE=0

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
note() { printf '  %s\n' "$1"; }
warn() { printf '  \033[33m%s\033[0m\n' "$1"; }
abort() {
  printf '\033[31m%s\033[0m\n' "$1" >&2
  exit 1
}

while (( $# )); do
  case "$1" in
    --copy) MODE=copy; shift ;;
    --remove) REMOVE=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    -h | --help)
      awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
      exit 0
      ;;
    *) abort "Unknown option: $1" ;;
  esac
done

(( EUID != 0 )) || abort "Do not run this as root. Plugins are installed into your own config."

# Every plugin directory here that actually carries a manifest.
plugins=()
for dir in "$HERE"/plugins/*/; do
  [[ -f ${dir}manifest.json ]] || continue
  name=$(basename "$dir")
  if [[ -n $ONLY ]]; then
    short=${name#omarchy-}
    [[ ,$ONLY, == *,$short,* || ,$ONLY, == *,$name,* ]] || continue
  fi
  plugins+=("$name")
done

(( ${#plugins[@]} > 0 )) || abort "No plugins matched${ONLY:+ --only $ONLY}."

manifest_id() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$1" 2>/dev/null
}

# --- uninstall ---------------------------------------------------------------

if (( REMOVE )); then
  bold "Removing plugins..."
  for name in "${plugins[@]}"; do
    id=$(manifest_id "$HERE/plugins/$name/manifest.json")
    target="$PLUGINS_DIR/$name"

    if [[ -n $id ]] && command -v omarchy-plugin-disable >/dev/null 2>&1; then
      omarchy-plugin-disable "$id" >/dev/null 2>&1 || true
    fi

    # Only ever remove a link, or a directory this script put there. Never
    # follow a link out and delete the repo itself.
    if [[ -L $target ]]; then
      rm -f "$target"
      note "removed link $name"
    elif [[ -d $target ]]; then
      rm -rf "$target"
      note "removed copy $name"
    else
      note "$name was not installed"
    fi
  done
  echo ""
  bold "Done. Restart the shell to see the change: omarchy restart shell"
  exit 0
fi

# --- preflight ---------------------------------------------------------------

if ! command -v omarchy-plugin-enable >/dev/null 2>&1; then
  warn "omarchy-plugin-enable not found. This does not look like an Omarchy machine."
  warn "The files will still be installed, but nothing will enable them."
fi

mkdir -p "$PLUGINS_DIR"

# What each helper shells out to. Missing ones do not stop the install: every
# plugin degrades to reporting the feature unavailable rather than breaking the
# bar, which is the whole reason they were written that way.
declare -A NEEDS=(
  [omarchy-beam]="openssl"
  [omarchy-cast]="openssl"
  [omarchy-lens]="hyprctl"
  [omarchy-mixer]="pactl"
  [omarchy-paper]="lpstat lp"
  [omarchy-type]="fc-list fc-cache"
  [omarchy-unifi]="openssl"
)

# --- install -----------------------------------------------------------------

bold "Installing ${#plugins[@]} plugin(s) into $PLUGINS_DIR"
echo ""

installed=()
failed=()

for name in "${plugins[@]}"; do
  source_dir="$HERE/plugins/$name"
  target="$PLUGINS_DIR/$name"
  id=$(manifest_id "$source_dir/manifest.json")

  if [[ -z $id ]]; then
    warn "$name: manifest.json has no id; skipping"
    failed+=("$name")
    continue
  fi

  # Replace whatever is there, but never delete through a symlink.
  [[ -L $target ]] && rm -f "$target"
  [[ -d $target ]] && rm -rf "$target"

  if [[ $MODE == link ]]; then
    ln -s "$source_dir" "$target"
  else
    cp -r "$source_dir" "$target"
  fi

  # Omarchy's own validator is the gate a marketplace submission is judged by,
  # so run it here too when it exists rather than finding out later.
  if command -v omarchy-plugin-validate >/dev/null 2>&1; then
    if ! omarchy-plugin-validate "$target" >/dev/null 2>&1; then
      warn "$name: omarchy plugin validate failed"
      omarchy-plugin-validate "$target" 2>&1 | sed 's/^/        /'
      failed+=("$name")
      continue
    fi
  fi

  missing=""
  for cmd in ${NEEDS[$name]:-}; do
    command -v "$cmd" >/dev/null 2>&1 || missing+="$cmd "
  done

  printf '  %-16s %s' "$name" "$id"
  [[ -n $missing ]] && printf '  \033[33m(needs: %s)\033[0m' "${missing% }"
  printf '\n'

  installed+=("$id")
done

# --- enable ------------------------------------------------------------------

if command -v omarchy-plugin-enable >/dev/null 2>&1 && (( ${#installed[@]} > 0 )); then
  echo ""
  bold "Enabling..."
  for id in "${installed[@]}"; do
    if omarchy-plugin-enable "$id" >/dev/null 2>&1; then
      note "enabled $id"
    else
      warn "could not enable $id -- enable it from Setup > Plugins"
    fi
  done
fi

# --- report ------------------------------------------------------------------

echo ""
if (( ${#failed[@]} > 0 )); then
  warn "${#failed[@]} plugin(s) had problems: ${failed[*]}"
  echo ""
fi

bold "Installed ${#installed[@]} of ${#plugins[@]}."
echo ""
note "See them:     omarchy plugin list"
note "Load them:    omarchy restart shell"
[[ $MODE == link ]] && note "Update them:  git -C $HERE pull   (they are symlinks)"
note "Remove them:  $0 --remove"
echo ""
note "Every bar widget hides itself when idle by default, so a quiet machine may"
note "show nothing until there is something to report. Settings for each live in"
note "Setup > Plugins."
