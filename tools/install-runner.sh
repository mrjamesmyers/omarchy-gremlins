#!/bin/bash
#
# Install a GitHub Actions self-hosted runner on this Omarchy machine.
#
# Run this ON the machine that should execute CI -- not in a container, not on
# the machine you are reading this from unless they are the same box.
#
#   tools/install-runner.sh <registration-token>
#   tools/install-runner.sh --gh          # mint a token with the gh CLI
#
# Get a token by hand from:
#   https://github.com/mrjamesmyers/omarchy-gremlins/settings/actions/runners/new
# Registration tokens expire one hour after they are issued.
#
# Overridable: RUNNER_DIR, RUNNER_NAME, RUNNER_LABELS, RUNNER_VERSION.

set -euo pipefail

REPO=mrjamesmyers/omarchy-gremlins
REPO_URL="https://github.com/$REPO"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null || echo omarchy)}"
RUNNER_LABELS="${RUNNER_LABELS:-omarchy,arch}"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
note() { printf '  %s\n' "$1"; }
abort() {
  printf '\033[31m%s\033[0m\n' "$1" >&2
  exit 1
}

usage() {
  # The header comment block, minus the shebang, stopping at the first line
  # that is not a comment -- so it cannot drift when the script grows.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
  exit "${1:-0}"
}

# --- preflight ---------------------------------------------------------------

case "${1:-}" in
  -h | --help | help) usage 0 ;;
  "") usage 1 ;;
esac

(( EUID != 0 )) || abort "Do not run this as root. The runner refuses to configure under sudo, and the service should run as you."

[[ $(uname -s) == Linux ]] || abort "This installs the Linux runner; this machine is $(uname -s)."

case "$(uname -m)" in
  x86_64) platform=linux-x64 ;;
  aarch64 | arm64) platform=linux-arm64 ;;
  armv7l) platform=linux-arm ;;
  *) abort "No GitHub runner build for $(uname -m)." ;;
esac

for tool in curl tar sha256sum sudo; do
  command -v "$tool" >/dev/null || abort "$tool is required but not installed."
done

# --- the registration token --------------------------------------------------

# Short-lived and single-use. Minting it through gh avoids a copy-paste round
# trip, but the web UI is the documented path and works without gh installed.
if [[ $1 == "--gh" ]]; then
  command -v gh >/dev/null || abort "--gh needs the gh CLI. Install it, or pass a token from $REPO_URL/settings/actions/runners/new"
  bold "Requesting a registration token..."
  token=$(gh api -X POST "/repos/$REPO/actions/runners/registration-token" --jq .token) ||
    abort "gh could not mint a token. Check you are logged in with admin rights on $REPO."
else
  token="$1"
fi

[[ -n $token ]] || abort "Empty registration token."

# --- dependencies ------------------------------------------------------------

# What the runner's own installdependencies.sh installs elsewhere, in Arch
# names. That script only knows Debian, RHEL and SUSE, so on Arch it bails --
# these are the same libraries by their Arch package names. All but lttng-ust
# are already on any Arch system; listing them makes the requirement explicit
# and costs nothing when they are present.
bold "Installing runner dependencies..."
if command -v omarchy-pkg-add >/dev/null; then
  omarchy-pkg-add icu krb5 zlib openssl git
else
  sudo pacman -S --noconfirm --needed icu krb5 zlib openssl git
fi

# Tracing only. The runner starts without it, so a failure here is not fatal.
if command -v omarchy-pkg-add >/dev/null; then
  omarchy-pkg-add lttng-ust || note "lttng-ust unavailable; continuing without it."
else
  sudo pacman -S --noconfirm --needed lttng-ust || note "lttng-ust unavailable; continuing without it."
fi

# The QML job lints with qmllint, which ships with qt6-declarative. Omarchy
# already has it; the job downgrades to a warning if it is missing, so this is
# a convenience rather than a requirement.
if ! command -v qmllint >/dev/null && [[ ! -x /usr/lib/qt6/bin/qmllint ]]; then
  note "qmllint not found. The QML job will warn rather than fail."
  note "Install it with: omarchy pkg add qt6-declarative"
fi

# --- fetch the runner --------------------------------------------------------

api() { curl -fsSL -H "Accept: application/vnd.github+json" "https://api.github.com$1"; }

bold "Resolving the latest runner release..."
release=$(api /repos/actions/runner/releases/latest) || abort "Could not reach the GitHub API."

version="${RUNNER_VERSION:-$(printf '%s' "$release" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p')}"
[[ -n $version ]] || abort "Could not read the latest runner version."

tarball="actions-runner-$platform-$version.tar.gz"
url="https://github.com/actions/runner/releases/download/v$version/$tarball"

# The release notes carry the checksums between literal markers -- see
# releaseNote.md in actions/runner. Parsing those is exact, where scraping the
# rendered table would not be.
expected=$(printf '%s' "$release" |
  sed -n "s/.*<!-- BEGIN SHA $platform -->\([0-9a-f]\{64\}\)<!-- END SHA $platform -->.*/\1/p" | head -1)

note "version:  $version"
note "platform: $platform"
note "checksum: ${expected:-not published for this platform}"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ -f ./config.sh ]]; then
  note "A runner is already unpacked in $RUNNER_DIR; reusing it and re-registering."
  note "To install a different version, remove that directory first."
else
  bold "Downloading $tarball..."
  curl -fL --retry 3 -o "$tarball" "$url" || abort "Download failed: $url"

  if [[ -n $expected ]]; then
    actual=$(sha256sum "$tarball" | cut -d' ' -f1)
    [[ $actual == "$expected" ]] ||
      abort "Checksum mismatch for $tarball.
  expected $expected
  got      $actual"
    note "checksum verified"
  else
    # Never silently accept an unverified binary that is about to run CI as you.
    abort "No checksum published for $platform in the release notes. Refusing to install unverified."
  fi

  tar xzf "$tarball"
  rm -f "$tarball"
fi

# --- register ----------------------------------------------------------------

bold "Registering with $REPO..."

# --replace lets this script be re-run: a stale registration under the same name
# is taken over rather than colliding.
./config.sh \
  --url "$REPO_URL" \
  --token "$token" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --work _work \
  --unattended \
  --replace

# --- run it as a service -----------------------------------------------------

bold "Installing the systemd service..."
sudo ./svc.sh install "$(id -un)"
sudo ./svc.sh start

# --- verify ------------------------------------------------------------------

bold "Waiting for the runner to come online..."

# "Listening for Jobs" in the diagnostic log is the runner's own statement that
# it has connected and is ready -- a stronger signal than the unit being active,
# which is true for a few seconds before the connection succeeds.
online=0
for _ in $(seq 1 30); do
  if grep -qs "Listening for Jobs" _diag/Runner_*.log; then
    online=1
    break
  fi
  sleep 2
done

echo ""
if (( online == 1 )); then
  bold "Runner '$RUNNER_NAME' is online and listening."
  echo ""
  note "labels:  self-hosted, $(uname -m | sed 's/x86_64/X64/'), Linux, $RUNNER_LABELS"
  note "service: $(cat .service 2>/dev/null || echo "see $RUNNER_DIR/.service")"
  note "check:   $REPO_URL/settings/actions/runners"
  echo ""
  note "Queued jobs should start within a few seconds. Re-run any that were"
  note "already queued from $REPO_URL/actions"
else
  echo "The service is installed but has not reported 'Listening for Jobs' yet." >&2
  echo "" >&2
  note "sudo $RUNNER_DIR/svc.sh status" >&2
  note "tail -n 40 $RUNNER_DIR/_diag/Runner_*.log" >&2
  exit 1
fi

echo ""
bold "One thing worth knowing"
note "This runner executes whatever a workflow says, on this machine."
note "helper-tests.yml already skips pull requests from forks for that reason."
note "Under $REPO_URL/settings/actions you can also require approval before"
note "any outside contributor's workflow runs here."
