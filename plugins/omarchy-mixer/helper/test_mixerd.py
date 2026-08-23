#!/usr/bin/env python3
"""
Tests for mixerd.

Driven by feeding real `pactl -f json` output through the parsers and by
capturing the exact argv the daemon would run, because the whole plugin is a
translation layer between PulseAudio's JSON and a slider - and a wrong argv
means somebody's volume changes on the wrong application.

    python3 test_mixerd.py
"""

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mixerd", os.path.join(HERE, "mixerd.py"))
mixerd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mixerd)

PASSED, FAILED = [], []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "   <- %s" % detail))


# Real-shaped pactl output. Note the deliberate awkwardness: a hard-panned
# stream, a paused one, a lowercase binary name, and a stream on the non-default sink.
SINK_INPUTS = [
    {"index": 89, "sink": 50, "corked": False, "mute": False,
     "volume": {"front-left": {"value": 65536, "value_percent": "100%"},
                "front-right": {"value": 65536, "value_percent": "100%"}},
     "properties": {"application.name": "Firefox", "media.name": "AudioStream",
                    "application.icon_name": "firefox"}},
    {"index": 91, "sink": 50, "corked": False, "mute": True,
     "volume": {"front-left": {"value": 32768, "value_percent": "50%"},
                "front-right": {"value": 0, "value_percent": "0%"}},
     "properties": {"application.process.binary": "spotify",
                    "media.name": "Playback"}},
    {"index": 95, "sink": 61, "corked": True, "mute": False,
     "volume": {"mono": {"value": 49152, "value_percent": "75%"}},
     "properties": {"application.name": "mpv", "media.name": "holiday.mkv"}},
]

SINKS = [
    {"index": 50, "name": "alsa_output.pci-0000_00_1f.3.analog-stereo",
     "description": "Built-in Audio", "mute": False, "state": "RUNNING",
     "volume": {"front-left": {"value": 45875}, "front-right": {"value": 45875}}},
    {"index": 61, "name": "bluez_output.AC_12_2F.1",
     "description": "WH-1000XM5", "mute": False, "state": "IDLE",
     "volume": {"front-left": {"value": 65536}, "front-right": {"value": 65536}}},
]


class FakePactl:
    """Stands in for the pactl binary and records every argv it is handed."""

    def __init__(self, default="alsa_output.pci-0000_00_1f.3.analog-stereo"):
        self.calls = []
        self.default = default

    def __call__(self, args, timeout=6):
        self.calls.append(list(args))
        if args[:4] == ["pactl", "-f", "json", "list"]:
            what = args[4]
            if what == "sink-inputs":
                return 0, json.dumps(SINK_INPUTS), ""
            if what == "sinks":
                return 0, json.dumps(SINKS), ""
            return 0, "[]", ""
        if args[:2] == ["pactl", "get-default-sink"]:
            return 0, self.default + "\n", ""
        return 0, "", ""


def with_fake(fn, fake=None):
    fake = fake or FakePactl()
    real = mixerd.run
    mixerd.run = fake
    try:
        return fn(fake)
    finally:
        mixerd.run = real


def capture_snapshot(mixer):
    captured = {}
    real = mixerd.emit
    mixerd.emit = lambda ev, **f: captured.update({ev: f})
    try:
        mixer.snapshot(force=True)
    finally:
        mixerd.emit = real
    return captured.get("snapshot", {})


# --------------------------------------------------------------------------

def test_volume_maths():
    check("volume: full scale is 1.0",
          mixerd.average_volume({"a": {"value": 65536}}) == 1.0)
    check("volume: half is 0.5",
          mixerd.average_volume({"a": {"value": 32768}}) == 0.5)
    # A hard-panned stream must not read as half volume, or touching the
    # slider snaps it to centre and destroys the user's panning.
    check("volume: hard-panned stream reads by loudest channel, not mean",
          mixerd.average_volume({"l": {"value": 65536}, "r": {"value": 0}}) == 1.0,
          mixerd.average_volume({"l": {"value": 65536}, "r": {"value": 0}}))
    check("volume: empty is zero, not a crash", mixerd.average_volume({}) == 0.0)
    check("volume: junk is zero, not a crash", mixerd.average_volume(None) == 0.0)
    check("volume: non-numeric channel ignored",
          mixerd.average_volume({"a": {"value": "loud"}, "b": {"value": 65536}}) == 1.0)


def test_naming():
    check("name: application.name preferred",
          mixerd.friendly_name({"application.name": "Firefox",
                                "media.name": "AudioStream"}) == "Firefox")
    check("name: falls back to the binary, capitalised",
          mixerd.friendly_name({"application.process.binary": "spotify"}) == "Spotify")
    check("name: existing capitalisation is left alone",
          mixerd.friendly_name({"application.name": "mpv"}) == "mpv")
    check("name: nothing usable yields Unknown, not a blank row",
          mixerd.friendly_name({}) == "Unknown")
    # media.name is usually a generic label; preferring it over the binary
    # turned Spotify into "Playback" in the stream list.
    check("name: binary outranks a generic media.name",
          mixerd.friendly_name({"application.process.binary": "spotify",
                                "media.name": "Playback"}) == "Spotify",
          mixerd.friendly_name({"application.process.binary": "spotify",
                                "media.name": "Playback"}))
    check("name: media.name still used when nothing better exists",
          mixerd.friendly_name({"media.name": "System Sounds"}) == "System Sounds")

    check("name: whitespace-only value is skipped",
          mixerd.friendly_name({"application.name": "   ",
                                "media.name": "Playback"}) == "Playback")


def test_snapshot():
    def body(fake):
        return capture_snapshot(mixerd.Mixer())
    snap = with_fake(body)

    streams = {s["name"]: s for s in snap["streams"]}
    check("snapshot: every stream listed", len(snap["streams"]) == 3,
          [s["name"] for s in snap["streams"]])
    check("snapshot: binary name capitalised into the list", "Spotify" in streams,
          list(streams))
    check("snapshot: muted flag carried", streams["Spotify"]["mute"] is True)
    check("snapshot: volume normalised", streams["Firefox"]["volume"] == 1.0,
          streams["Firefox"]["volume"])
    check("snapshot: paused streams sort last",
          snap["streams"][-1]["name"] == "mpv", [s["name"] for s in snap["streams"]])
    check("snapshot: stream carries the sink it is on",
          streams["mpv"]["sinkName"] == "bluez_output.AC_12_2F.1",
          streams["mpv"]["sinkName"])
    check("snapshot: media detail carried", streams["mpv"]["detail"] == "holiday.mkv")

    outputs = snap["outputs"]
    check("snapshot: both outputs listed", len(outputs) == 2)
    check("snapshot: default output sorts first and is flagged",
          outputs[0]["isDefault"] is True and outputs[0]["label"] == "Built-in Audio",
          [(o["label"], o["isDefault"]) for o in outputs])
    check("snapshot: sink volume normalised", outputs[0]["volume"] == 0.7,
          outputs[0]["volume"])
    check("snapshot: friendly output label used", outputs[1]["label"] == "WH-1000XM5")


def test_no_spurious_updates():
    """An unchanged graph must not re-emit, or the UI rebuilds on a timer."""
    fake = FakePactl()
    real = mixerd.run
    mixerd.run = fake
    emitted = []
    real_emit = mixerd.emit
    mixerd.emit = lambda ev, **f: emitted.append(ev)
    try:
        mixer = mixerd.Mixer()
        mixer.snapshot()
        mixer.snapshot()
        mixer.snapshot()
    finally:
        mixerd.run, mixerd.emit = real, real_emit
    check("dedupe: three identical reads emit exactly one snapshot",
          emitted.count("snapshot") == 1, emitted)


def test_commands():
    def body(fake):
        mixer = mixerd.Mixer()
        mixer.set_stream_volume(89, 0.42)
        mixer.set_stream_mute(91, True)
        mixer.set_stream_mute(91, False)
        mixer.move_stream(95, "alsa_output.pci-0000_00_1f.3.analog-stereo")
        mixer.set_sink_volume(50, 0.8)
        mixer.set_sink_mute(50, True)
        return fake.calls
    calls = with_fake(body)
    flat = [" ".join(str(a) for a in c) for c in calls]

    check("cmd: stream volume as a percentage of the right id",
          "pactl set-sink-input-volume 89 42%" in flat, flat)
    check("cmd: mute on", "pactl set-sink-input-mute 91 1" in flat, flat)
    check("cmd: mute off", "pactl set-sink-input-mute 91 0" in flat, flat)
    check("cmd: move names the stream then the sink",
          "pactl move-sink-input 95 alsa_output.pci-0000_00_1f.3.analog-stereo" in flat, flat)
    check("cmd: sink volume", "pactl set-sink-volume 50 80%" in flat, flat)
    check("cmd: sink mute", "pactl set-sink-mute 50 1" in flat, flat)


def test_volume_clamped():
    def body(fake):
        mixer = mixerd.Mixer()
        mixer.set_stream_volume(89, -3.0)
        mixer.set_stream_volume(89, 99.0)
        return fake.calls
    flat = [" ".join(str(a) for a in c) for c in with_fake(body)]
    check("clamp: negative volume floors at 0%",
          "pactl set-sink-input-volume 89 0%" in flat, flat)
    # Above 100% is allowed - PulseAudio supports it and people use it - but
    # not unboundedly, or a stray drag blows out a speaker.
    check("clamp: absurd volume is capped at 150%",
          "pactl set-sink-input-volume 89 150%" in flat, flat)


def test_switching_output_moves_audio():
    """Picking a new output must move what is already playing."""
    def body(fake):
        mixerd.Mixer().set_default_sink("bluez_output.AC_12_2F.1")
        return fake.calls
    calls = with_fake(body)
    flat = [" ".join(str(a) for a in c) for c in calls]

    check("switch: the default is set",
          "pactl set-default-sink bluez_output.AC_12_2F.1" in flat, flat)
    moved = [c for c in flat if c.startswith("pactl move-sink-input")]
    check("switch: every existing stream is brought along", len(moved) == 3, moved)
    check("switch: they all go to the chosen sink",
          all(c.endswith("bluez_output.AC_12_2F.1") for c in moved), moved)

    def body_no_move(fake):
        mixerd.Mixer().set_default_sink("bluez_output.AC_12_2F.1", move_streams=False)
        return fake.calls
    flat2 = [" ".join(str(a) for a in c) for c in with_fake(body_no_move)]
    check("switch: moving can be turned off",
          not any(c.startswith("pactl move-sink-input") for c in flat2), flat2)


def test_pactl_failure_is_reported():
    def failing(args, timeout=6):
        if args[:4] == ["pactl", "-f", "json", "list"]:
            return 1, "", "Connection refused"
        return 0, "", ""
    real, real_emit = mixerd.run, mixerd.emit
    seen = []
    mixerd.run = failing
    mixerd.emit = lambda ev, **f: seen.append((ev, f.get("message", "")))
    try:
        mixerd.Mixer().snapshot()
    finally:
        mixerd.run, mixerd.emit = real, real_emit
    check("failure: a dead pactl surfaces as an error, not silence",
          any(ev == "error" and "Connection refused" in msg for ev, msg in seen), seen)


def main():
    print("-- volume maths --");        test_volume_maths()
    print("\n-- naming --");            test_naming()
    print("\n-- snapshot --");          test_snapshot()
    print("\n-- change detection --");  test_no_spurious_updates()
    print("\n-- commands --");          test_commands()
    print("\n-- clamping --");          test_volume_clamped()
    print("\n-- switching output --");  test_switching_output_moves_audio()
    print("\n-- failure handling --");  test_pactl_failure_is_reported()

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    for name in FAILED:
        print("   failed: %s" % name)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
