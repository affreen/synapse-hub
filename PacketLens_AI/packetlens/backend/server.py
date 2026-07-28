"""
server.py — PacketLens backend (stdlib only, no pip install required)

Endpoints:
  GET  /                     -> frontend UI
  GET  /app.js, /style.css   -> static assets
  POST /api/upload           -> upload raw .pcap bytes, get back parsed packets + stats
  GET  /api/sample           -> parse the bundled sample.pcap (quick demo, no upload needed)
  GET  /api/live/stream      -> Server-Sent-Events stream of live packets (for the browser)
  POST /api/live/ingest      -> capture agent posts one packet JSON here (fan-out to subscribers)
  POST /api/live/replay      -> demo mode: loops the sample.pcap packets over SSE to simulate an
                                 ongoing live capture, for environments where no capture agent/root
                                 access is available. Keeps running (looping) until /api/live/stop
                                 is called, a newer replay is started, or nobody is subscribed anymore.
  POST /api/live/stop        -> stop the demo replay loop started by /api/live/replay
  GET  /api/ai/status        -> whether AI (Claude API) explanations are configured/enabled

Explanations ("plain English" sentences per packet) come from one of two
places, picked automatically:
  - backend/ai_explainer.py  — calls the Claude API (needs ANTHROPIC_API_KEY)
  - backend/plain_english.py — offline rule-based templates (always available)
If an API key is configured, AI mode is tried first; any failure (missing
key, network error, bad response) falls back to the offline templates so
the app always produces an explanation.

Run:
  python3 server.py [port]        (default port 8765)

See ../README.md for the full picture, and ../agent/capture_agent.py for the
real live-capture agent that runs locally with elevated privileges.
"""

import copy
import datetime
import json
import os
import sys
import threading
import time
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
import pcap_parser  # noqa: E402
import plain_english  # noqa: E402
import ai_explainer  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
SAMPLE_PCAP = os.path.join(BASE_DIR, "sample.pcap")

STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/app.js": ("app.js", "application/javascript"),
    "/style.css": ("style.css", "text/css"),
}

# --- live-stream pub/sub -------------------------------------------------
_subscribers = []
_subscribers_lock = threading.Lock()


def _broadcast(packet_obj):
    with _subscribers_lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(packet_obj)
            except queue.Full:
                pass


def _has_subscribers():
    with _subscribers_lock:
        return len(_subscribers) > 0


# --- demo-replay loop control ---------------------------------------------
# A monotonically increasing "generation" number identifies the currently
# active replay loop. Starting a new replay, explicitly stopping, or simply
# having no one left listening all invalidate the running loop by making
# its captured generation stale, so it notices (within one packet interval)
# and exits on its own — this avoids ever having two replay loops racing to
# broadcast at once if "Start live" gets clicked more than once.
_replay_generation = 0
_replay_lock = threading.Lock()


def _begin_new_replay():
    global _replay_generation
    with _replay_lock:
        _replay_generation += 1
        return _replay_generation


def _stop_replay():
    global _replay_generation
    with _replay_lock:
        _replay_generation += 1


def _replay_generation_is_current(my_gen):
    with _replay_lock:
        return _replay_generation == my_gen


def _explain_batch_with_fallback(packets, stats):
    """Try AI explanations for a whole capture; fall back to the offline
    templates (for all packets) if the AI call fails in any way."""
    if ai_explainer.is_enabled():
        try:
            narrative = ai_explainer.explain_batch(packets, stats)
            if narrative:
                return narrative
        except Exception as e:
            sys.stderr.write("[ai] batch explanation failed, falling back to offline templates: %s\n" % e)
            # Some packets in an earlier chunk may have gotten AI explanations
            # before a later chunk failed; only fill in the ones still missing.
    plain_english.annotate_packets([p for p in packets if not p.get("summary", {}).get("plain")])
    return plain_english.capture_narrative(packets, stats)


def _explain_single_with_fallback(pkt):
    """Try an AI explanation for one live packet; fall back to the offline
    template if it fails (missing key, network error, timeout, etc.)."""
    if ai_explainer.is_enabled():
        try:
            sentence = ai_explainer.explain_single(pkt)
            pkt.setdefault("summary", {})["plain"] = sentence
            pkt["summary"]["plain_source"] = "ai"
            return
        except Exception as e:
            sys.stderr.write("[ai] live explanation failed, falling back to offline template: %s\n" % e)
    plain_english.annotate_packet(pkt)
    pkt["summary"]["plain_source"] = "offline"


def _parsed_response(packets, meta):
    stats = pcap_parser.summarize_capture(packets)
    narrative = _explain_batch_with_fallback(packets, stats)
    stats["narrative"] = narrative
    meta["ai_enabled"] = ai_explainer.is_enabled()
    body = {"packets": packets, "meta": meta, "stats": stats}
    return json.dumps(body).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PacketLens/0.3"

    def log_message(self, fmt, *args):
        sys.stderr.write("[server] " + (fmt % args) + "\n")

    def _send_json(self, obj, status=200):
        payload = json.dumps(obj).encode("utf-8") if not isinstance(obj, (bytes, bytearray)) else obj
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    # ---- GET ----
    def do_GET(self):
        parsed_path = self.path.split("?")[0]

        if parsed_path in STATIC_FILES:
            fname, ctype = STATIC_FILES[parsed_path]
            fpath = os.path.join(FRONTEND_DIR, fname)
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                self._send_error_json("not found", 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed_path == "/api/sample":
            try:
                with open(SAMPLE_PCAP, "rb") as f:
                    data = f.read()
                packets, meta = pcap_parser.parse_pcap_bytes(data)
            except Exception as e:
                self._send_error_json(str(e), 500)
                return
            self._send_json_bytes(_parsed_response(packets, meta))
            return

        if parsed_path == "/api/live/stream":
            self._handle_sse()
            return

        if parsed_path == "/api/ai/status":
            self._send_json({
                "ai_enabled": ai_explainer.is_enabled(),
                "model": ai_explainer._model() if ai_explainer.is_enabled() else None,
            })
            return

        self._send_error_json("not found", 404)

    def _send_json_bytes(self, payload_bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload_bytes)

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = queue.Queue(maxsize=1000)
        with _subscribers_lock:
            _subscribers.append(q)
        try:
            while True:
                try:
                    packet_obj = q.get(timeout=15)
                    chunk = ("data: %s\n\n" % json.dumps(packet_obj)).encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except queue.Empty:
                    # heartbeat comment to keep the connection alive
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _subscribers_lock:
                if q in _subscribers:
                    _subscribers.remove(q)

    # ---- POST ----
    def do_POST(self):
        parsed_path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if parsed_path == "/api/upload":
            try:
                packets, meta = pcap_parser.parse_pcap_bytes(body)
            except pcap_parser.PcapParseError as e:
                self._send_error_json(str(e), 400)
                return
            except Exception as e:
                self._send_error_json("failed to parse file: %s" % e, 400)
                return
            self._send_json_bytes(_parsed_response(packets, meta))
            return

        if parsed_path == "/api/live/ingest":
            # A real capture agent (agent/capture_agent.py) POSTs one
            # dissected packet (JSON) here. We explain it (AI if configured,
            # else offline template) and fan it out to every browser
            # currently subscribed via /api/live/stream.
            try:
                packet_obj = json.loads(body.decode("utf-8"))
            except Exception:
                self._send_error_json("invalid JSON", 400)
                return
            _explain_single_with_fallback(packet_obj)
            _broadcast(packet_obj)
            self._send_json({"ok": True})
            return

        if parsed_path == "/api/live/replay":
            # Demo mode: no privileged capture agent available, so loop the
            # bundled sample.pcap's packets over the SSE channel at a
            # watchable pace, continuing indefinitely (like a real ongoing
            # capture) until stopped. Exercises the exact same UI code path
            # real live packets would use, AI explanations included.
            my_gen = _begin_new_replay()
            threading.Thread(target=self._replay_sample_loop, args=(my_gen,), daemon=True).start()
            self._send_json({"ok": True, "mode": "replay"})
            return

        if parsed_path == "/api/live/stop":
            _stop_replay()
            self._send_json({"ok": True})
            return

        self._send_error_json("not found", 404)

    def _replay_sample_loop(self, my_gen):
        try:
            with open(SAMPLE_PCAP, "rb") as f:
                data = f.read()
            packets, _meta = pcap_parser.parse_pcap_bytes(data)
        except Exception as e:
            _broadcast({"summary": {"protocol": "ERROR", "info": str(e)}})
            return

        counter = 0
        lap = 0
        while _replay_generation_is_current(my_gen):
            lap += 1
            for template_pkt in packets:
                if not _replay_generation_is_current(my_gen):
                    return
                # Only start checking for "nobody's listening anymore" after
                # a full lap — the browser's EventSource connects within
                # milliseconds of the request that kicked this loop off, but
                # checking from packet #1 risked a race where this thread
                # checks before that connection has registered. One full lap
                # (~7s) is a large, safe margin, and still cleans up an
                # abandoned loop (tab closed without clicking Stop) reasonably
                # promptly rather than spinning forever.
                if lap > 1 and not _has_subscribers():
                    return

                counter += 1
                pkt = copy.deepcopy(template_pkt)
                pkt["number"] = counter
                now = time.time()
                pkt["timestamp"] = now
                pkt["timestamp_iso"] = datetime.datetime.utcfromtimestamp(now).isoformat() + "Z"

                _explain_single_with_fallback(pkt)
                _broadcast(pkt)
                time.sleep(0.6)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("PacketLens backend listening on http://localhost:%d" % port)
    print("AI explanations: %s" % ("ON (%s)" % ai_explainer._model() if ai_explainer.is_enabled() else "OFF (set ANTHROPIC_API_KEY to enable)"))
    print("Open that URL in a browser to use the UI.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
