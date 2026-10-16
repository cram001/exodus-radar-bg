#!/usr/bin/env python3
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
"""
radar-capture.py - record what the radar actually puts on the wire, and work out
                   the shape of it without guessing.

FOR THE VIDEO. NMEA 0183 is text you can read. NMEA 2000 is 8-byte CAN frames.
Radar is neither: it streams SPOKES - one bearing angle plus an array of range
bins, each bin an echo strength. This captures them raw so they can be shown as
bytes and then painted as a picture.

Exodus has a Raymarine Quantum (Quantum_W3 bridge). changes.txt records it
streaming to 232.1.216.1:2574.

    sudo python3 radar-capture.py                       # defaults to the above
    sudo python3 radar-capture.py --seconds 20
    sudo python3 radar-capture.py --group 232.1.216.1 --port 2574
    sudo python3 radar-capture.py --analyse radar-cap-*.bin   # re-read a capture

THE RADAR MUST BE TRANSMITTING. Powered up and out of standby. If the Axiom is
on it owns the radar - that is fine, the spokes are multicast and we only listen.
We never command it. See ~/Desktop/RADAR-HANDOVER.txt.

WHAT IT WRITES
    radar-cap-<stamp>.bin    every packet, length-prefixed, for later analysis
    and prints: packet rate, size histogram, a hex view, and a first guess at
    where the spoke header ends and the echo data begins - derived from the
    bytes themselves, not from an assumed spec.

Built 9 Oct 2026.
"""

import argparse
import collections
import os
import socket
import struct
import sys
import time

DEF_GROUP = "232.1.216.1"
DEF_PORT = 2574


def join(group, port, iface_ip="0.0.0.0", timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    s.bind(("", port))
    mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(iface_ip))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    s.settimeout(timeout)
    return s


def capture(group, port, seconds, iface_ip):
    s = join(group, port, iface_ip)
    out = "radar-cap-%s.bin" % time.strftime("%Y%m%d-%H%M%S")
    pkts, total = [], 0
    t0 = time.time()
    print("listening on %s:%d for %d s ..." % (group, port, seconds))
    with open(out, "wb") as f:
        while time.time() - t0 < seconds:
            try:
                data, addr = s.recvfrom(65535)
            except socket.timeout:
                if not pkts:
                    print("\nNOTHING ARRIVED.")
                    print("  The radar is almost certainly in standby or powered off.")
                    print("  Check it is transmitting, then run this again.")
                    return None
                continue
            f.write(struct.pack("<I", len(data)))
            f.write(data)
            pkts.append(data)
            total += len(data)
            if len(pkts) == 1:
                print("  first packet from %s:%d, %d bytes" % (addr[0], addr[1], len(data)))
    el = time.time() - t0
    print("\n%d packets, %.1f KB, %.0f pkt/s -> %s"
          % (len(pkts), total / 1024.0, len(pkts) / el if el else 0, out))
    return pkts


def load(path):
    pkts = []
    with open(path, "rb") as f:
        while True:
            h = f.read(4)
            if len(h) < 4:
                break
            (n,) = struct.unpack("<I", h)
            d = f.read(n)
            if len(d) < n:
                break
            pkts.append(d)
    print("loaded %d packets from %s" % (len(pkts), path))
    return pkts


def analyse(pkts):
    if not pkts:
        return
    print("\n=== PACKET SIZES ===")
    sizes = collections.Counter(len(p) for p in pkts)
    for sz, n in sizes.most_common(8):
        print("  %5d bytes  x %d" % (sz, n))

    big = max(sizes, key=lambda k: sizes[k])
    same = [p for p in pkts if len(p) == big]
    print("\nusing the %d packets of %d bytes" % (len(same), big))

    # Which byte positions never change? Those are header/constant.
    # Which change every packet? Those are counters, angles, or echo data.
    n = min(len(same), 200)
    const, varying = [], []
    for i in range(big):
        vals = {same[k][i] for k in range(n)}
        (const if len(vals) == 1 else varying).append(i)

    print("\n=== STRUCTURE, derived from the bytes ===")
    print("  %d byte positions never change  (header / constants)" % len(const))
    print("  %d byte positions vary          (angle, counters, echo data)" % len(varying))
    if const:
        runs, start = [], const[0]
        for a, b in zip(const, const[1:] + [None]):
            if b != (a + 1):
                runs.append((start, a))
                start = b
        fixed = ", ".join("%d-%d" % r if r[0] != r[1] else "%d" % r[0] for r in runs[:10])
        print("  fixed at offsets: %s" % fixed)

    # A spoke header is usually a short varying prefix followed by a long run of
    # echo bytes. Find where the "settles into data" boundary is.
    if varying:
        first_long_run = None
        run_start, run_len = varying[0], 1
        for a, b in zip(varying, varying[1:]):
            if b == a + 1:
                run_len += 1
            else:
                if run_len >= 64 and first_long_run is None:
                    first_long_run = (run_start, a)
                run_start, run_len = b, 1
        if run_len >= 64 and first_long_run is None:
            first_long_run = (run_start, varying[-1])
        if first_long_run:
            s, e = first_long_run
            print("  longest varying run: offsets %d..%d  (%d bytes)" % (s, e, e - s + 1))
            print("  -> header is probably the first %d bytes, echo data the rest" % s)

    print("\n=== FIRST PACKET, first 96 bytes ===")
    p = same[0]
    for off in range(0, min(96, len(p)), 16):
        chunk = p[off:off + 16]
        hexs = " ".join("%02x" % c for c in chunk)
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        print("  %04x  %-47s  %s" % (off, hexs, txt))

    print("\n=== ECHO BYTES look like intensities? ===")
    tail = p[-256:]
    hist = collections.Counter(tail)
    print("  last 256 bytes: %d distinct values, min %d, max %d, mean %.0f"
          % (len(hist), min(tail), max(tail), sum(tail) / len(tail)))
    print("  most common: %s" % ", ".join("%d(x%d)" % (v, c) for v, c in hist.most_common(6)))
    print("\n  If those are mostly low with occasional high values, that IS the")
    print("  picture: low = open water, high = a hard target returning energy.")


def main():
    ap = argparse.ArgumentParser(description="Capture and dissect radar spoke traffic.")
    ap.add_argument("--group", default=DEF_GROUP)
    ap.add_argument("--port", type=int, default=DEF_PORT)
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--iface-ip", default="0.0.0.0",
                    help="local IP of the radar-facing interface, if multi-homed")
    ap.add_argument("--analyse", help="re-read a previous .bin instead of capturing")
    args = ap.parse_args()

    pkts = load(args.analyse) if args.analyse else \
        capture(args.group, args.port, args.seconds, args.iface_ip)
    if pkts:
        analyse(pkts)


if __name__ == "__main__":
    main()
