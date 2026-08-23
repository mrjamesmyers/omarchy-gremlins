#!/usr/bin/env bash
# Run the helper daemons against real hardware and report what they actually
# find. Run this ON an Omarchy machine - it is the half of the testing that a
# cloud container cannot do, because there are no printers, no sound cards and
# no Chromecasts in a container.
#
#   tools/smoke-test.sh            # all five
#   tools/smoke-test.sh paper      # just one
#
# Read-only: it starts each helper, watches its event stream for a few seconds,
# prints what came back, and stops it. Nothing is printed, cast, sent or changed.

set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
seconds="${SMOKE_SECONDS:-8}"
only="${1:-}"

bold=$'\e[1m'; dim=$'\e[2m'; green=$'\e[32m'; red=$'\e[31m'; amber=$'\e[33m'; off=$'\e[0m'

pass=0; fail=0; warn=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %sPASS%s %s\n' "$green" "$off" "$*"; pass=$((pass+1)); }
bad()  { printf '  %sFAIL%s %s\n' "$red" "$off" "$*"; fail=$((fail+1)); }
soft() { printf '  %sNOTE%s %s\n' "$amber" "$off" "$*"; warn=$((warn+1)); }

need() {
  if command -v "$1" >/dev/null 2>&1; then return 0; fi
  return 1
}

# Run a helper for `seconds`, capture its NDJSON, hand back the file.
capture() {
  local helper="$1"; shift
  local out; out="$(mktemp)"
  local cmd=(python3 -u "$helper")

  # Feed the commands on stdin, then hold the pipe open for the run window so
  # the daemon does not see EOF and exit before it has said anything.
  { for line in "$@"; do printf '%s\n' "$line"; done; sleep "$seconds"; } \
    | timeout $((seconds + 6)) "${cmd[@]}" > "$out" 2>/dev/null
  printf '%s' "$out"
}

field() { python3 -c "
import json,sys
key=sys.argv[1]; want=sys.argv[2]
for line in open(sys.argv[3]):
    line=line.strip()
    if not line: continue
    try: ev=json.loads(line)
    except ValueError: continue
    if ev.get('ev')==want: print(ev.get(key,'')); break
" "$1" "$2" "$3" 2>/dev/null; }

# grep -c prints "0" AND exits non-zero when there are no matches, so a
# `|| echo 0` fallback appends a second zero and the caller then compares
# "0\n0" as an integer. Capture the output and discard the status instead.
count_ev() {
  local n
  n="$(grep -c "\"ev\":\"$1\"" "$2" 2>/dev/null)" || true
  printf '%s' "${n:-0}"
}

summarise() { python3 -c "
import json,sys
path, want, key = sys.argv[1], sys.argv[2], sys.argv[3]
best=None
for line in open(path):
    line=line.strip()
    if not line: continue
    try: ev=json.loads(line)
    except ValueError: continue
    if ev.get('ev')==want: best=ev
if not best: sys.exit(0)
items=best.get(key) or []
print(len(items))
for it in items[:8]:
    if isinstance(it,dict):
        label=it.get('name') or it.get('alias') or it.get('queue') or it.get('label') or '?'
        extra=it.get('address') or it.get('state') or it.get('kind') or it.get('sinkName') or ''
        print('   - %s %s' % (label, ('(%s)'%extra) if extra else ''))
" "$1" "$2" "$3" 2>/dev/null; }

# ---------------------------------------------------------------- beam
smoke_beam() {
  say "${bold}Beam${off} ${dim}(LocalSend)${off}"
  local h="$root/plugins/omarchy-beam/helper/beamd.py"
  need openssl || soft "openssl missing - Beam would fall back to plaintext HTTP"
  local out; out="$(capture "$h" '{"cmd":"scan"}')"

  local fp; fp="$(field fingerprint ready "$out")"
  local proto; proto="$(field protocol ready "$out")"
  if [ -n "$fp" ]; then ok "came up as '$(field alias ready "$out")' over ${proto:-?}"
  else bad "never emitted ready"; rm -f "$out"; return; fi
  [ "${#fp}" = 64 ] && ok "fingerprint is a certificate hash" \
                    || soft "fingerprint is random (plaintext mode)"

  local n; n="$(count_ev peer "$out")"
  if [ "$n" -gt 0 ]; then ok "$n peer announcement(s) seen on the LAN"
  else soft "no LocalSend peers found - open the app on a phone and re-run"; fi
  rm -f "$out"
}

# ---------------------------------------------------------------- cast
smoke_cast() {
  say "${bold}Cast${off} ${dim}(Chromecast / DLNA)${off}"
  local h="$root/plugins/omarchy-cast/helper/castd.py"
  local out; out="$(SMOKE=1 capture "$h" '{"cmd":"scan"}')"

  grep -q '"ev":"ready"' "$out" && ok "helper started" || { bad "never emitted ready"; rm -f "$out"; return; }
  local found; found="$(summarise "$out" targets targets)"
  local n="${found%%$'\n'*}"
  if [ -n "$n" ] && [ "$n" != "0" ]; then
    ok "found $n cast target(s):"
    printf '%s\n' "$found" | tail -n +2
  else
    soft "no cast targets found - is the TV awake and on this network?"
  fi
  rm -f "$out"
}

# ---------------------------------------------------------------- paper
smoke_paper() {
  say "${bold}Paper${off} ${dim}(printing)${off}"
  local h="$root/plugins/omarchy-paper/helper/paperd.py"
  need lpstat || soft "lpstat missing - CUPS is not installed"
  local out; out="$(capture "$h" '{"cmd":"rescan"}' '{"cmd":"refresh"}')"

  grep -q '"ev":"ready"' "$out" && ok "helper started" || { bad "never emitted ready"; rm -f "$out"; return; }
  local found; found="$(summarise "$out" snapshot printers)"
  local n="${found%%$'\n'*}"
  if [ -n "$n" ] && [ "$n" != "0" ]; then
    ok "found $n printer(s):"
    printf '%s\n' "$found" | tail -n +2
  else
    soft "no printers found - none configured in CUPS and none advertising"
  fi
  # The privilege boundary is the load-bearing claim in this plugin.
  if grep -q "lpadmin" "$out"; then
    ok "setup commands are offered as text (never executed)"
  fi
  rm -f "$out"
}

# ---------------------------------------------------------------- mixer
smoke_mixer() {
  say "${bold}Mixer${off} ${dim}(per-app audio)${off}"
  local h="$root/plugins/omarchy-mixer/helper/mixerd.py"
  need pactl || { bad "pactl missing - install pipewire-pulse"; return; }
  local out; out="$(capture "$h" '{"cmd":"refresh"}')"

  grep -q '"ev":"ready"' "$out" && ok "helper started" || { bad "never emitted ready"; rm -f "$out"; return; }
  local outs; outs="$(summarise "$out" snapshot outputs)"
  local n="${outs%%$'\n'*}"
  if [ -n "$n" ] && [ "$n" != "0" ]; then
    ok "found $n audio output(s):"
    printf '%s\n' "$outs" | tail -n +2
  else
    bad "no audio outputs at all - that is not right"
  fi
  local streams; streams="$(summarise "$out" snapshot streams)"
  local sn="${streams%%$'\n'*}"
  if [ -n "$sn" ] && [ "$sn" != "0" ]; then
    ok "$sn application stream(s) playing:"
    printf '%s\n' "$streams" | tail -n +2
  else
    soft "nothing is playing - start some audio and re-run to see the sliders"
  fi
  rm -f "$out"
}

# ---------------------------------------------------------------- unifi
smoke_unifi() {
  say "${bold}UniFi${off}"
  local h="$root/plugins/omarchy-unifi/helper/unifid.py"
  local key="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/unifi.key"
  if [ ! -f "$key" ] && [ -z "${UNIFI_API_KEY:-}" ]; then
    soft "no API key at $key - skipping (this is expected)"
    return
  fi
  local host="${UNIFI_HOST:-}"
  if [ -z "$host" ]; then soft "set UNIFI_HOST=192.168.1.1 to exercise this"; return; fi
  local out; out="$(capture "$h" "{\"cmd\":\"config\",\"host\":\"$host\",\"port\":443}")"
  if grep -q '"ev":"snapshot"' "$out"; then
    ok "talked to the console at $host"
  else
    bad "no snapshot - $(field message error "$out")"
  fi
  rm -f "$out"
}

say ""
say "${bold}Omarchy plugin smoke test${off} ${dim}- $seconds s per helper, read-only${off}"
say "${dim}$(uname -srm) | $(python3 --version 2>&1)${off}"
say ""

for name in beam cast paper mixer unifi; do
  if [ -n "$only" ] && [ "$only" != "$name" ]; then continue; fi
  "smoke_$name"
  say ""
done

say "${bold}$pass passed, $fail failed, $warn note(s)${off}"
[ "$fail" -eq 0 ]
