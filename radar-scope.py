#!/usr/bin/env python3
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
"""
Exodus Radar Scope - the Quantum's raw packets, field by field, beside the
picture they make.

Nothing else is involved: no Raymarine software, no Axiom, no mayara. This
joins the radar's multicast group with an IGMPv3 source-specific join, takes
one spoke apart exactly the way an MFD has to, and paints the result.

Wire format, read off Exodus's own packets on 9 Oct 2026:
    offset  0  u16   message type 0x0003
    offset  2  u16   header length 0x0028 (40 - but the data starts at 20)
    offset  4  u16   sequence number, +1 every spoke
    offset  8  u16   range cells per spoke        (173 here)
    offset 10  u16   spokes per revolution        (250 here)
    offset 12  u16   unknown, constant 8
    offset 14  u16   unknown, constant 115
    offset 16  u16   bearing, 0..249, +1 a spoke, wraps each turn
    offset 18  u16   payload length (matched on 4500 of 4500 packets)
  payload:  0x5c + u16 little-endian = that many empty cells
            anything else            = one cell's echo strength 0x00..0xfd
            a spoke may stop early; the rest of the cells are empty

Offsets 12 and 14 are labelled unknown on purpose - they never changed in the
capture, so there is no evidence for what they mean.

Caveat shown in the status line: 0x5c is also a legal echo strength, so escape
and data are not perfectly separable. Where treating it as an escape would
overrun the spoke, it is read as a literal instead.

NOT shown: range in feet or miles. The radar does not put its range setting in
these packets. The rings are range cells. Do not navigate off this window.
"""
import os
import socket
import struct
import threading
import time
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

GROUP, PORT = "232.1.216.1", 2574
# Optional: your radar's IP address, via the RADAR_SOURCE environment variable. Empty = any source.
SOURCE = os.environ.get("RADAR_SOURCE", "")
IP_ADD_SOURCE_MEMBERSHIP = 39
ESC = 0x5C
SC = 560                      # scope pixels - the bytes get the rest of the page
FPS = 10                      # scope repaint
TEXT_HZ = 3                   # new spoke shown this often - readable, not a blur
FS = 20                       # the raw bytes, big enough to read across a cabin
MAXTOK = 20                   # payload lines that fit at that size

BG, PANEL = "#0a0d13", "#0f141c"
WHITE, GREY, DIM = "#ecf3fa", "#8a9aab", "#60707e"
GOLD, CYAN, GREEN, AMBER = "#e8a33d", "#4fc3f7", "#5dd98c", "#f5a623"

state = {"az": 0, "spokes": 0, "pps": 0.0, "err": "", "joined": "",
         "last": 0.0, "misread": 0, "sample": None, "frozen": False}
V = np.zeros((250, 173), np.float32)
lock = threading.Lock()


def nic_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((SOURCE or "198.18.0.1", PORT))
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


def decode(payload, ncell):
    """Returns (cells, tokens, overran). Tokens drive the readout."""
    out, toks, i, over = [], [], 0, False
    while i < len(payload) and len(out) < ncell:
        b = payload[i]
        if b == ESC and i + 2 < len(payload):
            run = struct.unpack_from("<H", payload, i + 1)[0]
            if len(out) + run <= ncell:
                out.extend([0] * run)
                toks.append((payload[i:i + 3].hex(" "), "skip %d empty" % run, DIM))
                i += 3
                continue
            over = True
        out.append(b)
        if b >= 230:
            toks.append(("%02x" % b, "echo %d   HARD RETURN" % b, AMBER))
        elif b >= 120:
            toks.append(("%02x" % b, "echo %d" % b, GREEN))
        elif b >= 24:
            toks.append(("%02x" % b, "echo %d   faint" % b, GREY))
        else:
            toks.append(("%02x" % b, "echo %d   nothing there" % b, DIM))
        i += 1
    if len(out) < ncell:
        toks.append(("", "stops here - remaining %d cells empty"
                     % (ncell - len(out)), DIM))
        out.extend([0] * (ncell - len(out)))
    return out, toks, over


def reader():
    global V
    nic = nic_address()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    try:
        s.bind((GROUP, PORT))
    except OSError:
        s.bind(("", PORT))
    joined = False
    if SOURCE:
        try:
            s.setsockopt(socket.IPPROTO_IP, IP_ADD_SOURCE_MEMBERSHIP,
                         struct.pack("4s4s4s", socket.inet_aton(GROUP),
                                     socket.inet_aton(nic), socket.inet_aton(SOURCE)))
            state["joined"] = "source-specific join: %s from %s via %s" % (GROUP, SOURCE, nic)
            joined = True
        except OSError:
            pass
    if not joined:
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4s4s", socket.inet_aton(GROUP), socket.inet_aton(nic)))
            state["joined"] = "joined %s via %s (any source)" % (GROUP, nic)
        except OSError as e:
            state["err"] = "cannot join the radar group: %s" % e
            return
    s.settimeout(2.0)
    n0, t0, nexttext = 0, time.time(), 0.0
    while True:
        try:
            d = s.recv(65535)
        except socket.timeout:
            state["pps"] = 0.0
            continue
        if len(d) < 20 or d[:4] != b"\x03\x00\x28\x00":
            continue
        ncell = struct.unpack_from("<H", d, 8)[0]
        naz = struct.unpack_from("<H", d, 10)[0]
        az = struct.unpack_from("<H", d, 16)[0]
        if not (0 < ncell <= 2048 and 0 < naz <= 4096 and az < naz):
            continue
        cells, toks, over = decode(d[20:], ncell)
        with lock:
            if V.shape != (naz, ncell):
                V = np.zeros((naz, ncell), np.float32)
            V[az] = cells
        state["az"] = az
        state["spokes"] += 1
        state["misread"] += over
        state["last"] = time.time()
        now = time.time()
        if now >= nexttext and not state["frozen"]:
            state["sample"] = (d, toks)
            nexttext = now + 1.0 / TEXT_HZ
        n0 += 1
        if now - t0 >= 1.0:
            state["pps"] = n0 / (now - t0)
            n0, t0 = 0, now


# ------------------------------------------------------------------ window --
root = tk.Tk()
root.title("Exodus Radar Scope")
root.configure(bg=BG)
try:
    root.attributes("-zoomed", True)        # fill the screen on X11
except tk.TclError:
    root.geometry("1900x1020+10+30")

tk.Label(root, text="What the radar puts on the wire, and the picture it makes",
         bg=BG, fg=WHITE, font=("DejaVu Sans", 22, "bold")).pack(pady=(8, 0))

# The bottom strips are packed FIRST, against the bottom edge, so the big
# text pane cannot push them off the screen when it expands.
bar = tk.Frame(root, bg=BG)
foot = tk.Label(root, bg=BG, fg=DIM, anchor="w", font=("DejaVu Sans", 10),
                text="Rings are range cells, not distance - the radar does not "
                     "send its range setting. Not for navigation.")
foot.pack(side="bottom", fill="x", padx=16, pady=(0, 6))
bar.pack(side="bottom", fill="x", padx=16, pady=(0, 2))

body = tk.Frame(root, bg=BG)
body.pack(padx=14, pady=8, fill="both", expand=True)

left = tk.Frame(body, bg=PANEL, highlightbackground="#7a5a2a",
                highlightthickness=2)
left.pack(side="left", fill="both", expand=True, padx=(0, 10))
tk.Label(left, text="ONE SPOKE, THE WAY AN MFD READS IT", bg=PANEL, fg=GOLD,
         font=("DejaVu Sans", 21, "bold"), anchor="w").pack(fill="x", padx=18,
                                                            pady=(10, 0))
tk.Label(left, text=("%s  ->  232.1.216.1:2574" % (SOURCE or "any source")), bg=PANEL, fg=GREY,
         font=("DejaVu Sans Mono", 13), anchor="w").pack(fill="x", padx=18)
txt = tk.Text(left, bg=PANEL, fg=GREY, bd=0, highlightthickness=0,
              font=("DejaVu Sans Mono", FS), width=52, height=30,
              wrap="none", spacing1=2)
txt.pack(fill="both", expand=True, padx=18, pady=(8, 12))
for name, col in (("gold", GOLD), ("cyan", CYAN), ("green", GREEN),
                  ("amber", AMBER), ("grey", GREY), ("dim", DIM),
                  ("white", WHITE)):
    txt.tag_configure(name, foreground=col)
txt.tag_configure("hdr", foreground=WHITE,
                  font=("DejaVu Sans Mono", FS, "bold"))
txt.tag_configure("big", foreground=CYAN,
                  font=("DejaVu Sans Mono", FS + 4, "bold"))

right = tk.Frame(body, bg=PANEL, highlightbackground="#2e6b47",
                 highlightthickness=2)
right.pack(side="left", fill="both")
tk.Label(right, text="THE PICTURE THEY MAKE", bg=PANEL, fg=GREEN,
         font=("DejaVu Sans", 21, "bold"), anchor="w").pack(fill="x", padx=14,
                                                            pady=(10, 0))
tk.Label(right, text="painted only from those bytes", bg=PANEL, fg=GREY,
         font=("DejaVu Sans", 13), anchor="w").pack(fill="x", padx=14)
scope = tk.Label(right, bg=PANEL, bd=0)
scope.pack(padx=14, pady=10)

status = tk.Label(bar, bg=BG, fg=GREEN, justify="left", anchor="w",
                  font=("DejaVu Sans Mono", 12))
status.pack(side="left")


def toggle_freeze():
    state["frozen"] = not state["frozen"]
    btn.configure(text="Resume" if state["frozen"] else "Freeze a spoke")


btn = tk.Button(bar, text="Freeze a spoke", command=toggle_freeze,
                bg="#17384f", fg=WHITE, activebackground="#1e4a68",
                bd=0, padx=16, pady=5, font=("DejaVu Sans", 12))
btn.pack(side="right")

_maps = {}


def maps(naz, ncell):
    key = (naz, ncell)
    if key not in _maps:
        c, rad = SC // 2, SC // 2 - 6
        yy, xx = np.mgrid[0:SC, 0:SC].astype(np.float32)
        dx, dy = xx - c, yy - c
        rr = np.sqrt(dx * dx + dy * dy)
        ang = (np.arctan2(dy, dx) + np.pi / 2) % (2 * np.pi)
        ins = rr <= rad
        ring = np.zeros((SC, SC), bool)
        for f in (0.25, 0.5, 0.75, 1.0):
            ring |= np.abs(rr - rad * f) < 1.0
        _maps.clear()
        _maps[key] = (np.clip((ang / (2 * np.pi) * naz).astype(np.int32), 0, naz - 1),
                      np.clip((rr / rad * ncell).astype(np.int32), 0, ncell - 1),
                      ins, ring & ins)
    return _maps[key]


# Offsets 8 and 14 were both constant across the 45 s capture, so they looked
# fixed. Watching the live window while the radar's range was changed showed
# them move together - 173/115 at one range, 43/29 at another - so 8 is the
# cell count for the current range and 14 tracks it. Offset 12 has stayed at 8
# throughout and is still unexplained.
U16 = [(0, "message type"), (2, "header length"), (4, "sequence number"),
       (8, "range cells, this range"), (10, "spokes per revolution"),
       (12, "unknown, always 8"), (14, "tracks the range too"),
       (16, "BEARING"), (18, "payload length, bytes")]


def write_sample():
    s = state["sample"]
    txt.configure(state="normal")
    txt.delete("1.0", "end")
    if not s:
        txt.insert("end", "\n  waiting for the radar ...\n", "grey")
        txt.configure(state="disabled")
        return
    d, toks = s
    txt.insert("end", "HEADER  20 bytes\n", "hdr")
    for off, name in U16:
        v = struct.unpack_from("<H", d, off)[0]
        raw = d[off:off + 2].hex(" ")
        if name == "BEARING":
            txt.insert("end", " %-7s " % raw, "big")
            txt.insert("end", "%-26s" % name, "cyan")
            txt.insert("end", "%d\n" % v, "big")
        else:
            txt.insert("end", " %-7s " % raw, "green")
            txt.insert("end", "%-26s" % name, "grey")
            txt.insert("end", "%d\n" % v, "white")
    txt.insert("end", "\nPAYLOAD %d bytes, run-length compressed\n" % len(d[20:]),
               "hdr")
    for raw, meaning, col in toks[:MAXTOK]:
        tag = {GOLD: "gold", CYAN: "cyan", GREEN: "green", AMBER: "amber",
               GREY: "grey", DIM: "dim"}.get(col, "grey")
        txt.insert("end", " %-9s " % raw, tag)
        txt.insert("end", "%s\n" % meaning, tag)
    if len(toks) > MAXTOK:
        txt.insert("end", " ... %d more in this spoke\n" % (len(toks) - MAXTOK),
                   "dim")
    txt.configure(state="disabled")


_lasttext = [0.0]


def tick():
    global V
    with lock:
        naz, ncell = V.shape
        snap = V.copy()
        V *= 0.985
    azm, cm, ins, ring = maps(naz, ncell)
    vals = snap[azm, cm]
    g = np.clip(40 + vals * 0.85, 0, 255)
    img = np.zeros((SC, SC, 3), np.float32)
    lit = (vals > 24) & ins
    img[..., 0] = np.where(lit, g * 0.25, 0)
    img[..., 1] = np.where(lit, g, 0)
    img[..., 2] = np.where(lit, g * 0.45, 0)
    img[~ins] = np.array([15, 20, 28], np.float32)
    img[(~lit) & ins] = np.array([4, 17, 12], np.float32)
    img[ring & ~lit] = np.array([20, 60, 44], np.float32)
    beam = ins & (((azm - state["az"]) % naz) < 3)
    img[beam] = np.minimum(255.0, img[beam] + np.array([30, 120, 70], np.float32))
    ph = ImageTk.PhotoImage(Image.fromarray(img.astype(np.uint8), "RGB"))
    scope.configure(image=ph)
    scope.image = ph

    now = time.time()
    if now - _lasttext[0] >= 1.0 / TEXT_HZ:
        write_sample()
        _lasttext[0] = now

    live = (now - state["last"]) < 3 if state["last"] else False
    if state["err"]:
        status.configure(text=state["err"], fg=AMBER)
    else:
        t = ("%s   bearing %3d/%d   %3.0f spokes/s   %d total"
             % ("LIVE" if live else "no data - is the radar transmitting?",
                state["az"], naz, state["pps"], state["spokes"]))
        if state["spokes"]:
            t += "   (%.0f%% needed the 0x5c fallback)" % (
                100.0 * state["misread"] / state["spokes"])
        t += "\n" + state["joined"]
        status.configure(text=t, fg=GREEN if live else AMBER)
    root.after(int(1000 / FPS), tick)


threading.Thread(target=reader, daemon=True).start()
tick()
root.mainloop()
