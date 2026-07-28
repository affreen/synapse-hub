"""
capture_agent.py — PacketLens live-capture agent (cross-platform)

WHY THIS EXISTS
----------------
Sniffing live network traffic requires raw-socket / packet-capture
privileges (root on Linux/macOS, Npcap + admin on Windows) on the machine
whose traffic you want to see. A web server sitting in the cloud (or in a
sandbox) cannot reach into your NIC — so real live capture has to happen via
a small local agent that YOU run on your own machine, which then streams
what it sees to the PacketLens web UI.

This script is that agent. It:
  1. Shells out to a capture tool — `tcpdump` (Linux/macOS, and Windows if
     you've separately installed a tcpdump-compatible binary) or `tshark`
     (installed automatically as part of Wireshark, including on Windows,
     alongside the Npcap driver) — to capture raw packets on a chosen
     interface. By default it auto-detects whichever one is on your PATH;
     use --tool to force a specific one.
  2. Parses each packet with the same dissector the backend uses
     (backend/pcap_parser.py) so the JSON shape matches uploaded-file
     analysis exactly.
  3. POSTs each dissected packet to the backend's /api/live/ingest
     endpoint, which fans it out to any browser watching the live view.

REQUIRES ELEVATED PRIVILEGES — this is expected and matches how Wireshark
itself works (dumpcap/tcpdump/tshark need CAP_NET_RAW or admin/root).

USAGE
-----
  # macOS / Linux (tcpdump, usually already installed):
  sudo python3 capture_agent.py --iface eth0 --backend http://localhost:8765

  # Windows (install Wireshark first — it bundles tshark + the Npcap
  # driver — then run from an Administrator terminal):
  python capture_agent.py --iface 1 --backend http://localhost:8765

  # list interfaces first if unsure (works with either tool):
  sudo python3 capture_agent.py --list-interfaces
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import pcap_parser  # noqa: E402


def _detect_tool(preferred=None):
    """Pick which capture tool to use. tcpdump and tshark both understand
    "write pcap-format bytes to stdout" (-w -) and produce byte-for-byte
    compatible output, so everything downstream of this function (the
    incremental pcap-stream reader) works identically either way."""
    candidates = [preferred] if preferred else ["tcpdump", "tshark"]
    for tool in candidates:
        if tool and shutil.which(tool):
            return tool
    return None


def list_interfaces(tool=None):
    chosen = _detect_tool(tool)
    if not chosen:
        sys.stderr.write(
            "[agent] Neither tcpdump nor tshark was found on your PATH.\n"
            "  - macOS/Linux: tcpdump is usually pre-installed; if not, "
            "install it via your package manager.\n"
            "  - Windows: install Wireshark (https://www.wireshark.org/) — "
            "it installs tshark and the Npcap capture driver together.\n"
        )
        return
    flag = "-D"
    out = subprocess.run([chosen, flag], capture_output=True, text=True)
    print("[agent] using %s -- available interfaces:\n" % chosen)
    print(out.stdout or out.stderr)


def post_packet(backend_url, packet_obj):
    data = json.dumps(packet_obj).encode("utf-8")
    req = urllib.request.Request(
        backend_url.rstrip("/") + "/api/live/ingest",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception as e:
        sys.stderr.write("[agent] failed to post packet: %s\n" % e)


def _build_command(tool, iface, count):
    if tool == "tcpdump":
        cmd = ["tcpdump", "-i", iface, "-U", "-w", "-"]
        if count:
            cmd += ["-c", str(count)]
        return cmd
    if tool == "tshark":
        # -l = line-buffered / flush output promptly, matters for streaming
        cmd = ["tshark", "-i", iface, "-w", "-", "-l"]
        if count:
            cmd += ["-c", str(count)]
        return cmd
    raise ValueError("unknown capture tool: %s" % tool)


def run_capture(iface, backend_url, count, tool=None):
    """
    Runs the chosen tool with "write pcap-format bytes to stdout" and
    incrementally parses the stream: one 24-byte global header, then a
    sequence of 16-byte-record-header + payload packet records, exactly
    like a .pcap file — just delivered live instead of read from disk.
    """
    chosen = _detect_tool(tool)
    if not chosen:
        sys.stderr.write(
            "[agent] Neither tcpdump nor tshark was found on your PATH.\n"
            "  - macOS/Linux: install tcpdump (or Wireshark, for tshark).\n"
            "  - Windows: install Wireshark (https://www.wireshark.org/) — "
            "it installs tshark and the Npcap capture driver together, "
            "then re-run this from an Administrator terminal.\n"
        )
        return

    cmd = _build_command(chosen, iface, count)
    print("[agent] starting: %s" % " ".join(cmd))
    print("[agent] streaming dissected packets to %s/api/live/ingest" % backend_url)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    header = _read_exact(proc.stdout, 24)
    if not header:
        stderr_tail = proc.stderr.read().decode("utf-8", "ignore")
        sys.stderr.write(
            "[agent] no output from %s — check permissions (macOS/Linux: "
            "run with sudo; Windows: run from an Administrator terminal) "
            "and the interface name/number (--list-interfaces).\n" % chosen
        )
        if stderr_tail:
            sys.stderr.write("[%s] %s\n" % (chosen, stderr_tail))
        return
    endian = "<" if header[0:4] == b"\xa1\xb2\xc3\xd4" else ">"

    idx = 0
    while True:
        rec_header = _read_exact(proc.stdout, 16)
        if not rec_header:
            break
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + "IIII", rec_header)
        raw = _read_exact(proc.stdout, incl_len)
        if raw is None:
            break
        idx += 1
        try:
            pkt = pcap_parser.dissect_ethernet_frame(raw)
        except Exception as e:
            pkt = {"summary": {"protocol": "MALFORMED", "info": str(e)}, "layers": {}}
        pkt["number"] = idx
        pkt["timestamp"] = ts_sec + ts_usec / 1e6
        pkt["length"] = orig_len
        pkt["captured_length"] = incl_len
        post_packet(backend_url, pkt)
        print("[agent] #%d %s %s -> %s  %s" % (
            idx, pkt["summary"]["protocol"], pkt["summary"].get("src"),
            pkt["summary"].get("dst"), pkt["summary"].get("info", "")))

    err = proc.stderr.read().decode("utf-8", "ignore")
    if err:
        sys.stderr.write("[%s] %s\n" % (chosen, err))


def _read_exact(stream, n):
    if n == 0:
        return b""
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def main():
    ap = argparse.ArgumentParser(description="PacketLens live-capture agent")
    ap.add_argument("--iface", default="any",
                     help="interface to capture on. Default 'any' works with tcpdump on "
                          "Linux; tshark/Windows users should pass a specific interface "
                          "name or number from --list-interfaces (no 'any' pseudo-device "
                          "on Windows/Npcap).")
    ap.add_argument("--backend", default="http://localhost:8765", help="PacketLens backend URL")
    ap.add_argument("--count", type=int, default=0, help="stop after N packets (0 = unlimited)")
    ap.add_argument("--tool", choices=["tcpdump", "tshark"], default=None,
                     help="force a specific capture tool instead of auto-detecting "
                          "(auto-detect prefers tcpdump, then tshark)")
    ap.add_argument("--list-interfaces", action="store_true")
    args = ap.parse_args()

    if args.list_interfaces:
        list_interfaces(args.tool)
        return

    run_capture(args.iface, args.backend, args.count, args.tool)


if __name__ == "__main__":
    main()
