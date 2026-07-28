"""
plain_english.py — a small, offline "explain this to a human" layer on top
of the technical packet dissection in pcap_parser.py.

This is a curated knowledge base + template engine, not a live AI call: for
every packet shape PacketLens can dissect (ARP, DNS, TCP handshake stages,
HTTP request/response, ICMP ping, generic TCP/UDP), there's a hand-written
explanation template. That keeps PacketLens fully offline and dependency-free
(no API key, no network call, no per-analysis cost) while still translating
"TCP [SYN,ACK] Seq=5000 Ack=1001 Win=64240" into something a non-network-
engineer can read without a glossary.

Two entry points:
  annotate_packet(pkt)          -> mutates pkt["summary"]["plain"] in place
  capture_narrative(packets, stats) -> one paragraph describing the whole capture
"""

PROTO_PLAIN_NAMES = {
    "HTTP": "web page loading (HTTP)",
    "HTTP-ALT": "web traffic on an alternate port",
    "TLS/HTTPS": "secure web browsing (HTTPS)",
    "DNS": "looking up website addresses (DNS)",
    "SSH": "a secure remote terminal session (SSH)",
    "FTP": "file transfer (FTP)",
    "FTP-DATA": "file transfer data (FTP)",
    "TELNET": "an unencrypted remote terminal session (Telnet)",
    "SMTP": "sending email (SMTP)",
    "POP3": "checking email (POP3)",
    "IMAP": "checking email (IMAP)",
    "NTP": "syncing the clock with a time server (NTP)",
    "DHCP": "getting network settings automatically (DHCP)",
    "SMB": "shared file/printer access on a local network (SMB)",
    "MySQL": "a database connection (MySQL)",
    "RDP": "a remote desktop session (RDP)",
    "PostgreSQL": "a database connection (PostgreSQL)",
    "ARP": "devices finding each other's hardware addresses on the local network (ARP)",
    "ICMP": "connectivity checks / pings (ICMP)",
    "TCP": "general data exchange (TCP)",
    "UDP": "general data exchange (UDP)",
}


def _service_context(port_a, port_b, well_known_lookup):
    """Return a short ' (this looks like X traffic)' clause, or ''."""
    for p in (port_a, port_b):
        name = well_known_lookup.get(p)
        if name:
            return " (this looks like %s traffic)" % PROTO_PLAIN_NAMES.get(name, name)
    return ""


# Imported lazily to avoid a circular import at module load time.
def _well_known_ports():
    from pcap_parser import WELL_KNOWN_PORTS
    return WELL_KNOWN_PORTS


def packet_plain_sentence(pkt):
    """Build a one-to-two-sentence, jargon-light explanation of a single
    dissected packet. Falls back to a generic sentence for anything not
    specifically templated below."""
    summary = pkt.get("summary", {})
    layers = pkt.get("layers", {})
    proto = summary.get("protocol", "")
    src = summary.get("src", "a device")
    dst = summary.get("dst", "another device")

    if "arp" in layers:
        arp = layers["arp"]
        if arp.get("opcode") == "Request":
            return (
                "%s is asking everyone on the local network: “Who has the "
                "address %s?” This is a normal, routine step — devices do "
                "this to find each other's hardware (MAC) address before they "
                "can talk directly, similar to looking up a phone number "
                "before calling." % (arp["sender_ip"], arp["target_ip"])
            )
        return (
            "%s answered an address lookup: “That's me — my hardware "
            "address is %s.”" % (arp["sender_ip"], arp["sender_mac"])
        )

    if "icmp" in layers:
        icmp = layers["icmp"]
        if icmp.get("type") == 8:
            return (
                "%s is pinging %s — sending a quick “are you there?” "
                "check that's commonly used to test whether a device is "
                "reachable on the network." % (src, dst)
            )
        if icmp.get("type") == 0:
            return (
                "%s replied to a ping from %s, confirming it's online and "
                "reachable." % (src, dst)
            )
        return (
            "%s sent %s a network status/control message (ICMP type %d, "
            "code %d)." % (src, dst, icmp.get("type", -1), icmp.get("code", -1))
        )

    if "udp" in layers:
        udp = layers["udp"]
        wkp = _well_known_ports()
        if proto == "DNS":
            if udp["dst_port"] == 53:
                return (
                    "%s is asking a DNS server (%s) to translate a website "
                    "name into its numeric IP address — like looking up a "
                    "phone number by someone's name before you can call "
                    "them." % (src, dst)
                )
            return (
                "The DNS server (%s) sent back the answer to an address "
                "lookup, to %s." % (src, dst)
            )
        service_name = wkp.get(udp["dst_port"]) or wkp.get(udp["src_port"])
        if service_name:
            plain = PROTO_PLAIN_NAMES.get(service_name, service_name)
            return "%s and %s are exchanging %s." % (src, dst, plain)
        return (
            "%s sent a short message to %s (UDP, port %d). UDP is a "
            "lightweight way to send data without first setting up a "
            "connection — often used for things like video calls, games, "
            "or quick lookups where a little data loss is OK." % (src, dst, udp["dst_port"])
        )

    if "tcp" in layers:
        tcp = layers["tcp"]
        flags = set(tcp.get("flags_set", []))
        wkp = _well_known_ports()
        ctx = _service_context(tcp["dst_port"], tcp["src_port"], wkp)
        preview = tcp.get("payload_preview")

        if preview:
            if preview[:3] in ("GET", "PUT") or preview.startswith(("POST", "HEAD", "DELETE", "OPTIONS")):
                return (
                    "%s is sending a web request to %s: “%s” — this is "
                    "a browser or app asking a web server for something." % (src, dst, preview)
                )
            if preview.startswith("HTTP/"):
                return (
                    "%s is sending back a web response to %s: “%s”." % (src, dst, preview)
                )

        if flags == {"SYN"}:
            return (
                "%s is starting a new connection to %s%s — like knocking "
                "on the door and asking “can we talk?”. This is step 1 of "
                "3 in setting up the connection (the TCP handshake)." % (src, dst, ctx)
            )
        if flags == {"SYN", "ACK"}:
            return (
                "%s is answering back, agreeing to open the connection with "
                "%s%s. This is step 2 of 3 in the handshake." % (src, dst, ctx)
            )
        if flags == {"ACK"} and not preview:
            return (
                "%s confirms the connection with %s is open%s. This completes "
                "the handshake (step 3 of 3) — the two sides can now "
                "exchange data." % (src, dst, ctx)
            )
        if "RST" in flags:
            return (
                "%s abruptly reset (cancelled) the connection with %s%s — "
                "this usually means the destination refused the connection, "
                "or something went wrong." % (src, dst, ctx)
            )
        if "FIN" in flags:
            return (
                "%s is closing its connection with %s%s — the conversation "
                "is finished and both sides are done sending data." % (src, dst, ctx)
            )
        if preview:
            return "%s is sending data to %s%s: “%s”" % (src, dst, ctx, preview)
        return "%s and %s are exchanging data over a connection%s." % (src, dst, ctx)

    return "%s sent a network frame to %s (%s)." % (src, dst, proto or "unknown protocol")


def annotate_packet(pkt):
    """Mutate pkt in place, adding 'plain' and 'plain_source' keys to its
    summary. plain_source is always "offline" here — this module never
    calls out to the network; see ai_explainer.py for the Claude-API path,
    which sets plain_source to "ai" instead."""
    try:
        pkt.setdefault("summary", {})["plain"] = packet_plain_sentence(pkt)
    except Exception:
        pkt.setdefault("summary", {})["plain"] = None
    pkt["summary"]["plain_source"] = "offline"
    return pkt


def annotate_packets(packets):
    for p in packets:
        annotate_packet(p)
    return packets


def capture_narrative(packets, stats):
    """One short paragraph summarizing an entire capture in plain language."""
    total = stats.get("total_packets", 0)
    if total == 0:
        return "No packets captured yet."

    sentences = []
    sentences.append(
        "This capture contains %d packet%s." % (total, "s" if total != 1 else "")
    )

    top_convo = stats.get("top_conversations") or []
    if top_convo:
        top = top_convo[0]
        sentences.append(
            "Most of the traffic (%d packet%s) is between %s and %s." % (
                top["packets"], "s" if top["packets"] != 1 else "", top["a"], top["b"]
            )
        )

    proto_counts = stats.get("protocol_counts", {})
    order_priority = [
        "HTTP", "TLS/HTTPS", "DNS", "SSH", "FTP", "SMTP", "RDP", "ARP",
        "ICMP", "TCP", "UDP",
    ]
    descriptions = []
    seen = set()
    for proto in order_priority:
        if proto in proto_counts:
            count = proto_counts[proto]
            plain = PROTO_PLAIN_NAMES.get(proto, proto)
            descriptions.append("%s (%d packet%s)" % (plain, count, "s" if count != 1 else ""))
            seen.add(proto)
    for proto, count in proto_counts.items():
        if proto not in seen:
            plain = PROTO_PLAIN_NAMES.get(proto, "%s traffic" % proto)
            descriptions.append("%s (%d packet%s)" % (plain, count, "s" if count != 1 else ""))

    if descriptions:
        sentences.append("What's happening: " + "; ".join(descriptions) + ".")

    return " ".join(sentences)
