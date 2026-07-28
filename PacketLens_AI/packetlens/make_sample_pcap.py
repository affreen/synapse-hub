"""
make_sample_pcap.py — builds sample.pcap by hand-crafting raw Ethernet
frames (stdlib only, no scapy). Produces a small, realistic mix: ARP,
a TCP three-way handshake + HTTP-ish request/response, a UDP/DNS query,
and an ICMP echo — enough to exercise every dissector path in
backend/pcap_parser.py.
"""

import struct
import socket
import time

OUT_PATH = "sample.pcap"


def mac_bytes(s):
    return bytes(int(b, 16) for b in s.split(":"))


def ip_bytes(s):
    return socket.inet_aton(s)


def eth_header(dst, src, ethertype):
    return mac_bytes(dst) + mac_bytes(src) + struct.pack(">H", ethertype)


def ipv4_header(src, dst, proto, payload_len, ident=1, ttl=64):
    ver_ihl = (4 << 4) | 5
    total_len = 20 + payload_len
    flags_frag = 0
    header = struct.pack(
        ">BBHHHBBH4s4s",
        ver_ihl, 0, total_len, ident, flags_frag, ttl, proto, 0,
        ip_bytes(src), ip_bytes(dst),
    )
    checksum = ip_checksum(header)
    return header[0:10] + struct.pack(">H", checksum) + header[12:]


def ip_checksum(header):
    if len(header) % 2:
        header += b"\x00"
    total = 0
    for i in range(0, len(header), 2):
        total += (header[i] << 8) + header[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def tcp_header(sport, dport, seq, ack, flags, window=64240, payload=b""):
    data_offset = (5 << 4)
    header = struct.pack(">HHIIBBHHH", sport, dport, seq, ack, data_offset,
                          flags, window, 0, 0)
    return header  # checksum left as 0; not validated by our dissector


def udp_header(sport, dport, payload):
    length = 8 + len(payload)
    return struct.pack(">HHHH", sport, dport, length, 0)


def icmp_echo(icmp_type, code, ident, seq, payload=b"abcdefgh"):
    header = struct.pack(">BBHHH", icmp_type, code, 0, ident, seq) + payload
    checksum = ip_checksum(header)
    return header[0:2] + struct.pack(">H", checksum) + header[4:]


def arp_packet(opcode, sender_mac, sender_ip, target_mac, target_ip):
    return struct.pack(">HHBBH", 1, 0x0800, 6, 4, opcode) + \
        mac_bytes(sender_mac) + ip_bytes(sender_ip) + \
        mac_bytes(target_mac) + ip_bytes(target_ip)


MAC_HOST = "02:11:22:33:44:55"
MAC_ROUTER = "02:aa:bb:cc:dd:ee"
IP_HOST = "192.168.1.50"
IP_ROUTER = "192.168.1.1"
IP_SERVER = "93.184.216.34"  # example.com-ish
IP_DNS = "8.8.8.8"


def build_frames():
    frames = []

    # 1. ARP: who has the router?
    arp = arp_packet(1, MAC_HOST, IP_HOST, "00:00:00:00:00:00", IP_ROUTER)
    frames.append(eth_header("ff:ff:ff:ff:ff:ff", MAC_HOST, 0x0806) + arp)

    # 2. ARP reply
    arp_reply = arp_packet(2, MAC_ROUTER, IP_ROUTER, MAC_HOST, IP_HOST)
    frames.append(eth_header(MAC_HOST, MAC_ROUTER, 0x0806) + arp_reply)

    # 3. DNS query over UDP (fake minimal payload, not a real DNS packet
    #    parse — our dissector reports it at the UDP layer with the
    #    well-known port 53 -> "DNS" label)
    dns_payload = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" \
                  b"\x07example\x03com\x00\x00\x01\x00\x01"
    udp_h = udp_header(51820, 53, dns_payload)
    ip_h = ipv4_header(IP_HOST, IP_DNS, 17, len(udp_h) + len(dns_payload), ident=10)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_h + udp_h + dns_payload)

    # 4. DNS response
    dns_resp = b"\x12\x34\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00" \
               b"\x07example\x03com\x00\x00\x01\x00\x01\xc0\x0c\x00\x01" \
               b"\x00\x01\x00\x00\x00\x3c\x00\x04\x5d\xb8\xd8\x22"
    udp_h2 = udp_header(53, 51820, dns_resp)
    ip_h2 = ipv4_header(IP_DNS, IP_HOST, 17, len(udp_h2) + len(dns_resp), ident=11)
    frames.append(eth_header(MAC_HOST, MAC_ROUTER, 0x0800) + ip_h2 + udp_h2 + dns_resp)

    # 5-7. TCP three-way handshake to port 80
    seq_c, seq_s = 1000, 5000
    tcp_syn = tcp_header(52001, 80, seq_c, 0, 0x02)  # SYN
    ip_syn = ipv4_header(IP_HOST, IP_SERVER, 6, len(tcp_syn), ident=20)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_syn + tcp_syn)

    tcp_synack = tcp_header(80, 52001, seq_s, seq_c + 1, 0x12)  # SYN+ACK
    ip_synack = ipv4_header(IP_SERVER, IP_HOST, 6, len(tcp_synack), ident=21)
    frames.append(eth_header(MAC_HOST, MAC_ROUTER, 0x0800) + ip_synack + tcp_synack)

    tcp_ack = tcp_header(52001, 80, seq_c + 1, seq_s + 1, 0x10)  # ACK
    ip_ack = ipv4_header(IP_HOST, IP_SERVER, 6, len(tcp_ack), ident=22)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_ack + tcp_ack)

    # 8. HTTP GET request (PSH+ACK with payload)
    http_req = b"GET / HTTP/1.1\r\nHost: example.com\r\nUser-Agent: PacketLens\r\n\r\n"
    tcp_push = tcp_header(52001, 80, seq_c + 1, seq_s + 1, 0x18, payload=http_req)
    ip_push = ipv4_header(IP_HOST, IP_SERVER, 6, len(tcp_push) + len(http_req), ident=23)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_push + tcp_push + http_req)

    # 9. HTTP response
    http_resp = b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, world!"
    tcp_resp = tcp_header(80, 52001, seq_s + 1, seq_c + 1 + len(http_req), 0x18, payload=http_resp)
    ip_resp = ipv4_header(IP_SERVER, IP_HOST, 6, len(tcp_resp) + len(http_resp), ident=24)
    frames.append(eth_header(MAC_HOST, MAC_ROUTER, 0x0800) + ip_resp + tcp_resp + http_resp)

    # 10. FIN to close
    tcp_fin = tcp_header(52001, 80, seq_c + 1 + len(http_req), seq_s + 1 + len(http_resp), 0x11)
    ip_fin = ipv4_header(IP_HOST, IP_SERVER, 6, len(tcp_fin), ident=25)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_fin + tcp_fin)

    # 11. ICMP echo request/reply (ping)
    icmp_req = icmp_echo(8, 0, 1, 1)
    ip_icmp_req = ipv4_header(IP_HOST, IP_ROUTER, 1, len(icmp_req), ident=30, ttl=128)
    frames.append(eth_header(MAC_ROUTER, MAC_HOST, 0x0800) + ip_icmp_req + icmp_req)

    icmp_reply = icmp_echo(0, 0, 1, 1)
    ip_icmp_reply = ipv4_header(IP_ROUTER, IP_HOST, 1, len(icmp_reply), ident=31, ttl=255)
    frames.append(eth_header(MAC_HOST, MAC_ROUTER, 0x0800) + ip_icmp_reply + icmp_reply)

    return frames


def write_pcap(frames, path):
    global_header = struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    now = time.time()
    with open(path, "wb") as f:
        f.write(global_header)
        for i, frame in enumerate(frames):
            ts = now + i * 0.25
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1e6)
            rec_header = struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame))
            f.write(rec_header)
            f.write(frame)


if __name__ == "__main__":
    frames = build_frames()
    write_pcap(frames, OUT_PATH)
    print("wrote %d packets to %s" % (len(frames), OUT_PATH))
