"""
ai_explainer.py — LLM-backed plain-English explanations via the Claude API.

This is the AI-generated counterpart to plain_english.py's offline template
engine. Where plain_english.py pattern-matches packet shapes against
hand-written sentence templates, this module sends the dissected packet
fields to Claude and asks it to write the explanation.

Enable it by setting the ANTHROPIC_API_KEY environment variable (or putting
ANTHROPIC_API_KEY=sk-... in a .env file at the project root — see
_load_dotenv() below). If it's not set, or a call fails for any reason
(network error, rate limit, bad response), callers should fall back to
plain_english.py — see server.py's explain() / explain_live_packet()
wrappers, which do exactly that. PacketLens never breaks or blocks because
the AI is unavailable; it just quietly uses the offline templates instead.

No third-party SDK required: this talks to the Anthropic Messages API
directly over HTTPS using only the standard library (urllib), consistent
with the rest of this project's zero-pip-install philosophy.
"""

import json
import os
import re
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# How many packets to ask Claude to explain in a single request, for batch
# (offline-capture) mode. Keeps prompts/responses a reasonable size even for
# large captures.
BATCH_SIZE = 40

_dotenv_loaded = False


def _load_dotenv():
    """Best-effort loader for a `.env` file at the project root, so people
    who'd rather not fuss with system/PyCharm environment variables can
    just drop ANTHROPIC_API_KEY=sk-... in a text file instead. Silently
    does nothing if no .env file exists. Never overrides a variable that's
    already set in the real environment."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dotenv_path = os.path.join(project_root, ".env")
    if not os.path.exists(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


def is_enabled():
    """True if an API key is configured (env var or .env file)."""
    _load_dotenv()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _model():
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)


def _call_claude(system_prompt, user_prompt, max_tokens, timeout):
    _load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    payload = {
        "model": _model(),
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError("Claude API error %s: %s" % (e.code, detail[:300]))
    except urllib.error.URLError as e:
        raise RuntimeError("Could not reach Claude API: %s" % e.reason)

    content = body.get("content", [])
    text_parts = [c["text"] for c in content if c.get("type") == "text"]
    if not text_parts:
        raise RuntimeError("Claude API returned no text content")
    return "".join(text_parts)


def _extract_json(text):
    """Claude is asked to respond with pure JSON, but strip ```json fences
    defensively in case it wraps the answer anyway."""
    text = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    return json.loads(text)


def _packet_facts(pkt):
    """Compact technical description of one packet, for the prompt. Mirrors
    the same fields plain_english.py's template engine keys off of, so the
    AI has equivalent information to work with."""
    summary = pkt.get("summary", {})
    layers = pkt.get("layers", {})
    facts = {
        "number": pkt.get("number"),
        "protocol": summary.get("protocol"),
        "src": summary.get("src"),
        "dst": summary.get("dst"),
        "length_bytes": pkt.get("length"),
    }
    if "arp" in layers:
        arp = layers["arp"]
        facts["arp"] = {"opcode": arp.get("opcode"), "sender_ip": arp.get("sender_ip"),
                         "target_ip": arp.get("target_ip"), "sender_mac": arp.get("sender_mac")}
    if "icmp" in layers:
        facts["icmp"] = layers["icmp"]
    if "udp" in layers:
        facts["udp"] = {"src_port": layers["udp"].get("src_port"), "dst_port": layers["udp"].get("dst_port")}
    if "tcp" in layers:
        tcp = layers["tcp"]
        facts["tcp"] = {
            "src_port": tcp.get("src_port"), "dst_port": tcp.get("dst_port"),
            "flags": tcp.get("flags_set"), "seq": tcp.get("seq"), "ack": tcp.get("ack"),
        }
        if tcp.get("payload_preview"):
            facts["tcp"]["payload_preview"] = tcp["payload_preview"]
    return facts


_SYSTEM_PROMPT = (
    "You explain network packet captures to people who are NOT network "
    "engineers — plain, everyday language, no unexplained jargon. Use "
    "short, concrete analogies where helpful (e.g. ARP is like asking "
    "'who has this address?' on a shared street; a TCP handshake is like "
    "knocking before entering). Each explanation should be 1-2 sentences. "
    "Be accurate to the technical facts given — do not invent details "
    "that aren't in the data. Respond with ONLY valid JSON, no markdown "
    "fences, no commentary before or after."
)


def explain_batch(packets, stats):
    """AI-generate a plain-English sentence for every packet in `packets`
    (mutates each pkt['summary']['plain'] in place) plus one narrative
    paragraph for the whole capture. Raises on any failure — callers should
    catch and fall back to plain_english.py."""
    if not packets:
        return "No packets captured yet."

    narrative = None
    for start in range(0, len(packets), BATCH_SIZE):
        chunk = packets[start:start + BATCH_SIZE]
        facts = [_packet_facts(p) for p in chunk]

        want_narrative = start == 0  # only ask for the overall narrative once
        user_prompt = (
            "Here are dissected network packets as JSON facts:\n\n"
            + json.dumps(facts, indent=None)
            + "\n\nProtocol counts across the WHOLE capture: " + json.dumps(stats.get("protocol_counts", {}))
            + "\nTotal packets in the whole capture: " + str(stats.get("total_packets"))
            + "\n\nRespond with a JSON object of this exact shape:\n"
            + '{"packets": ["<one explanation per packet, in the same order given, as an array of strings>"]'
            + (', "narrative": "<one short paragraph (2-4 sentences) summarizing what this whole capture shows, in plain English>"' if want_narrative else "")
            + "}"
        )

        max_tokens = 220 * len(chunk) + (300 if want_narrative else 0) + 200
        raw = _call_claude(_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens, timeout=45)
        parsed = _extract_json(raw)

        explanations = parsed["packets"]
        if len(explanations) != len(chunk):
            raise RuntimeError(
                "Claude returned %d explanations for %d packets" % (len(explanations), len(chunk))
            )
        for pkt, sentence in zip(chunk, explanations):
            pkt.setdefault("summary", {})["plain"] = sentence
            pkt["summary"]["plain_source"] = "ai"

        if want_narrative:
            narrative = parsed.get("narrative")

    return narrative or ""


def explain_single(pkt):
    """AI-generate a plain-English sentence for one packet (used for live
    capture, where packets arrive one at a time). Raises on failure."""
    facts = _packet_facts(pkt)
    user_prompt = (
        "Here is one dissected network packet as JSON facts:\n\n"
        + json.dumps(facts)
        + "\n\nRespond with ONLY a JSON object of this exact shape: "
        + '{"explanation": "<1-2 sentence plain-English explanation>"}'
    )
    raw = _call_claude(_SYSTEM_PROMPT, user_prompt, max_tokens=220, timeout=12)
    parsed = _extract_json(raw)
    return parsed["explanation"]
