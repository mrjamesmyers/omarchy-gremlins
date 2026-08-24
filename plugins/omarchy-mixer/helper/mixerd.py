#!/usr/bin/env python3
"""
omarchy-mixer helper daemon - turn one application down without turning the rest down.

Windows has had a per-application volume mixer since Vista and everybody who
has ever used one expects it. Nothing in the 1,099-plugin Omarchy registry does
this. `pavucontrol` exists, but it is a separate window you have to go and find,
which is not the same thing as a slider in the bar.

Talks to PipeWire through `pactl`, which ships with pipewire-pulse and speaks
JSON, rather than to `pw-dump` directly. pw-dump exposes the graph, which is
more powerful and considerably more work: routing a stream to a different sink
means finding its link objects and rebuilding them, where pactl calls it
`move-sink-input` and does it in one command.

Updates are event-driven. `pactl subscribe` emits a line whenever anything in
the audio graph changes, so this re-reads on change rather than polling a
slider position sixty times a minute.

Transport contract with QML: newline-delimited JSON.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time

# A slow safety net behind the event stream, in case a change arrives that
# `pactl subscribe` does not report.
SAFETY_POLL = 10.0

# Coalesce bursts: changing a volume emits several events in a few
# milliseconds and re-reading the whole graph for each is pointless.
COALESCE = 0.08


def log(msg):
    sys.stderr.write("mixerd: %s\n" % msg)
    sys.stderr.flush()


class Emitter:
    def __init__(self):
        self._lock = threading.Lock()

    def __call__(self, event, **fields):
        fields["ev"] = event
        line = json.dumps(fields, separators=(",", ":"))
        with self._lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, ValueError):
                os._exit(0)


emit = Emitter()


def run(args, timeout=6):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def pactl_json(what):
    code, out, err = run(["pactl", "-f", "json", "list", what])
    if code != 0:
        raise OSError(err.strip() or "pactl list %s failed" % what)
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise OSError("pactl returned unparseable JSON: %s" % exc)
    return data if isinstance(data, list) else []


def average_volume(volume):
    """PulseAudio reports per-channel volume; the UI wants one number.

    Uses the loudest channel rather than the mean, because a stream panned
    hard left would otherwise read as half volume and snap to centre the
    moment anyone touched the slider.
    """
    if not isinstance(volume, dict) or not volume:
        return 0.0
    peak = 0
    for channel in volume.values():
        if isinstance(channel, dict):
            with contextlib.suppress(TypeError, ValueError):
                peak = max(peak, int(channel.get("value", 0)))
    return round(peak / 65536.0, 4)


def friendly_name(properties):
    """The name a person would recognise, not the one the graph uses.

    Only the binary-name fallback gets capitalised. `application.name` and
    `media.name` are display strings the application chose for itself, and
    plenty of them are deliberately lowercase - mpv, qutebrowser, yt-dlp -
    so title-casing those is not a tidy-up, it is getting the name wrong.
    """
    props = properties or {}

    # The app's own display name, if it set one.
    value = props.get("application.name")
    if value and str(value).strip():
        return str(value).strip()

    # Then the binary. This ranks above media.name on purpose: media.name is
    # usually a generic stream label - "Playback", "AudioStream" - so
    # preferring it turns Spotify into "Playback" in the list.
    binary = props.get("application.process.binary")
    if binary and str(binary).strip():
        name = str(binary).strip()
        return name[:1].upper() + name[1:]

    for key in ("media.name", "node.name"):
        value = props.get(key)
        if value and str(value).strip():
            return str(value).strip()

    return "Unknown"


def icon_for(properties):
    props = properties or {}
    for key in ("application.icon_name", "application.process.binary", "application.name"):
        value = props.get(key)
        if value:
            return str(value).lower()
    return ""


class Mixer:
    def __init__(self):
        self.running = True
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.last = None

    # -- reading -----------------------------------------------------------

    def snapshot(self, force=False):
        try:
            inputs = pactl_json("sink-inputs")
            sinks = pactl_json("sinks")
        except OSError as exc:
            emit("error", message=str(exc))
            return

        code, out, _ = run(["pactl", "get-default-sink"])
        default_sink = out.strip() if code == 0 else ""

        outputs = []
        by_index = {}
        for s in sinks:
            index = s.get("index")
            name = s.get("name", "")
            by_index[index] = name
            outputs.append({
                "index": index,
                "name": name,
                "label": s.get("description") or name,
                "volume": average_volume(s.get("volume")),
                "mute": bool(s.get("mute")),
                "isDefault": name == default_sink,
                "state": (s.get("state") or "").lower(),
            })
        outputs.sort(key=lambda o: (not o["isDefault"], o["label"].lower()))

        streams = []
        for i in inputs:
            props = i.get("properties") or {}
            sink_index = i.get("sink")
            streams.append({
                "id": i.get("index"),
                "name": friendly_name(props),
                "detail": (props.get("media.name") or "")[:60],
                "icon": icon_for(props),
                "volume": average_volume(i.get("volume")),
                "mute": bool(i.get("mute")),
                "corked": bool(i.get("corked")),
                "sink": sink_index,
                "sinkName": by_index.get(sink_index, ""),
            })
        # Streams that are actually making noise first; then by name, so the
        # list does not reshuffle every time something pauses.
        streams.sort(key=lambda s: (s["corked"], s["name"].lower()))

        payload = {"streams": streams, "outputs": outputs, "defaultSink": default_sink}
        if not force and payload == self.last:
            return
        self.last = payload
        emit("snapshot", at=int(time.time()), **payload)

    # -- writing -----------------------------------------------------------

    def set_stream_volume(self, stream_id, level):
        level = max(0.0, min(1.5, float(level)))
        run(["pactl", "set-sink-input-volume", str(stream_id),
             "%d%%" % round(level * 100)])
        self.wake.set()

    def set_stream_mute(self, stream_id, mute):
        run(["pactl", "set-sink-input-mute", str(stream_id), "1" if mute else "0"])
        self.wake.set()

    def move_stream(self, stream_id, sink):
        code, _, err = run(["pactl", "move-sink-input", str(stream_id), str(sink)])
        if code != 0:
            emit("error", message=(err.strip() or "Could not move that stream.")[:160])
        self.wake.set()

    def set_sink_volume(self, sink, level):
        level = max(0.0, min(1.5, float(level)))
        run(["pactl", "set-sink-volume", str(sink), "%d%%" % round(level * 100)])
        self.wake.set()

    def set_sink_mute(self, sink, mute):
        run(["pactl", "set-sink-mute", str(sink), "1" if mute else "0"])
        self.wake.set()

    def set_default_sink(self, sink, move_streams=True):
        code, _, err = run(["pactl", "set-default-sink", str(sink)])
        if code != 0:
            emit("error", message=(err.strip() or "Could not switch output.")[:160])
            return
        if move_streams:
            # Changing the default does nothing for audio that is already
            # playing, which is not what anybody means when they pick a new
            # output. Bring the existing streams along.
            with contextlib.suppress(OSError):
                for i in pactl_json("sink-inputs"):
                    run(["pactl", "move-sink-input", str(i.get("index")), str(sink)])
        self.wake.set()

    # -- loops -------------------------------------------------------------

    def subscribe_loop(self):
        """Follow `pactl subscribe` and wake the reader on relevant events."""
        while self.running:
            try:
                proc = subprocess.Popen(["pactl", "subscribe"],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
            except (OSError, subprocess.SubprocessError) as exc:
                log("cannot subscribe: %s" % exc)
                time.sleep(5)
                continue

            try:
                for line in proc.stdout:
                    if not self.running:
                        break
                    if "sink-input" in line or "sink" in line or "server" in line:
                        self.wake.set()
            except (OSError, ValueError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    proc.terminate()
            if self.running:
                time.sleep(2)      # pactl died; give the daemon a moment

    def reader_loop(self):
        while self.running:
            self.snapshot()
            # Wait for either an event or the safety interval, then coalesce
            # whatever else arrives in the next few milliseconds.
            self.wake.wait(SAFETY_POLL)
            if self.wake.is_set():
                time.sleep(COALESCE)
            self.wake.clear()


def handle_command(mixer, msg):
    cmd = msg.get("cmd")
    if cmd == "refresh":
        mixer.snapshot(force=True)
    elif cmd == "volume":
        mixer.set_stream_volume(msg.get("id"), msg.get("value", 1.0))
    elif cmd == "mute":
        mixer.set_stream_mute(msg.get("id"), bool(msg.get("value")))
    elif cmd == "move":
        mixer.move_stream(msg.get("id"), msg.get("sink"))
    elif cmd == "sinkVolume":
        mixer.set_sink_volume(msg.get("sink"), msg.get("value", 1.0))
    elif cmd == "sinkMute":
        mixer.set_sink_mute(msg.get("sink"), bool(msg.get("value")))
    elif cmd == "defaultSink":
        mixer.set_default_sink(msg.get("sink"), msg.get("moveStreams", True))
    elif cmd == "quit":
        mixer.running = False
        mixer.wake.set()


def main():
    if not shutil.which("pactl"):
        emit("error", message="pactl is not installed. It ships with pipewire-pulse, "
                              "which Omarchy normally has: pacman -S pipewire-pulse")
        emit("ready", available=False)
        # Stay alive so the widget can show the message rather than a dead helper.
        for _ in sys.stdin:
            pass
        return

    mixer = Mixer()
    emit("ready", available=True)
    threading.Thread(target=mixer.reader_loop, daemon=True).start()
    threading.Thread(target=mixer.subscribe_loop, daemon=True).start()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        try:
            handle_command(mixer, msg)
        except Exception as exc:                        # noqa: BLE001
            log("command %r failed: %s" % (msg.get("cmd"), exc))
            emit("error", message=str(exc))
        if not mixer.running:
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
