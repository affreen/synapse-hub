"""
pcap_parser.py

A dependency-free (stdlib-only) parser and protocol dissector for classic
libpcap (.pcap) capture files. Produces the same kind of per-packet summary
and per-layer detail that Wireshark's packet list / detail panes show.

Supported link-layer: Ethernet (LINKTYPE_ETHERNET = 1)
Supported network/transport layers: ARP, IPv4, IPv6 (basic), ICMP, TCP, UDP

This intentionally avoids third-party libraries (scapy, dpkt, pyshark) so the
prototype runs anywhere Python 3 runs, with zero install step.
"""

import struct
import socket
import datetime

# ---- Constants -------------------------------------------------------

ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806
ETHERTYPE_IPV6 = 0x86DD

IP_PROTO_ICMP = 1
IP_PROTO_TCP = 6
IP_PROTO_UDP = 17

TCP_FLAG_NAMES = [
    (0x01, "FIN"), (0x02, "SYN"), (0x04, "RST"), (0x08, "PSH"),
    (0x10, "ACK"), (0x20, "URG"), (0x40, "ECE"), (0x80, "CWR"),
]

WELL_KNOWN_PORTS = {
    20: "FTP-DATA", 21: "FTP", 22: "SSH", 23: "TELNET", 25: "SMTP",
    53: "DNS", 67: "DHCP", 68: "DHCP", 80: "HTTP", 110: "POP3",
    123: "NTP", 143: "IMAP", 443: "TLS/HTTPS", 445: "SMB",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 8080: "HTTP-ALT",
}


class PcapParseError(Exception):
    pass


def _mac(raw6):
    return ":".join("%02x" % b for b in raw6)


def _guess_service(sport, dport):
    for p in (sport, dport):
        if p in WELL_KNOWN_PORTS:
            return WELL_KNOWN_PORTS[p]
    return None


def parse_pcap_bytes(data):
    """Parse raw bytes of a classic .pcap file. Returns (packets, meta)."""
    if len(data) < 24:
        raise PcapParseError("File too small to be a valid pcap")

    magic = data[0:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian, ts_is_ns = "<", False
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian, ts_is_ns = ">", False
    elif magic == b"\x4d\x3c\xb2\xa1":
        endian, ts_is_ns = "<", True
    elif magic == b"\xa1\xb2\x3c\x4d":
        endian, ts_is_ns = ">", True
    elif data[0:4] == b"\x0a\x0d\x0d\x0a":
        raise PcapParseError(
            "This looks like a pcapng file. This prototype currently "
            "supports classic .pcap only (Wireshark: File > Save As > "
            ".pcap format)."
        )
    else:
        raise PcapParseError("Not a recognized pcap file (bad magic number)")

    version_major, version_minor, thiszone, sigfigs, snaplen, network = \
        struct.unpack(endian + "HHiIII", data[4:24])

    if network != 1:
        raise PcapParseError(
            "Only Ethernet-linktype captures are supported in this "
            "prototype (found linktype=%d)" % network
        )

    packets = []
    offset = 24
    idx = 0
    while offset + 16 <= len(data):
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
            endian + "IIII", data[offset:offset + 16]
        )
        offset += 16
        if offset + incl_len > len(data):
            break
        raw = data[offset:offset + incl_len]
        offset += incl_len
        idx += 1

        ts = ts_sec + (ts_usec / 1e9 if ts_is_ns else ts_usec / 1e6)
        try:
            pkt = _dissect_ethernet_frame(raw)
        except Exception as e:  # keep going even on malformed frames
            pkt = {"summary": {"protocol": "MALFORMED", "info": str(e)},
                   "layers": {}}

        pkt["number"] = idx
        pkt["timestamp"] = ts
        pkt["timestamp_iso"] = datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z"
        pkt["length"] = orig_len
        pkt["captured_length"] = incl_len
        packets.append(pkt)

    meta = {
        "version": "%d.%d" % (version_major, version_minor),
        "snaplen": snaplen,
        "packet_count": len(packets),
    }
    return packets, meta


def _dissect_ethernet_frame(raw):
    if len(raw) < 14:
        raise ValueError("Ethernet frame too short")

    dst_mac = _mac(raw[0:6])
    src_mac = _mac(raw[6:12])
    ethertype = struct.unpack(">H", raw[12:14])[0]

    layers = {
        "ethernet": {
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "ethertype": "0x%04x" % ethertype,
        }
    }
    payload = raw[14:]

    summary = {
        "src": src_mac,
        "dst": dst_mac,
        "protocol": "ETH",
        "info": "Ethertype 0x%04x" % ethertype,
    }

    if ethertype == ETHERTYPE_IPV4:
        ip_info = _dissect_ipv4(payload)
        layers["ipv4"] = ip_info["layer"]
        summary.update(src=ip_info["layer"]["src_ip"], dst=ip_info["layer"]["dst_ip"])
        summary["protocol"] = ip_info["summary_protocol"]
        summary["info"] = ip_info["summary_info"]
        if "transport_layer" in ip_info:
            layers[ip_info["transport_name"]] = ip_info["transport_layer"]

    elif ethertype == ETHERTYPE_ARP:
        arp = _dissect_arp(payload)
        layers["arp"] = arp
        summary["protocol"] = "ARP"
        summary["src"] = arp["sender_ip"]
        summary["dst"] = arp["target_ip"]
        summary["info"] = arp["info"]

    elif ethertype == ETHERTYPE_IPV6:
        v6 = _dissect_ipv6_basic(payload)
        layers["ipv6"] = v6
        summary["protocol"] = "IPv6"
        summary["src"] = v6["src_ip"]
        summary["dst"] = v6["dst_ip"]
        summary["info"] = "Next header %d" % v6["next_header"]

    return {"summary": summary, "layers": layers}


def _dissect_ipv4(payload):
    if len(payload) < 20:
        raise ValueError("IPv4 header too short")

    b0 = payload[0]
    version = b0 >> 4
    ihl = (b0 & 0x0F) * 4
    total_len = struct.unpack(">H", payload[2:4])[0]
    ttl = payload[8]
    proto = payload[9]
    src_ip = socket.inet_ntoa(payload[12:16])
    dst_ip = socket.inet_ntoa(payload[16:20])

    layer = {
        "version": version,
        "header_len": ihl,
        "total_len": total_len,
        "ttl": ttl,
        "protocol_num": proto,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
    }

    result = {"layer": layer}
    transport_payload = payload[ihl:]

    if proto == IP_PROTO_TCP and len(transport_payload) >= 20:
        tcp = _dissect_tcp(transport_payload)
        app_bytes = transport_payload[tcp["data_offset"]:]
        preview = _extract_text_preview(app_bytes)
        if preview:
            tcp["payload_preview"] = preview
        result["transport_name"] = "tcp"
        result["transport_layer"] = tcp
        service = _guess_service(tcp["src_port"], tcp["dst_port"])
        flags_str = ",".join(tcp["flags_set"]) if tcp["flags_set"] else "-"
        result["summary_protocol"] = service if service else "TCP"
        result["summary_info"] = "%s:%d -> %s:%d [%s] Seq=%d Ack=%d Win=%d" % (
            src_ip, tcp["src_port"], dst_ip, tcp["dst_port"],
            flags_str, tcp["seq"], tcp["ack"], tcp["window"],
        )
    elif proto == IP_PROTO_UDP and len(transport_payload) >= 8:
        udp = _dissect_udp(transport_payload)
        result["transport_name"] = "udp"
        result["transport_layer"] = udp
        service = _guess_service(udp["src_port"], udp["dst_port"])
        result["summary_protocol"] = service if service else "UDP"
        result["summary_info"] = "%s:%d -> %s:%d Len=%d" % (
            src_ip, udp["src_port"], dst_ip, udp["dst_port"], udp["length"],
        )
    elif proto == IP_PROTO_ICMP and len(transport_payload) >= 4:
        icmp = _dissect_icmp(transport_payload)
        result["transport_name"] = "icmp"
        result["transport_layer"] = icmp
        result["summary_protocol"] = "ICMP"
        result["summary_info"] = "Type=%d Code=%d" % (icmp["type"], icmp["code"])
    else:
        result["summary_protocol"] = "IPv4/%d" % proto
        result["summary_info"] = "%s -> %s (proto %d)" % (src_ip, dst_ip, proto)

    return result


def _extract_text_preview(app_bytes, max_len=100):
    """If a TCP segment's application payload looks like printable text
    (e.g. an HTTP request/response line), return a short first-line
    preview of it. Returns None for binary/encrypted/empty payloads."""
    if not app_bytes:
        return None
    sample = app_bytes[:max_len]
    printable = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
    if printable / len(sample) < 0.85:
        return None  # looks binary/encrypted (e.g. TLS) - don't guess
    text = sample.decode("ascii", errors="replace")
    first_line = text.split("\r\n")[0].split("\n")[0].strip()
    return first_line if first_line else None


def _dissect_tcp(payload):
    src_port, dst_port, seq, ack = struct.unpack(">HHII", payload[0:12])
    b12 = payload[12]
    data_offset = (b12 >> 4) * 4
    flags_byte = payload[13]
    window = struct.unpack(">H", payload[14:16])[0]
    flags_set = [name for bit, name in TCP_FLAG_NAMES if flags_byte & bit]
    return {
        "src_port": src_port, "dst_port": dst_port,
        "seq": seq, "ack": ack, "data_offset": data_offset,
        "flags_set": flags_set, "window": window,
    }


def _dissect_udp(payload):
    src_port, dst_port, length, checksum = struct.unpack(">HHHH", payload[0:8])
    return {"src_port": src_port, "dst_port": dst_port, "length": length}


def _dissect_icmp(payload):
    icmp_type, code = payload[0], payload[1]
    return {"type": icmp_type, "code": code}


def _dissect_arp(payload):
    if len(payload) < 28:
        raise ValueError("ARP packet too short")
    hw_type, proto_type, hw_len, proto_len, opcode = struct.unpack(
        ">HHBBH", payload[0:8]
    )
    sender_mac = _mac(payload[8:14])
    sender_ip = socket.inet_ntoa(payload[14:18])
    target_mac = _mac(payload[18:24])
    target_ip = socket.inet_ntoa(payload[24:28])
    op_name = {1: "Request", 2: "Reply"}.get(opcode, "Op-%d" % opcode)
    info = "Who has %s? Tell %s" % (target_ip, sender_ip) if opcode == 1 \
        else "%s is at %s" % (sender_ip, sender_mac)
    return {
        "opcode": op_name, "sender_mac": sender_mac, "sender_ip": sender_ip,
        "target_mac": target_mac, "target_ip": target_ip, "info": info,
    }


def _dissect_ipv6_basic(payload):
    if len(payload) < 40:
        raise ValueError("IPv6 header too short")
    next_header = payload[6]
    src_ip = socket.inet_ntop(socket.AF_INET6, payload[8:24])
    dst_ip = socket.inet_ntop(socket.AF_INET6, payload[24:40])
    return {"next_header": next_header, "src_ip": src_ip, "dst_ip": dst_ip}


# Public alias so other modules (e.g. the live-capture agent) can reuse the
# same Ethernet-frame dissector without depending on a "private" name.
dissect_ethernet_frame = _dissect_ethernet_frame


def summarize_capture(packets):
    """Build protocol-distribution and conversation stats (Wireshark's Statistics menu, in miniature)."""
    proto_counts = {}
    total_bytes = 0
    conversations = {}
    for p in packets:
        proto = p["summary"]["protocol"]
        proto_counts[proto] = proto_counts.get(proto, 0) + 1
        total_bytes += p.get("length", 0)
        src, dst = p["summary"].get("src"), p["summary"].get("dst")
        if src and dst:
            key = tuple(sorted([src, dst]))
            conversations[key] = conversations.get(key, 0) + 1

    top_conversations = sorted(conversations.items(), key=lambda kv: -kv[1])[:10]
    return {
        "protocol_counts": proto_counts,
        "total_packets": len(packets),
        "total_bytes": total_bytes,
        "top_conversations": [
            {"a": a, "b": b, "packets": c} for (a, b), c in top_conversations
        ],
    }
