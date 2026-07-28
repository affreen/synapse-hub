"""
Unit tests for backend/pcap_parser.py.

Run in PyCharm: right-click this file (or the tests/ folder) -> Run 'Unittests
in test_pcap_parser'. Or from a terminal:

    cd packetlens
    python3 -m unittest discover -s tests -v

No third-party test framework required — this uses the standard library's
`unittest`.
"""

import os
import sys
import struct
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

import pcap_parser  # noqa: E402

SAMPLE_PCAP = os.path.join(PROJECT_ROOT, "sample.pcap")


def build_minimal_pcap(frames):
    """Hand-roll a tiny classic-pcap byte string from a list of raw
    Ethernet frames, for tests that don't want to depend on sample.pcap."""
    global_header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    out = [global_header]
    for i, frame in enumerate(frames):
        rec_header = struct.pack("<IIII", 1_700_000_000 + i, 0, len(frame), len(frame))
        out.append(rec_header)
        out.append(frame)
    return b"".join(out)


def eth_udp_frame():
    """A minimal Ethernet + IPv4 + UDP frame: 10.0.0.1:5000 -> 10.0.0.2:53"""
    import socket as _socket

    eth = bytes.fromhex("aabbccddeeff") + bytes.fromhex("112233445566") + struct.pack(">H", 0x0800)
    udp_payload = b"hello"
    udp = struct.pack(">HHHH", 5000, 53, 8 + len(udp_payload), 0) + udp_payload
    ip_total_len = 20 + len(udp)
    ip = struct.pack(
        ">BBHHHBBH4s4s",
        0x45, 0, ip_total_len, 1, 0, 64, 17, 0,
        _socket.inet_aton("10.0.0.1"), _socket.inet_aton("10.0.0.2"),
    )
    return eth + ip + udp


class TestPcapParser(unittest.TestCase):

    def test_bad_magic_raises(self):
        with self.assertRaises(pcap_parser.PcapParseError):
            pcap_parser.parse_pcap_bytes(b"not a pcap file, too short")

    def test_too_small_raises(self):
        with self.assertRaises(pcap_parser.PcapParseError):
            pcap_parser.parse_pcap_bytes(b"\x00" * 10)

    def test_minimal_udp_packet(self):
        data = build_minimal_pcap([eth_udp_frame()])
        packets, meta = pcap_parser.parse_pcap_bytes(data)
        self.assertEqual(meta["packet_count"], 1)
        self.assertEqual(len(packets), 1)

        pkt = packets[0]
        self.assertEqual(pkt["summary"]["protocol"], "DNS")  # port 53 well-known
        self.assertEqual(pkt["layers"]["ipv4"]["src_ip"], "10.0.0.1")
        self.assertEqual(pkt["layers"]["ipv4"]["dst_ip"], "10.0.0.2")
        self.assertEqual(pkt["layers"]["udp"]["src_port"], 5000)
        self.assertEqual(pkt["layers"]["udp"]["dst_port"], 53)

    def test_sample_capture_present(self):
        self.assertTrue(os.path.exists(SAMPLE_PCAP), "run make_sample_pcap.py first")

    def test_sample_capture_parses(self):
        with open(SAMPLE_PCAP, "rb") as f:
            data = f.read()
        packets, meta = pcap_parser.parse_pcap_bytes(data)
        self.assertEqual(meta["packet_count"], 12)

        protocols = [p["summary"]["protocol"] for p in packets]
        self.assertEqual(protocols[0], "ARP")
        self.assertEqual(protocols[1], "ARP")
        self.assertIn("DNS", protocols)
        self.assertIn("HTTP", protocols)
        self.assertIn("ICMP", protocols)

    def test_sample_tcp_handshake_flags(self):
        with open(SAMPLE_PCAP, "rb") as f:
            data = f.read()
        packets, _meta = pcap_parser.parse_pcap_bytes(data)

        # Packets 5, 6, 7 (1-indexed) are the SYN, SYN-ACK, ACK of the
        # three-way handshake in make_sample_pcap.py.
        syn = packets[4]["layers"]["tcp"]
        synack = packets[5]["layers"]["tcp"]
        ack = packets[6]["layers"]["tcp"]

        self.assertEqual(syn["flags_set"], ["SYN"])
        self.assertEqual(set(synack["flags_set"]), {"SYN", "ACK"})
        self.assertEqual(ack["flags_set"], ["ACK"])

    def test_summarize_capture_stats(self):
        with open(SAMPLE_PCAP, "rb") as f:
            data = f.read()
        packets, _meta = pcap_parser.parse_pcap_bytes(data)
        stats = pcap_parser.summarize_capture(packets)

        self.assertEqual(stats["total_packets"], 12)
        self.assertEqual(sum(stats["protocol_counts"].values()), 12)
        self.assertGreater(stats["total_bytes"], 0)
        self.assertTrue(len(stats["top_conversations"]) > 0)

    def test_arp_dissection(self):
        with open(SAMPLE_PCAP, "rb") as f:
            data = f.read()
        packets, _meta = pcap_parser.parse_pcap_bytes(data)
        arp_request = packets[0]["layers"]["arp"]
        self.assertEqual(arp_request["opcode"], "Request")
        self.assertEqual(arp_request["sender_ip"], "192.168.1.50")
        self.assertEqual(arp_request["target_ip"], "192.168.1.1")

    def test_icmp_dissection(self):
        with open(SAMPLE_PCAP, "rb") as f:
            data = f.read()
        packets, _meta = pcap_parser.parse_pcap_bytes(data)
        icmp_packets = [p for p in packets if p["summary"]["protocol"] == "ICMP"]
        self.assertEqual(len(icmp_packets), 2)
        self.assertEqual(icmp_packets[0]["layers"]["icmp"]["type"], 8)  # echo request
        self.assertEqual(icmp_packets[1]["layers"]["icmp"]["type"], 0)  # echo reply


if __name__ == "__main__":
    unittest.main()
