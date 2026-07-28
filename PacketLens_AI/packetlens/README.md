# PacketLens

A Wireshark-style packet capture & analysis tool with a web UI. Open a
`.pcap` file, or stream your own live traffic in through a local capture
agent, and get a searchable packet list, per-layer detail view, and
protocol/conversation statistics — in your browser.

Every packet also gets a **plain-English explanation** (toggle "Plain
English" / "Technical" in the toolbar) — so it's usable by people who
aren't network engineers, not just by protocol experts. Explanations come
from the **Claude API** when configured (see below), and automatically
fall back to a built-in offline template library if no API key is set or
a call fails for any reason — the app never breaks either way.

See `PacketLens_Design_Doc.docx` for the full architecture write-up.

## Enabling AI-generated explanations (Claude API)

By default PacketLens uses offline templates (`backend/plain_english.py`)
— free, instant, no setup. To get richer, adaptive explanations generated
by Claude instead (`backend/ai_explainer.py`), set an environment variable
with your Anthropic API key:

**In PyCharm:** Run → Edit Configurations… → select "Run PacketLens
server" → Environment variables → add `ANTHROPIC_API_KEY=sk-ant-...`.

**From a terminal (macOS/Linux):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 backend/server.py
```

**From a terminal (Windows PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python backend/server.py
```

**Or drop a `.env` file** in the `packetlens` folder (next to this README)
containing:
```
ANTHROPIC_API_KEY=sk-ant-...
```
This is picked up automatically at startup — convenient if you don't want
to fuss with system/IDE environment variables. `.env` is already listed in
`.gitignore` so it won't get committed if you put this project in git.

The server prints which mode it's using on startup, and the toolbar shows
a live status pill ("🤖 AI explanations: ON" / "OFF"). You can also check
`http://localhost:8765/api/ai/status` directly.

By default it uses `claude-haiku-4-5-20251001` (fast and inexpensive, a
good fit for short per-packet explanations). Override with
`ANTHROPIC_MODEL=claude-sonnet-5` (or any other model string) if you want
different quality/cost tradeoffs.

**Cost/latency note:** offline analysis (upload/sample) batches all
packets into one API call per ~40 packets. Live capture calls the API once
per packet as it arrives, which adds a per-packet delay (network
round-trip) and cost that scales with traffic volume — reasonable for
casual/demo use, but something to be aware of on a busy interface.

## Opening in PyCharm

1. Unzip the package, then in PyCharm: **File → Open…** and select the
   `packetlens` folder (the one containing this README).
2. PyCharm will detect it as a Python project (`.idea/` is already set up).
   If it prompts for an interpreter, pick any Python **3.8+** — there are no
   packages to install (`requirements.txt` is intentionally empty; the
   Claude API integration uses only `urllib`, already in the standard
   library — see the comments in that file).
3. Two run configurations are included and should show up in the
   configuration dropdown at the top right:
   - **Run PacketLens server** — runs `backend/server.py`.
   - **Run all tests** — runs everything in `tests/` with `unittest`.

   If they don't appear (PyCharm sometimes needs a "Trust Project" click
   first, or a reopen), just right-click the file directly (see below) —
   nothing depends on the saved run configs working.

## Testing

Automated tests (`tests/test_pcap_parser.py`, `tests/test_ai_explainer.py`)
check the protocol dissector and the AI module's pure logic (JSON parsing,
`.env` loading, enable/disable detection) — 18 tests total, all offline and
deterministic. They do **not** call the real Claude API (that wouldn't be
reproducible without a live key), so the API integration itself is verified
manually:

- **In PyCharm:** right-click the `tests` folder → **Run 'Unittests in
  tests'** (or use the included **Run all tests** configuration). You
  should see 18 tests pass.
- **From a terminal:**
  ```bash
  cd packetlens
  python3 -m unittest discover -s tests -v
  ```

Manually testing the app itself (the part unit tests don't cover — the UI
and the live Claude API calls):

1. Run the server: right-click `backend/server.py` → **Run 'server'** (or
   use the **Run PacketLens server** configuration, or `python3
   backend/server.py` from a terminal).
2. Open **http://localhost:8765** in a browser.
3. Check the **🤖 AI explanations** pill in the toolbar — it should say ON
   (with a model name) if you set `ANTHROPIC_API_KEY`, or OFF otherwise.
4. Click **Load sample** — you should see 12 packets (ARP, DNS, a TCP/HTTP
   handshake, ICMP), a plain-English summary in the sidebar ("What's
   happening"), a protocol pie chart, and top conversations. If AI mode is
   on, these sentences come from Claude; check the server terminal for any
   `[ai] ... failed, falling back to offline templates` warnings, which
   mean the call didn't succeed (bad key, no network, rate limit) and the
   offline templates kicked in instead — the app should still work either way.
5. Click a row — the detail panel below the table should show a highlighted
   plain-English sentence at the top (labeled "AI-generated" or "offline
   template" depending on which was used), followed by the full technical
   Ethernet/IP/TCP (or UDP/ARP/ICMP) field breakdown.
6. Toggle **Plain English** / **Technical** in the toolbar — the table's
   Info column should switch between everyday sentences and raw protocol
   fields (e.g. `[SYN,ACK] Seq=5000 Ack=1001 Win=64240`).
7. Type into the search box — try `tcp`, `arp`, `ping`, `webpage`, or
   `ip==192.168.1.50` — the table should narrow to matching rows (plain-English
   text is searchable too, not just protocol jargon).
8. Click **Open capture…** and pick any real classic-format `.pcap` file
   (e.g. exported from Wireshark via *File → Save As → Wireshark/tcpdump…
   pcap*) to confirm upload+parse works on real captures, not just the demo
   one.
9. Click **Start live (demo)** — packets should stream into the table one
   at a time, and keep going indefinitely (looping back through the sample
   capture) until you click **Stop live** — this replays the sample capture
   over the same live pipe a real capture agent uses; each packet is
   explained — AI or offline fallback — before it reaches the browser.
   Packet numbers keep counting up across loops (13, 14, 15...) rather than
   resetting, so it reads like one continuous ongoing capture.

To test **real** live capture, run the agent locally with elevated
privileges while the server above is running:

```bash
sudo python3 agent/capture_agent.py --iface en0 --backend http://localhost:8765
```

(swap `en0` for your interface name — `sudo python3
agent/capture_agent.py --list-interfaces` lists them). Generate some
traffic (browse a site, ping something) and confirm packets appear in the
UI's live view in real time.

## Quick start (offline analysis — works immediately, no privileges needed)

```bash
cd backend
python3 server.py          # starts on http://localhost:8765
```

Open http://localhost:8765 in a browser, then click **"Load sample"** to see
a bundled demo capture, or **"Open capture…"** to analyze your own `.pcap`
file (classic pcap format; pcapng is not yet supported — see the design doc).

No third-party packages to install — the backend, dissector, and Claude API
client all use only the Python standard library.

## Live capture (real traffic from your own machine)

Live packet capture needs OS-level privileges (root / admin), the same way
Wireshark's own capture engine (`dumpcap`) does. The agent auto-detects
`tcpdump` or `tshark`, whichever is on your PATH, so it works the same way
on macOS, Linux, and Windows.

**macOS / Linux** (tcpdump is usually already installed):
```bash
sudo python3 agent/capture_agent.py --iface eth0 --backend http://localhost:8765
```

**Windows** — install [Wireshark](https://www.wireshark.org/download.html)
first (it installs `tshark` plus the Npcap capture driver — you don't need
Wireshark's GUI, just the install). Then, from an **Administrator**
terminal (PowerShell or Command Prompt — right-click, "Run as
administrator"):
```powershell
python agent\capture_agent.py --iface 1 --backend http://localhost:8765
```
Windows/Npcap interfaces are numbered rather than named, and there's no
`any`-all-interfaces pseudo-device like on Linux — run
`--list-interfaces` first (see below) to find the right number for your
network adapter.

Then click **"Start live (demo)"** in the UI while the agent is running —
real packets from your interface will stream in instead of the demo replay.

**Finding your interface name/number** (works on any OS):
```bash
python3 agent/capture_agent.py --list-interfaces
```

**Forcing a specific tool** if you have both installed and auto-detection
picks the wrong one: add `--tool tcpdump` or `--tool tshark`.

> In this project's own build/test sandbox there's no raw-socket access or
> real NIC to capture from, so the "Start live (demo)" button replays the
> sample capture over the exact same streaming pipe a real agent uses
> (`/api/live/replay`) — that's a demo fallback, not a limitation of the
> real agent.

## Regenerating the sample capture

```bash
python3 make_sample_pcap.py
```

Rewrites `sample.pcap` — a hand-crafted mix of ARP, a DNS query/response, a
full TCP handshake + HTTP request/response + FIN, and an ICMP ping.

## Layout

```
backend/pcap_parser.py     stdlib-only pcap parser + protocol dissector
backend/plain_english.py   offline knowledge base — rule-based plain-English
                            explanations, always available, zero dependencies
backend/ai_explainer.py    Claude API client (stdlib urllib) — richer,
                            adaptive explanations when ANTHROPIC_API_KEY is set
backend/server.py          HTTP + SSE server (upload / sample / live / AI status)
agent/capture_agent.py     privileged local live-capture agent (needs sudo)
frontend/                  packet table, detail pane, filter, chart (no build step)
make_sample_pcap.py        generates sample.pcap
PacketLens_Design_Doc.docx full architecture & roadmap document
```
