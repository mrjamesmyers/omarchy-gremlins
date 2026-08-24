#!/bin/bash

set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/base-test.sh"

require_command openssl

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/bin" "$tmp_dir/config/lan-mouse"

# A stand-in for the daemon's IPC client. It records every call and keeps its
# client list in a file, so the tests can assert on what the command asked for
# without lan-mouse -- or a compositor -- being present.
cat >"$tmp_dir/bin/lan-mouse" <<'EOF'
#!/bin/bash

printf '%s\n' "$*" >>"$LAN_MOUSE_CALLS"

[[ ${1:-} == cli ]] || exit 1
shift

case "${1:-}" in
  list)
    while IFS='|' read -r id host; do
      [[ -n $id ]] || continue
      printf 'id %s: %s:4242 (left) active: false, ips: []\n' "$id" "$host"
    done <"$LAN_MOUSE_STATE"
    ;;
  add-client)
    shift
    host=unknown
    while (( $# )); do
      case "$1" in
        --hostname)
          host="$2"
          shift 2
          ;;
        --ips) shift 2 ;;
        *) shift ;;
      esac
    done
    printf '%s|%s\n' "$LAN_MOUSE_NEXT_ID" "$host" >>"$LAN_MOUSE_STATE"
    ;;
  set-position | save-config | authorize-key | remove-client) ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$tmp_dir/bin/lan-mouse"

cat >"$tmp_dir/bin/systemctl" <<'EOF'
#!/bin/bash

[[ $* == *is-active* ]] || exit 0
[[ ${DAEMON_RUNNING:-1} == 1 ]]
EOF
chmod +x "$tmp_dir/bin/systemctl"

cat >"$tmp_dir/bin/hostname" <<'EOF'
#!/bin/bash

echo desk
EOF
chmod +x "$tmp_dir/bin/hostname"

export PATH="$tmp_dir/bin:$ROOT/bin:$PATH"
export XDG_CONFIG_HOME="$tmp_dir/config"
export LAN_MOUSE_CALLS="$tmp_dir/calls"
export LAN_MOUSE_STATE="$tmp_dir/clients"
export LAN_MOUSE_NEXT_ID=9

cert="$tmp_dir/config/lan-mouse/lan-mouse.pem"
share="$ROOT/bin/omarchy-setup-input-sharing"

reset_calls() {
  : >"$LAN_MOUSE_CALLS"
}

reset_clients() {
  : >"$LAN_MOUSE_STATE"
  printf '%s\n' "$@" >>"$LAN_MOUSE_STATE"
}

: >"$LAN_MOUSE_CALLS"
reset_clients

# --- lan-mouse missing -------------------------------------------------------

# A PATH holding nothing but Omarchy's own bin proves lan-mouse is absent no
# matter what the machine running this has installed.
error=$(PATH="$ROOT/bin" "$share" list 2>&1 >/dev/null || true)
[[ $error == *"not installed"* ]] ||
  fail "every command says so when Lan Mouse is not installed" "$error"
pass "every command says so when Lan Mouse is not installed"

if PATH="$ROOT/bin" "$share" status >/dev/null 2>&1; then
  fail "status fails when Lan Mouse is not installed"
fi
pass "status fails when Lan Mouse is not installed"

# --- fingerprint -------------------------------------------------------------

if "$share" fingerprint >/dev/null 2>&1; then
  fail "fingerprint fails before the daemon has written a certificate"
fi
pass "fingerprint fails before the daemon has written a certificate"

# lan-mouse stores the private key and the certificate in one PEM, which is why
# the command reads the fingerprint with openssl rather than hashing the file.
openssl req -x509 -newkey rsa:2048 -keyout "$tmp_dir/key.pem" -out "$tmp_dir/cert.pem" \
  -days 1 -nodes -subj "/CN=ignored" >/dev/null 2>&1
cat "$tmp_dir/key.pem" "$tmp_dir/cert.pem" >"$cert"

# What lan-mouse itself computes: the SHA-256 of the DER certificate, printed as
# lowercase colon-separated bytes.
expected=$(openssl x509 -in "$tmp_dir/cert.pem" -outform DER |
  sha256sum | cut -d' ' -f1 | sed 's/../&:/g; s/:$//')
actual=$("$share" fingerprint)

[[ $actual == "$expected" ]] ||
  fail "fingerprint matches the SHA-256 of the DER certificate" "expected: $expected
actual:   $actual"
pass "fingerprint matches the SHA-256 of the DER certificate"

[[ $actual == *:* && $actual != *[A-Z]* ]] ||
  fail "fingerprint is lowercase and colon-separated: $actual"
pass "fingerprint is lowercase and colon-separated"

# --- add ---------------------------------------------------------------------

reset_calls
if "$share" add mini sideways >/dev/null 2>&1; then
  fail "add rejects a position that is not an edge"
fi
[[ ! -s $LAN_MOUSE_CALLS ]] ||
  fail "add rejects a bad position before touching lan-mouse" "$(<"$LAN_MOUSE_CALLS")"
pass "add rejects a position that is not an edge, before touching lan-mouse"

reset_calls
if "$share" add >/dev/null 2>&1; then
  fail "add without a hostname fails"
fi
pass "add without a hostname fails"

# Ids are neither sequential nor sorted in the order they arrive, so the command
# has to work out which client is new by diffing the list around the call rather
# than assuming the last or highest id is the one it just made.
# Id 2 among 3 and 11 is neither the highest nor the one that sorts last, so a
# shortcut on either would move the wrong machine.
reset_calls
reset_clients "3|studio" "11|attic"
LAN_MOUSE_NEXT_ID=2 "$share" add mini right >/dev/null

grep -qx 'cli add-client --hostname mini' "$LAN_MOUSE_CALLS" ||
  fail "add passes the hostname to add-client" "$(<"$LAN_MOUSE_CALLS")"
pass "add passes the hostname to add-client"

grep -qx 'cli set-position 2 right' "$LAN_MOUSE_CALLS" ||
  fail "add moves the new client, not an existing one" "$(<"$LAN_MOUSE_CALLS")"
pass "add finds the new id among existing clients and positions it"

grep -qx 'cli save-config' "$LAN_MOUSE_CALLS" ||
  fail "add persists the configuration" "$(<"$LAN_MOUSE_CALLS")"
pass "add persists the configuration"

output=$(reset_clients; LAN_MOUSE_NEXT_ID=4 "$share" add mini right)
[[ $output == *"authorize desk $expected"* ]] ||
  fail "add prints the pairing command for the other machine" "$output"
pass "add prints the pairing command for the other machine"

# Each address is its own --ips flag; lan-mouse appends rather than splitting one
# comma-separated value.
reset_calls
reset_clients
LAN_MOUSE_NEXT_ID=2 "$share" add mini left 192.168.1.4 192.168.1.5 >/dev/null
grep -qx 'cli add-client --hostname mini --ips 192.168.1.4 --ips 192.168.1.5' "$LAN_MOUSE_CALLS" ||
  fail "add passes each address as its own --ips flag" "$(<"$LAN_MOUSE_CALLS")"
pass "add passes each address as its own --ips flag"

# --- authorize and remove ----------------------------------------------------

reset_calls
"$share" authorize studio "aa:bb:cc" >/dev/null
grep -qx 'cli authorize-key studio aa:bb:cc' "$LAN_MOUSE_CALLS" ||
  fail "authorize forwards the name and key" "$(<"$LAN_MOUSE_CALLS")"
grep -qx 'cli save-config' "$LAN_MOUSE_CALLS" ||
  fail "authorize persists the configuration" "$(<"$LAN_MOUSE_CALLS")"
pass "authorize forwards the name and key, and persists it"

reset_calls
if "$share" remove studio >/dev/null 2>&1; then
  fail "remove rejects anything that is not an id"
fi
[[ ! -s $LAN_MOUSE_CALLS ]] ||
  fail "remove rejects a bad id before touching lan-mouse" "$(<"$LAN_MOUSE_CALLS")"
pass "remove rejects anything that is not an id"

reset_calls
"$share" remove 3 >/dev/null
grep -qx 'cli remove-client 3' "$LAN_MOUSE_CALLS" ||
  fail "remove forwards the id" "$(<"$LAN_MOUSE_CALLS")"
pass "remove forwards the id"

# --- a stopped daemon --------------------------------------------------------

# Everything but status and fingerprint needs the daemon, and lan-mouse's own
# error for that is "could not connect", which reads like a network fault.
reset_calls
if DAEMON_RUNNING=0 "$share" add mini right >/dev/null 2>&1; then
  fail "add fails while the daemon is stopped"
fi
error=$(DAEMON_RUNNING=0 "$share" add mini right 2>&1 >/dev/null || true)
[[ $error == *"not running"* ]] ||
  fail "a stopped daemon is reported as a stopped daemon" "$error"
pass "a stopped daemon is reported as a stopped daemon, not a connection failure"

output=$(DAEMON_RUNNING=0 "$share" status)
[[ $output == *"stopped"* && $output == *"$expected"* ]] ||
  fail "status reports a stopped daemon and still shows this machine's key" "$output"
pass "status reports a stopped daemon and still shows this machine's key"

output=$("$share" status)
[[ $output == *"running"* && $output == *desk* ]] ||
  fail "status reports a running daemon and this machine's name" "$output"
pass "status reports a running daemon and this machine's name"
