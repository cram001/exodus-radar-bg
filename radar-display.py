#!/usr/bin/env python3
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
"""
Exodus Radar - a working radar display for the Raymarine Quantum.

Reads the radar straight off the network (IGMPv3 source-specific join on
232.1.216.1:2574 from the radar), decodes the run-length compressed spokes
and draws a proper PPI: bearing scale, labelled range rings, heading line,
own ship at the centre, click anywhere for range and bearing.

Heading, course, speed and position come from Signal K on localhost:3000.

TWO THINGS THE RADAR DOES NOT TELL US, so you set them:

1. RANGE. These packets carry a cell count, not a distance. Set the range
   button to whatever the Axiom is showing and the rings and readouts are
   right. Get it wrong and every distance on screen is wrong by that factor.

2. ORIENTATION. Whether the radar's bearing 0 is the bow or true north is not
   stated in the data either. It opens HEAD UP, which is the usual case for a
   radar's own spokes. If the picture does not match what you can see out of
   the window, press NORTH UP. Check it against something you can identify -
   at the dock that takes ten seconds.

ADDED 11 Oct 2026 (the owner): AIS targets on the scope and a DANGEROUS AIS list,
wind and depth readouts, an ANCHOR WATCH box, and the boat's logo faded in
behind the readouts. The anchor watch itself runs as its own service
(anchor-watch.py) so it keeps watching if this window is closed; the box here
only sets it and shows it.

This is a second opinion, not the ship's radar. The Axiom is the instrument
you navigate on.
"""
import json
import math
import os
import socket
import struct
import threading
import time
import tkinter as tk
import urllib.request

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk

GROUP, PORT = "232.1.216.1", 2574
IP_ADD_SOURCE_MEMBERSHIP = 39
ESC = 0x5C
SK = "http://127.0.0.1:3000/signalk/v1/api/vessels/self/"
CFG = "/home/pi/.radar-display.json"


def _cfg_value(key, default=""):
    try:
        return json.load(open(CFG)).get(key, default)
    except Exception:
        return default


# Optional: your radar's IP address. Empty (the default) accepts the radar group from any source, which
# works whatever address your radar was given. Set "radar_source" in the config file to filter.
SOURCE = str(_cfg_value("radar_source", ""))
SC = 980                      # scope diameter - rudder bar and status live in the right column so the scope gets the full height
FPS = 8
FS_BTN, FS_BIG, FS_HUGE = 16, 22, 30   # nothing on this screen should need squinting

BG, PANEL = "#000000", "#111111"
WHITE, GREY, DIM = "#ecf3fa", "#8a9aab", "#5a6a78"
GOLD, CYAN, GREEN, AMBER = "#4dc8ff", "#00ffff", "#4dff4d", "#ffcc44"

RANGES = [0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]
NM_FT = 6076.12

AW_CFG = "/home/pi/.anchor-watch.json"
AW_STATUS = "/home/pi/.anchor-watch-status.json"
AIS_CONF = "/home/pi/boat-bot/ais-alarm.json"
_LOGO_B64 = (
    "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"
    "jGZkfrd+HgU1aFHVb42Nj890SDyjUUsLPcWqD+bZeOh04OwYAAeIIpxENB7sgMwmW6dOOv427tTI0WEf4d2+7w9Tbeecqi+s"
    "5Bm3p9saHQDHqvNvbqy4vNvTMt81LBvg5sPql4074NAAPN2C3eMKfZWZn9U+5X/tnmZMkQrMhueaZJUJojDpHK9yqsqPf6yD"
    "qljynS4qqUxV/yEAmU1fLfe6o+AsWu1iB6hwkohUDL8nyVqt5Poyt7Kj9dcOCab0rMROnJK+R0oUXsm84u1jzV7lHc9p83PP"
    "kMc9xJjdQ9imrJieZA83Db8q8/ycxlKwMbWsh5klpNo/yLcU+S7W4ftBIXkfNHC1A69RQeBIq0DP48Eduwjf/N6Dw2ZFOQw9"
    "s/DG8ltHOaRtbJwzrmBB84hyC+eumGy4cegFwbH3hfXFsNt89GzCqUEUm6UXnAKh5t6FQ3bsVP9XszinieKvjHciZvUv9zw9"
    "zEdPpN21VEMajqmazFGFgmrTu7nc4Wv8l6Xu/xWA8Al7kFvOmZzE/AEZKnlJgMpyBuQyXpSLWp6G+6i/XkXFZxgyF1hbNHhi"
    "DMSrz4LVNYptK33ptvogvKQX09jgUuFBM3q7lo0P1iPZjNe1hhaJi7x3Ydf6Gw5IMdMDhE2W5Rmvd0qDbW5wUsBpGBEUYgq0"
    "IowODaMmRGJVtRs9W6S0K927TG126eq2jEcuV1hwculSxV23rS7f/8dONW5pjPpvr/YsuLh7zICNHItL8Q7PzIb0/A1K0Wt1"
    "JL/7BmtU3/a30w71uMVCXVSd+HwULJKPSJxNe2UmTzqrWvxNQilnmf1DAALFPK9JTsZQrWbSDQ3n6aYFA+kfj9LoAhz0dMM5"
    "6td18yIGFWF77ruMefxJ9BUSX4mqVJfelB9hV/28Zdf0grflQJ2uVXTilrx2X1MMp2SlyvpaqckLDv/Qse4qhmQpN4Vjxsc+"
    "QWk7WpyqyKDzgqoSY2CMcdARujdzptr17XUPG83rO1Xz2nHIzMm+bSZfedJrquGI/8JORU1eqHDz+p0WLffpzXlum9d+XBlo"
    "u5pPTs5ytiQQu6QIUTmW07Wq5Sw2a0fp/pZhKrJreuGzvy6vT5rg6ONCYLKiXXRA4+QtedKtMH/6hwBkDJVxzUUs6iNsWyWo"
    "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"
    "R7NrDZNfTM+B78/zjF1lWjFVMP5Q2sgfAsiY4Xu0gfbCFyxg1PD6Qo07WPp6o/tKretH1xMmN+wtRwz0L8/67eCJCh2ADB1c"
    "fWn2xF0d636vK8Erw1684KU50XLEk0EoSD2ZWmRu0iox3CSYTOmV4UpQSod8y8XDjc/dlPc5j5dUqnHb3vqZd1RKN5YqlfvK"
    "BOF7W+CpEEvXd9oeXmgRHxsen/3NoUJY23U+XTHfNi6jQUmRqIXv2rXQqhATJLcGQGoycGASP71ufxaEE5fHclNE1KhBnlKz"
    "SXSdWL/PSNgTpfY5JBh/nQYyMGPEeo8++ntOFhaX9Fh/S/rJteclz9zhnSpNor3KJXbt2T3WUnn21NlreTUAuKV22LS3d9Yz"
    "3xRdeH7cmjX+PjcNxD41tDFw9cqhk5fUuk07t0wIOHexwtYJhW2/TTxdczXou5LkHDnAe92in/2iK6n6fMGWdE1d3j0o/524"
    "dsJ3bV+rNp7tdGpfDuBo265wf/uJP3zInvD6rspo+v63n0uMyCCCObJ+p/7xyNzxZRq4SfO+OecTk6f5iPb1zXtOpN+47daR"
    "sKUJ/2KCYNBfCRCCvniukyZ/6TU0OS2pT9cuv3x/62qJMXBTm8uyFNgovOREHqvfuHOnhijLvXL+7KUiAKbYTJeFuxi0uFnq"
    "MjU8O4cQ3GdIu4pzl8ucGalVMCe269Wm+vyRlGEdEy5V/ex147fi5HJbuLR8yVc9ZN+c7XsPgNg7I7S8OunuQ/LJi/FHTZYK"
    "gPl1Tyw87n6eL8/ya+3+VWSOccmHBR2AOaFpuyYJvjj28y/nPdF1s7M1vfOeIT/bxHodxjc9f/Dbc/5P78huu6UuOzqo2tD/"
    "SisM6MJ86VVjVcmPJ99ZkGrvaWpa4s6uUDKlxMtMDNcy275gPXvsxD6Ymrfr1HOood1IvZqWekMhJ5jETbfG9Zz048VoMZ8V"
    "rt/UcECHtscu5rghKampq8O6DX/RufPVkEcS+h+pKLao9XXJqwYpI0oWrM2DpDZcPEj7tahpxulAR+lAfpQqZBbUIT5zbXb7"
    "R745DUlOKZKYWvYeRLNfYoemTSNJv739xxNVQr1ZISlnmLVGT6rNgWFv0NILVUcveX+zJjvuq0j267Nl4h/k98fzRAxxpjJb"
    "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"
    "/w/l0PV+g5I1KgAAAABJRU5ErkJggg=="
)

_LOGO_IMG = None


def _logo_img():
    """The Exodus mark, built into this file (not read from disk): a 320 px greyscale watermark."""
    global _LOGO_IMG
    if _LOGO_IMG is None:
        import base64
        import io
        _LOGO_IMG = Image.open(io.BytesIO(base64.b64decode(_LOGO_B64))).convert("L")
    return _LOGO_IMG.copy()
TITLE_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "PirataOne.ttf")
FT = 3.28084
DANGER_CPA_FT = 1000.0      # closest approach inside this, ...
DANGER_TCPA_S = 15 * 60     # ... within this long, counts as dangerous
AIS_MAX_AGE = 900           # a target not heard for 15 minutes is dropped
RED = "#ff5a52"

SWELL_FILE = "/home/pi/.swell.json"     # written by whatever estimates swell on your boat; read here, never faked
cfg = {"range": 0.5, "northup": False, "trails": True, "gain": 24, "ais": True}
try:
    cfg.update(json.load(open(CFG)))
except Exception:
    pass


def savecfg():
    try:
        json.dump(cfg, open(CFG, "w"))
    except Exception:
        pass


state = {"az": 0, "spokes": 0, "pps": 0.0, "last": 0.0, "err": "", "joined": "",
         "naz": 250, "ncell": 173, "cursor": None}
nav = {"hdg": None, "cog": None, "sog": None, "pos": None,
       "wind": None, "wind_t": None, "depth": None, "depth_t": None,
       "wangle": None, "wangle_t": None, "tangle": None, "tangle_t": None,
       "rudder": None, "rudder_t": None,
       "stw": None, "stw_t": None}
ais = {"targets": [], "self": None, "t": 0.0}
V = np.zeros((250, 173), np.float32)
lock = threading.Lock()


# ------------------------------------------------------------------ radar ---
def nic_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((SOURCE or "198.18.0.1", PORT))     # picks the interface that has a 198.18.x address
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


def decode(payload, ncell):
    out, i = [], 0
    while i < len(payload) and len(out) < ncell:
        b = payload[i]
        if b == ESC and i + 2 < len(payload):
            run = struct.unpack_from("<H", payload, i + 1)[0]
            if len(out) + run <= ncell:
                out.extend([0] * run)
                i += 3
                continue
        out.append(b)
        i += 1
    out.extend([0] * (ncell - len(out)))
    return out


def reader():
    global V
    nicaddr = nic_address()
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
                                     socket.inet_aton(nicaddr), socket.inet_aton(SOURCE)))
            state["joined"] = "joined %s from %s" % (GROUP, SOURCE)
            joined = True
        except OSError:
            pass
    if not joined:
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         struct.pack("4s4s", socket.inet_aton(GROUP),
                                     socket.inet_aton(nicaddr)))
            state["joined"] = "joined %s" % GROUP
        except OSError as e:
            state["err"] = "cannot join the radar group: %s" % e
            return
    s.settimeout(2.0)
    n0, t0 = 0, time.time()
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
        cells = decode(d[20:], ncell)
        with lock:
            if V.shape != (naz, ncell):
                V = np.zeros((naz, ncell), np.float32)
            V[az] = cells
        state.update(az=az, naz=naz, ncell=ncell, last=time.time())
        state["spokes"] += 1
        n0 += 1
        if time.time() - t0 >= 1.0:
            state["pps"] = n0 / (time.time() - t0)
            n0, t0 = 0, time.time()


def navloop():
    while True:
        for key, path in (("hdg", "navigation/headingTrue"),
                          ("cog", "navigation/courseOverGroundTrue"),
                          ("sog", "navigation/speedOverGround"),
                          ("pos", "navigation/position")):
            try:
                nav[key] = json.load(urllib.request.urlopen(SK + path + "/value",
                                                            timeout=4))
                nav[key + "_ok"] = time.time()          # when we last really heard this value
            except Exception:
                pass
        for key, path in (("wind", "environment/wind/speedApparent"),
                          ("depth", "environment/depth/belowTransducer"),
                          ("wangle", "environment/wind/angleApparent"),
                          ("tangle", "environment/wind/angleTrueGround"),
                          ("rudder", "steering/rudderAngle"),
                          ("stw", "navigation/speedThroughWater")):
            try:
                o = json.load(urllib.request.urlopen(SK + path, timeout=4))
                nav[key] = o.get("value")
                nav[key + "_t"] = o.get("timestamp")
            except Exception:
                pass
        time.sleep(2)


def iso_age(ts):
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        t0 = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return time.time() - t0.timestamp()
    except Exception:
        return None


def aisloop():
    base = "http://127.0.0.1:3000/signalk/v1/api/"
    while True:
        try:
            if ais["self"] is None:
                ais["self"] = json.load(urllib.request.urlopen(base + "self", timeout=4))
            d = json.load(urllib.request.urlopen(base + "vessels", timeout=8))
            me = str(ais["self"]).replace("vessels.", "")
            out = []
            for vid, v in d.items():
                if vid in ("self", me):
                    continue
                n = v.get("navigation", {})
                p = n.get("position", {})
                pv = p.get("value")
                if not pv:
                    continue
                age = iso_age(p.get("timestamp"))
                if age is None or age > AIS_MAX_AGE:
                    continue
                sog = (n.get("speedOverGround", {}) or {}).get("value") or 0.0
                cog = (n.get("courseOverGroundTrue", {}) or {}).get("value")
                out.append({"id": vid, "name": (v.get("name") or vid.split(":")[-1])[:14],
                            "lat": pv["latitude"], "lon": pv["longitude"],
                            "sog": float(sog), "cog": cog, "age": age})
            ais["targets"] = out
            ais["t"] = time.time()
        except Exception:
            pass
        time.sleep(5)


def ais_ok():
    """True while the AIS poll of Signal K is succeeding. A dead feed must never read as 'all clear'."""
    return ais.get("t", 0.0) > 0 and time.time() - ais["t"] < 60


def stale_hint(key, limit=30):
    """'STALE 5 min' when a navigation value has not been refreshed recently, else ''."""
    t = nav.get(key + "_ok")
    if nav.get(key) is None or t is None:
        return ""
    a = time.time() - t
    return ("STALE " + age_text(a)) if a > limit else ""


def ais_problem():
    """None when AIS targets can be trusted, else the short reason to show instead of 'none closing on us'."""
    if not ais_ok():
        return "AIS: no feed from Signal K"
    if nav["pos"] is None or stale_hint("pos"):
        return "AIS: waiting for own position"
    return None


def near_ft_setting():
    try:
        return float(json.load(open(AIS_CONF)).get("near_ft", 650))
    except Exception:
        return 650.0


def compute_ais():
    """Range, bearing, closest point of approach and time to it, for every target."""
    pos = nav["pos"]
    if not pos or ais_problem():
        return []
    lat0, lon0 = pos["latitude"], pos["longitude"]
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0
    so = nav["sog"] or 0.0
    co = nav["cog"] if nav["cog"] is not None else 0.0
    vox, voy = so * math.sin(co), so * math.cos(co)
    near_m = near_ft_setting() / FT
    res = []
    for tg in list(ais["targets"]):
        dx, dy = (tg["lon"] - lon0) * kx, (tg["lat"] - lat0) * ky
        rng = math.hypot(dx, dy)
        if rng > 12 * 1852:
            continue
        brg = math.degrees(math.atan2(dx, dy)) % 360
        # a target that is moving but reports no course cannot be predicted: say unknown, do not assume north
        unknown_course = tg["cog"] is None and tg["sog"] * 1.9438 > 0.5
        ct = tg["cog"] if tg["cog"] is not None else 0.0
        vtx, vty = tg["sog"] * math.sin(ct), tg["sog"] * math.cos(ct)
        rvx, rvy = vtx - vox, vty - voy
        v2 = rvx * rvx + rvy * rvy
        tcpa, cpa = None, rng
        if v2 > 0.05 and not unknown_course:
            tcpa = -(dx * rvx + dy * rvy) / v2
            cpa = math.hypot(dx + rvx * max(tcpa, 0), dy + rvy * max(tcpa, 0))
        closing = tcpa is not None and tcpa > 0
        moving = tg["sog"] * 1.9438 > 0.5
        why = ""
        if moving and closing and tcpa <= DANGER_TCPA_S and cpa <= DANGER_CPA_FT / FT:
            why = "CPA"
        elif moving and rng <= near_m and closing:
            why = "NEAR"
        elif unknown_course and rng <= near_m:
            why = "NEAR"
        res.append(dict(tg, dx=dx, dy=dy, rng=rng, brg=brg, cpa=cpa, tcpa=tcpa,
                        danger=bool(why), why=why, moving=moving))
    return res


# ----------------------------------------------------------------- window ---
root = tk.Tk()
root.title("Exodus Radar")
root.configure(bg=BG)
# Full screen, no title bar, no taskbar - it is a radar, not a window. Esc toggles it off
# (handy on a desktop), F11 toggles it back on.
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
root.bind("<F11>", lambda e: root.attributes("-fullscreen", True))

main = tk.Frame(root, bg=BG)
main.pack(fill="both", expand=True)

# Controls: range dropdown + HEAD/NORTH UP sit in a slim bar at the top-left of the scope.
# Everything else (trails, AIS, gain) is behind the MORE button.
side = tk.Frame(main, bg=PANEL, width=210, height=290,
                highlightbackground="#3a4a5c", highlightthickness=1)
side.pack_propagate(False)
topbar = tk.Frame(main, bg=PANEL, highlightbackground="#3a4a5c", highlightthickness=1)
topbar.place(x=12, y=8)
rbtns = {}


def fmt_rng(r):
    return ("%g nm" % round(r, 3)) if r >= 0.25 else ("%d ft" % (round(r * NM_FT / 10) * 10))


def set_range(r):
    cfg["range"] = r
    savecfg()
    try:
        rng_var.set(fmt_rng(r))
    except NameError:
        pass
    for k, b in rbtns.items():
        b.configure(bg="#444466" if k == r else "#222222",
                    fg=WHITE if k == r else GREY)


_rlabels = [fmt_rng(r) for r in RANGES]
rng_var = tk.StringVar(value=fmt_rng(cfg["range"]))
rng_menu = tk.OptionMenu(topbar, rng_var, *_rlabels,
                         command=lambda v: set_range(RANGES[_rlabels.index(v)]))
rng_menu.configure(font=("DejaVu Sans", 16, "bold"), bg="#444466", fg=WHITE,
                   activebackground="#555588", activeforeground=WHITE, bd=0,
                   highlightthickness=0, width=7)
rng_menu["menu"].configure(font=("DejaVu Sans", 16), bg="#222222", fg=WHITE)
rng_menu.pack(side="left", padx=4, pady=4)


def toggle_north():
    cfg["northup"] = not cfg["northup"]
    savecfg()
    bnorth.configure(text="NORTH UP" if cfg["northup"] else "HEAD UP",
                     bg="#444466" if cfg["northup"] else "#4d4d1a")


bnorth = tk.Button(topbar, text="NORTH UP" if cfg["northup"] else "HEAD UP",
                   command=toggle_north, bd=0, fg=WHITE,
                   bg="#444466" if cfg["northup"] else "#4d4d1a",
                   font=("DejaVu Sans", 16, "bold"), pady=4, width=9)
bnorth.pack(side="left", padx=4, pady=4)


def toggle_trails():
    cfg["trails"] = not cfg["trails"]
    savecfg()
    btrail.configure(text="TRAILS ON" if cfg["trails"] else "TRAILS OFF",
                     bg="#444466" if cfg["trails"] else "#222222")


btrail = tk.Button(side, text="TRAILS ON" if cfg["trails"] else "TRAILS OFF",
                   command=toggle_trails, bd=0, fg=WHITE,
                   bg="#444466" if cfg["trails"] else "#222222",
                   font=("DejaVu Sans", 13), pady=5)
btrail.pack(fill="x", padx=8, pady=3)


def toggle_ais():
    cfg["ais"] = not cfg["ais"]
    savecfg()
    bais.configure(text="AIS ON" if cfg["ais"] else "AIS OFF",
                   bg="#444466" if cfg["ais"] else "#222222")


aisrow = tk.Frame(side, bg=PANEL)
aisrow.pack(fill="x", padx=8, pady=3)
bais = tk.Button(aisrow, text="AIS ON" if cfg["ais"] else "AIS OFF",
                 command=toggle_ais, bd=0, fg=WHITE,
                 bg="#444466" if cfg["ais"] else "#222222",
                 font=("DejaVu Sans", 11), pady=5)
bais.pack(side="left", fill="x", expand=True)

tk.Label(side, text="SCREEN GAIN", bg=PANEL, fg=GOLD,
         font=("DejaVu Sans", 13, "bold")).pack(pady=(8, 0))
gain = tk.Scale(side, from_=4, to=120, orient="horizontal", bg=PANEL, fg=WHITE,
                troughcolor="#222222", highlightthickness=0, bd=0,
                font=("DejaVu Sans", 11), length=170, width=16)
gain.set(cfg["gain"])
gain.pack(padx=8)

tk.Label(side, bg=PANEL, fg=DIM, wraplength=180, justify="left",
         font=("DejaVu Sans", 12),
         text=""
         ).pack(side="bottom", padx=14, pady=12)

rose_lbl = tk.Label(main, bg=PANEL, bd=0)

scope = tk.Label(main, bg=BG, bd=0)
scope.pack(side="left", padx=10)
topbar.lift()
# wind gauge sits at the top-right of the right column (330 x 330 on screen, ROSE_SHOW)
rose_lbl.place(relx=1.0, x=-330 - 18, y=124)


def toggle_more():
    """MORE = two columns docked at the RIGHT edge (the scope stays fully visible while you adjust):
    RANGE and display options, then the radar's settings."""
    if side.winfo_ismapped():
        side.place_forget()
        try:
            ctl.place_forget()
        except NameError:
            pass
    else:
        cw = 0
        try:
            ctl.update_idletasks()
            cw = ctl.winfo_reqwidth()
            ctl.place(relx=1.0, x=-16, y=66, anchor="ne")
            ctl.lift()
        except NameError:
            pass
        side.place(relx=1.0, x=-(cw + 30), y=66, anchor="ne")
        side.lift()


btn_more = tk.Button(topbar, text="MORE", command=toggle_more, bd=0, fg=WHITE, bg="#222222",
                     activebackground="#444466", font=("DejaVu Sans", 16), pady=4, width=5)
btn_more.pack(side="left", padx=4, pady=4)

# ------------------------------------------------------------ radar controls ---
# The radar's own controls (power, gain, sea, rain, range ...) are not in the spoke stream. They go through
# mayara, or any server that speaks the Signal K Radar API. This panel is built from whatever the radar says
# it supports, so it follows the radar model. Nothing is sent to the radar unless you press something.
MAYARA = str(_cfg_value("mayara_url", "http://127.0.0.1:6502")).rstrip("/")
RADAR_API = MAYARA + "/signalk/v2/api/vessels/self/radars"
rc = {"id": None, "name": "", "caps": None, "vals": {}, "ok": False, "err": "", "err_t": 0.0, "t": 0.0}


def _rc_get(path):
    return json.load(urllib.request.urlopen(RADAR_API + path, timeout=3))


def radarctl_loop():
    """Keeps a fresh copy of the radar's capabilities and control values."""
    while True:
        try:
            if rc["id"] is None:
                d = _rc_get("")
                ids = list((d.get("radars") or {}).keys())
                if ids:
                    rc["id"] = ids[0]
                    rc["name"] = d["radars"][ids[0]].get("name", ids[0])
            if rc["id"] is not None:
                if rc["caps"] is None:
                    _full = _rc_get("/%s/capabilities" % rc["id"])
                    rc["caps"] = _full.get("controls") or {}
                    set_palette(_full.get("legend"))
                rc["vals"] = _rc_get("/%s/controls" % rc["id"])
                rc["ok"] = True
                rc["t"] = time.time()
            else:
                rc["ok"] = False
        except Exception:
            rc["ok"] = False
        time.sleep(2)


def radar_put(cid, body):
    """Send one control change in the background so the screen never freezes."""
    if rc["id"] is None:
        rc["err"], rc["err_t"] = "no radar found", time.time()
        return

    def run():
        try:
            req = urllib.request.Request("%s/%s/controls/%s" % (RADAR_API, rc["id"], cid),
                                         data=json.dumps(body).encode(), method="PUT",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=4).read()
            cur = dict(rc["vals"].get(cid) or {})
            cur.update(body)
            rc["vals"][cid] = cur            # show it at once; the next poll confirms what the radar really did
        except Exception:
            rc["err"], rc["err_t"] = "could not set %s" % cid, time.time()
    threading.Thread(target=run, daemon=True).start()


ctl = tk.Frame(main, bg=PANEL, highlightbackground="#3a4a5c", highlightthickness=1)
rcw = {}                       # widgets by control id
_ctl = {"built": False, "tx_confirm": 0.0, "menu_built": False}
_rng_m = {}                    # range label -> metres, as the radar offers them
CTL_F = ("DejaVu Sans", 14)
CTL_B = ("DejaVu Sans", 14, "bold")


def power_click(v):
    """Off and Standby act at once. Transmit asks for a second press: it radiates."""
    if v == 2:
        if time.time() - _ctl["tx_confirm"] > 4:
            _ctl["tx_confirm"] = time.time()
            return
        _ctl["tx_confirm"] = 0.0
    radar_put("power", {"value": v})


def toggle_flag(cid, kind):
    cur = (rc["vals"].get(cid) or {}).get(kind)
    radar_put(cid, {kind: not bool(cur)})


def slider_release(cid):
    w = rcw.get(cid)
    if not w:
        return
    w["drag"] = False
    body = {"value": int(round(float(w["scale"].get())))}
    if w["kind"] == "auto":
        body["auto"] = False
    elif w["kind"] == "enabled":
        body["enabled"] = True
    radar_put(cid, body)


def _add_number(parent, cid, c):
    fr = tk.Frame(parent, bg=PANEL)
    fr.pack(fill="x", padx=12, pady=(8, 0))
    top = tk.Frame(fr, bg=PANEL)
    top.pack(fill="x")
    tk.Label(top, text=c.get("name", cid).upper(), bg=PANEL, fg=WHITE, font=CTL_B).pack(side="left")
    kind, tog = None, None
    if c.get("hasAuto"):
        kind = "auto"
    elif c.get("hasEnabled"):
        kind = "enabled"
    if kind:
        tog = tk.Button(top, text="AUTO" if kind == "auto" else "ON", bd=0, fg=WHITE, bg="#222222",
                        font=CTL_B, padx=16, command=lambda: toggle_flag(cid, kind))
        tog.pack(side="right")
    sc = tk.Scale(fr, from_=c.get("minValue", 0), to=c.get("maxValue", 100), orient="horizontal",
                  resolution=c.get("stepValue", 1) or 1, bg=PANEL, fg=WHITE, troughcolor="#222222",
                  highlightthickness=0, bd=0, font=CTL_F, length=270, width=30, sliderlength=44)
    sc.pack(fill="x")
    w = {"scale": sc, "tog": tog, "kind": kind, "drag": False}
    sc.bind("<ButtonPress-1>", lambda e, w=w: w.__setitem__("drag", True))
    sc.bind("<ButtonRelease-1>", lambda e, cid=cid: slider_release(cid))
    rcw[cid] = w


def _add_enum(parent, cid, c):
    desc = c.get("descriptions") or {}
    valid = c.get("validValues")
    keys = sorted((int(k) for k in desc), key=int)
    if valid:
        keys = [k for k in keys if k in valid] or keys
    if not keys:
        return
    fr = tk.Frame(parent, bg=PANEL)
    fr.pack(fill="x", padx=12, pady=(8, 0))
    tk.Label(fr, text=c.get("name", cid).upper(), bg=PANEL, fg=WHITE, font=CTL_B).pack(side="left")
    labels = {k: str(desc[str(k)]) for k in keys}
    var = tk.StringVar(value=labels[keys[0]])
    om = tk.OptionMenu(fr, var, *[labels[k] for k in keys],
                       command=lambda lab, cid=cid, labels=labels: radar_put(
                           cid, {"value": next(k for k, v in labels.items() if v == lab)}))
    om.configure(font=CTL_B, bg="#444466", fg=WHITE, activebackground="#555588", activeforeground=WHITE,
                 bd=0, highlightthickness=0, width=9)
    om["menu"].configure(font=CTL_F, bg="#222222", fg=WHITE)
    om.pack(side="right")
    rcw[cid] = {"var": var, "labels": labels}



def mayara_panel_url():
    """Address of mayara's own control page for this radar (its stock 'Radar Controls' panel)."""
    base = MAYARA
    try:
        d = json.load(urllib.request.urlopen(RADAR_API, timeout=3))
        ids = list((d.get("radars") or {}).keys())
        if ids:
            return "%s/gui/viewer.html?id=%s" % (base, rc["id"] or ids[0])
    except Exception:
        pass
    return base + "/gui/"


def open_mayara_panel():
    """Open mayara's stock radar control page in its own window (needs a browser on this machine)."""
    import subprocess
    url = mayara_panel_url()
    for exe in ("chromium-browser", "chromium", "google-chrome"):
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=1500,900"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
        except OSError:
            continue
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def build_radar_panel():
    caps = rc["caps"] or {}
    for w in ctl.winfo_children():
        w.destroy()
    rcw.clear()
    head = tk.Frame(ctl, bg=PANEL)
    head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4))
    tk.Label(head, text="RADAR", bg=PANEL, fg=GOLD, font=("DejaVu Sans", 20, "bold")).pack(side="left")
    rcw["status"] = tk.Label(head, text="", bg=PANEL, fg=GREY, font=CTL_F)
    rcw["status"].pack(side="right")
    left = tk.Frame(ctl, bg=PANEL)
    left.grid(row=1, column=0, sticky="n")
    right = tk.Frame(ctl, bg=PANEL)
    right.grid(row=1, column=1, sticky="n", padx=(10, 0))
    pw = caps.get("power")
    if pw:
        row = tk.Frame(left, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(6, 4))
        rcw["power_btns"] = {}
        for v in (pw.get("validValues") or [0, 1, 2]):
            name = str((pw.get("descriptions") or {}).get(str(v), v)).upper()
            b = tk.Button(row, text=name, bd=0, fg=WHITE, bg="#222222", font=CTL_B, pady=10, width=8,
                          command=lambda v=v: power_click(v))
            b.pack(side="left", padx=3, expand=True, fill="x")
            rcw["power_btns"][v] = b
    for cid in [k for k in ("gain", "colorGain", "sea", "rain") if k in caps]:
        _add_number(left, cid, caps[cid])
    for cid in ("mode", "interferenceRejection"):
        c = caps.get(cid)
        if c and c.get("dataType") == "enum" and not c.get("isReadOnly"):
            _add_enum(left, cid, c)
    tk.Button(left, text="FULL MAYARA PANEL", bd=0, fg=WHITE, bg="#444466",
              activebackground="#555588", font=CTL_B, pady=8,
              command=open_mayara_panel).pack(fill="x", padx=12, pady=(14, 8))


rlab = tk.Label(side, text="RANGE", bg=PANEL, fg=GOLD, font=("DejaVu Sans", 16, "bold"))
rbox = tk.Frame(side, bg=PANEL)
_first = side.winfo_children()[0]
rlab.pack(side="top", pady=(8, 2), before=_first)
rbox.pack(side="top", fill="x", padx=8, before=_first)
_rng_btns = {}


def rebuild_range_buttons():
    for w in rbox.winfo_children():
        w.destroy()
    _rng_btns.clear()
    items = sorted(_rng_m.items(), key=lambda kv: kv[1])
    for i, (lab, m) in enumerate(items):
        b = tk.Button(rbox, text=lab, bd=0, fg=WHITE, bg="#222222", font=("DejaVu Sans", 13, "bold"),
                      pady=3, command=lambda l=lab: on_range_pick(l))
        b.grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")
        _rng_btns[m] = b
    rbox.grid_columnconfigure(0, weight=1)
    rbox.grid_columnconfigure(1, weight=1)
    rows = (len(items) + 1) // 2
    side.configure(width=270, height=60 + rows * 40 + 300)


def rebuild_range_menu():
    r = (rc["caps"] or {}).get("range") or {}
    vals = r.get("validValues") or []
    if not vals:
        return
    menu = rng_menu["menu"]
    menu.delete(0, "end")
    _rng_m.clear()
    for m in vals:
        lab = fmt_rng(m / 1852.0)
        _rng_m[lab] = m
        menu.add_command(label=lab, command=lambda l=lab: on_range_pick(l))
    _ctl["menu_built"] = True
    rebuild_range_buttons()


def on_range_pick(label):
    m = _rng_m.get(label)
    if m is None:
        return
    radar_put("range", {"value": m})
    cfg["range"] = m / 1852.0
    rng_var.set(label)


def rc_update_ui():
    now = time.time()
    if rc["caps"] and not _ctl["built"]:
        build_radar_panel()
        _ctl["built"] = True
    if rc["caps"] and not _ctl["menu_built"]:
        rebuild_range_menu()
    # the display follows the radar's real range, so rings, AIS and the anchor circle are always to scale
    rv = (rc["vals"].get("range") or {}).get("value")
    if rc["ok"] and rv:
        r_nm = float(rv) / 1852.0
        if abs(cfg["range"] - r_nm) > 1e-6:
            cfg["range"] = r_nm
            rng_var.set(fmt_rng(r_nm))
    btn_more.configure(fg=WHITE if rc["ok"] else AMBER)
    power_btn_refresh()
    for m, b in _rng_btns.items():
        b.configure(bg="#444466" if abs(m / 1852.0 - cfg["range"]) < 1e-6 else "#222222")
    if not _ctl["built"]:
        return
    st = rcw.get("status")
    if st is not None:
        if now - rc["err_t"] < 6:
            st.configure(text=rc["err"], fg=RED)
        elif rc["ok"]:
            st.configure(text=rc["name"], fg=GREEN)
        else:
            st.configure(text="no answer from radar control (mayara)", fg=AMBER)
    pb = rcw.get("power_btns") or {}
    pv = (rc["vals"].get("power") or {}).get("value")
    confirming = now - _ctl["tx_confirm"] <= 4
    for v, b in pb.items():
        on = pv == v
        if v == 2 and confirming:
            b.configure(text="PRESS AGAIN", bg="#5a4d00", fg=WHITE)
            continue
        base = str((((rc["caps"] or {}).get("power") or {}).get("descriptions") or {}).get(str(v), v)).upper()
        b.configure(text=base, bg=("#5a1a1a" if v == 2 else "#5a4d00" if v == 1 else "#3a4a5c") if on else "#222222")
    for cid, w in rcw.items():
        if cid in ("status", "power_btns"):
            continue
        val = rc["vals"].get(cid) or {}
        if "scale" in w:
            if not w["drag"] and val.get("value") is not None:
                try:
                    if abs(float(w["scale"].get()) - float(val["value"])) > 0.5:
                        w["scale"].set(val["value"])
                except Exception:
                    pass
            if w["tog"] is not None:
                flag = val.get("auto") if w["kind"] == "auto" else val.get("enabled")
                w["tog"].configure(bg="#1a4d1a" if flag else "#222222")
        elif "var" in w and val.get("value") is not None:
            lab = w["labels"].get(int(val["value"]))
            if lab:
                w["var"].set(lab)


def rc_tick():
    try:
        rc_update_ui()
    except Exception:
        pass
    root.after(700, rc_tick)

# ----------------------------------------------------------- power button ---
# Always on the top bar: shows what the radar is doing and lets you change it. Off and Standby act at once;
# Transmit needs a second tap within 4 seconds (it radiates), and says so on the button.
_PW_NAMES = {0: "OFF", 1: "STANDBY", 2: "TRANSMIT", 3: "PREPARING", 4: "FAULT"}
_PW_BG = {0: "#3a4a5c", 1: "#5a4d00", 2: "#5a1a1a", 3: "#5a4d00", 4: "#5a1a1a"}


def power_btn_click():
    if time.time() - _ctl["tx_confirm"] <= 4:      # armed: this second tap sends Transmit
        power_click(2)
        return
    try:
        x = btn_power.winfo_rootx()
        y = btn_power.winfo_rooty() + btn_power.winfo_height()
        pmenu.tk_popup(x, y)
    finally:
        pmenu.grab_release()


def power_btn_refresh():
    if time.time() - _ctl["tx_confirm"] <= 4:
        btn_power.configure(text="TAP AGAIN: TRANSMIT", bg="#5a4d00", fg=WHITE)
        return
    if not rc["ok"]:
        btn_power.configure(text="RADAR: NO LINK", bg="#222222", fg=AMBER)
        return
    pv = (rc["vals"].get("power") or {}).get("value")
    btn_power.configure(text="POWER: " + _PW_NAMES.get(pv, "?"), bg=_PW_BG.get(pv, "#222222"), fg=WHITE)


pmenu = tk.Menu(root, tearoff=0, font=("DejaVu Sans", 20, "bold"), bg="#222222", fg=WHITE,
                activebackground="#444466", activeforeground=WHITE, bd=2)
pmenu.add_command(label="   TRANSMIT   ", command=lambda: power_click(2))
pmenu.add_command(label="   STANDBY   ", command=lambda: power_click(1))
pmenu.add_command(label="   OFF   ", command=lambda: power_click(0))
btn_power = tk.Button(topbar, text="POWER", command=power_btn_click, bd=0, fg=WHITE, bg="#222222",
                      activebackground="#444466", font=("DejaVu Sans", 16, "bold"), pady=4, width=18)
btn_power.pack(side="left", padx=4, pady=4)

info = tk.Frame(main, bg=PANEL)
info.pack(side="left", fill="both", expand=True, pady=(0, 58))   # leave the 52 px rudder strip free
rose_lbl.lift()

# ---- anchor watch box (bottom right). Sets /home/pi/.anchor-watch.json; the
# anchor-watch service does the watching and the alarming.
def aw_read(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}


def aw_write(**kw):
    cur = aw_read(AW_CFG)
    new = {"armed": bool(cur.get("armed", False)),
           "radius_ft": float(cur.get("radius_ft", 150)),
           "anchor": cur.get("anchor")}
    new.update(kw)
    if "armed" in kw:
        new["anchor"] = None          # switching on (or off) always re-takes the position
    tmp = AW_CFG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f)
    os.replace(tmp, AW_CFG)


aw = tk.Frame(info, bg="#151c26", highlightbackground="#3a4a5c", highlightthickness=1)
aw.pack(side="bottom", fill="x", padx=14, pady=14)
awhead = tk.Frame(aw, bg="#151c26")
awhead.pack(fill="x", padx=12, pady=(4, 0))
awstate = tk.Label(awhead, text="", bg="#151c26", fg=GREY,
                   font=("DejaVu Sans", 16, "bold"))
awstate.pack(side="right")
awrow = tk.Frame(aw, bg="#151c26")
awrow.pack(fill="x", padx=8, pady=(6, 6))


def aw_toggle():
    cur = aw_read(AW_CFG)
    aw_write(armed=not cur.get("armed", False))


awbtn = tk.Button(awrow, text="WATCH OFF", command=aw_toggle, bd=0, fg=WHITE,
                  bg="#3a1a1a", activebackground="#5a2a2a",
                  font=("DejaVu Sans", 18, "bold"), width=10, pady=3)
awbtn.pack(side="left")
awrng = tk.Frame(awrow, bg="#151c26")
awrng.pack(side="right")


def aw_step(delta):
    cur = aw_read(AW_CFG)
    r = float(cur.get("radius_ft", 150)) + delta
    aw_write(radius_ft=max(25.0, min(2000.0, r)))


tk.Button(awrng, text="\u2212", command=lambda: aw_step(-25), bd=0, fg=WHITE,
          bg="#444466", font=("DejaVu Sans", 18, "bold"), width=2).pack(side="left")
awrad = tk.Label(awrng, text="150 ft", bg="#151c26", fg=WHITE, width=7,
                 font=("DejaVu Sans Mono", 18, "bold"))
awrad.pack(side="left", padx=4)
tk.Button(awrng, text="+", command=lambda: aw_step(25), bd=0, fg=WHITE,
          bg="#444466", font=("DejaVu Sans", 18, "bold"), width=2).pack(side="left")
awinfo = tk.Label(aw, text="", bg="#151c26", fg=GREY, anchor="w", justify="left",
                  font=("DejaVu Sans", 13), wraplength=820)
awinfo.pack(fill="x", padx=12, pady=(0, 4))

ph_w = max(420, root.winfo_screenwidth() - SC - 34)
ph_h = max(500, root.winfo_screenheight() - 40 - 250 - 30 - 88 + 110)

# rudder bar and status line sit at the bottom of the right column (above the anchor watch)
# so the round scope can use the full window height
RUD_W, RUD_H = root.winfo_screenwidth() - 12, 52
status = tk.Label(info, bg=PANEL, fg=GREEN, anchor="w", justify="left", wraplength=ph_w - 28,
                  font=("DejaVu Sans Mono", 12))
status.pack(side="bottom", fill="x", padx=14, pady=(0, 6))
rudder_lbl = tk.Label(root, bg=BG, bd=0)
rudder_lbl.pack(side="bottom", fill="x", padx=6, pady=(4, 0))
panel = tk.Label(info, bg=PANEL, bd=0, anchor="n")
panel.pack(side="top", fill="both", expand=True)
# bottom stack, lowest first: rudder bar, anchor watch box, status line
for _w in (rudder_lbl, aw, status):
    _w.pack_forget()
rudder_lbl.place(x=6, rely=1.0, y=-RUD_H - 2, width=RUD_W, height=RUD_H)     # full window width, very bottom
rudder_lbl.lift()
aw.pack(side="bottom", fill="x", padx=14, pady=(4, 4))
# status line (NO RADAR DATA ... joined ...) is not shown any more; the widget still exists so the updater is happy

set_range(cfg["range"])

# ---------------------------------------------------------------- geometry --
C = SC // 2
RAD = SC // 2 - 62                    # leave room for the bearing scale
_yy, _xx = np.mgrid[0:SC, 0:SC].astype(np.float32)
_dx, _dy = _xx - C, _yy - C
_rr = np.sqrt(_dx * _dx + _dy * _dy)
_ang = (np.arctan2(_dy, _dx) + np.pi / 2) % (2 * np.pi)
INSIDE = _rr <= RAD
_cache = {}



# ---- crisp rendering, like the stock mayara page ----
# The radar sends 250 spokes x 173 cells. Drawn as-is each cell becomes a visible block. Two things fix that:
# (1) the polar data is interpolated up (smooth, not blocky), (2) everything drawn on the scope is rendered at
# SS x size and averaged down, so rings, ticks, text and targets have soft anti-aliased edges.
UP_AZ, UP_R = 3, 2
SS = 2


def upsample_spokes(S):
    naz, nc = S.shape
    ext = np.concatenate([S, S[:1]], axis=0)                       # wrap round in azimuth
    A = np.empty((naz * UP_AZ, nc), np.float32)
    for k in range(UP_AZ):
        t = k / float(UP_AZ)
        A[k::UP_AZ] = ext[:-1] * (1.0 - t) + ext[1:] * t
    ext2 = np.concatenate([A, A[:, -1:]], axis=1)
    U = np.empty((A.shape[0], nc * UP_R), np.float32)
    for k in range(UP_R):
        t = k / float(UP_R)
        U[:, k::UP_R] = ext2[:, :-1] * (1.0 - t) + ext2[:, 1:] * t
    return U


_flat = {}


def _flat_index(nazu, ncu):
    """Which upsampled-spoke cell each pixel inside the scope reads (computed once per spoke geometry)."""
    key = (nazu, ncu)
    if _flat.get("key") != key:
        azm, cm = polar(nazu, ncu)
        inside = np.flatnonzero(INSIDE.ravel())
        _flat["key"] = key
        _flat["inside"] = inside
        _flat["az"] = azm.ravel()[inside].astype(np.int32)
        _flat["cm"] = cm.ravel()[inside].astype(np.int32)
        _flat["lin0"] = _flat["az"] * ncu + _flat["cm"]
    return _flat


class SSDraw:
    """A stand-in for ImageDraw on the scope: draws at SS x resolution straight onto the upscaled picture,
    then averages down. Same calls as ImageDraw; coordinates and widths are in normal (1x) units."""

    def __init__(self, base):
        self.base = base
        self.big = base.resize((base.width * SS, base.height * SS), Image.BILINEAR)
        self.d = ImageDraw.Draw(self.big)
        self._fonts = {}
        self._m = ImageDraw.Draw(base)

    def _s(self, v):
        if isinstance(v, (int, float)):
            return v * SS
        if isinstance(v, tuple):
            return tuple(self._s(x) for x in v)
        if isinstance(v, list):
            return [self._s(x) for x in v]
        return v

    def _f(self, font):
        k = id(font)
        if k not in self._fonts:
            try:
                self._fonts[k] = font.font_variant(size=int(font.size * SS))
            except Exception:
                self._fonts[k] = font
        return self._fonts[k]

    def textlength(self, text, font=None, **kw):
        return self._m.textlength(text, font=font, **kw)            # in 1x units, as the callers expect

    def __getattr__(self, name):
        fn = getattr(self.d, name)

        def call(*a, **kw):
            a = [self._s(x) if i == 0 else x for i, x in enumerate(a)]
            if isinstance(kw.get("width"), (int, float)):
                kw["width"] = max(1, int(round(kw["width"] * SS)))
            if kw.get("font") is not None:
                kw["font"] = self._f(kw["font"])
            return fn(*a, **kw)
        return call

    def finish(self):
        return self.big.reduce(SS)


def polar(naz, ncell):
    key = (naz, ncell)
    if key not in _cache:
        _cache.clear()
        _cache[key] = (np.clip((_ang / (2 * np.pi) * naz).astype(np.int32), 0, naz - 1),
                       np.clip((_rr / RAD * ncell).astype(np.int32), 0, ncell - 1))
    return _cache[key]


try:
    F  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 19)
    FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
except Exception:
    F = FB = ImageFont.load_default()


def hdg_deg():
    return None if nav["hdg"] is None else math.degrees(nav["hdg"]) % 360


def on_click(ev):
    dx, dy = ev.x - C, ev.y - C
    r = math.hypot(dx, dy)
    if r > RAD:
        state["cursor"] = None
        return
    scr = (math.degrees(math.atan2(dx, -dy))) % 360
    h = hdg_deg()
    if cfg["northup"]:
        true_b, rel_b = scr, (scr - h) % 360 if h is not None else None
    else:
        rel_b, true_b = scr, (scr + h) % 360 if h is not None else None
    state["cursor"] = (ev.x, ev.y, rel_b, true_b, r / RAD * cfg["range"])


scope.bind("<Button-1>", on_click)


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
PF_TITLE = _font(TITLE_FONT, 118)
PF_BIG, PF_MID, PF_SMALL = _font(MONO_B, 34), _font(MONO_B, 27), _font(SANS, 17)
PF_HEAD = _font(SANS_B, 26)
PF_LBL = _font(MONO, 22)
PFN_LBL = _font(MONO, 28)          # underway readout labels
PFN_BIG = _font(MONO_B, 46)        # underway readout values
PFN_MID = _font(MONO_B, 34)

_panel_base = None


def panel_base():
    """The panel background with the boat's logo faded in behind everything."""
    global _panel_base
    if _panel_base is None:
        im = Image.new("RGB", (ph_w, ph_h), (17, 17, 17))
        try:
            lg = _logo_img()
            # bottom-centred and sized to sit under the wind gauge, so the gauge never cuts it off
            s = min(ph_w - 40, ph_h - 480, 560)
            lg = lg.resize((s, s))
            lg = lg.point(lambda p: int(p * 0.22))      # a little lighter so it reads as a watermark
            lg3 = Image.merge("RGB", (lg, lg, lg))
            tmp = Image.new("RGB", (ph_w, ph_h), (0, 0, 0))
            tmp.paste(lg3, ((ph_w - s) // 2, ph_h - s - 24))
            im = ImageChops.add(im, tmp)
        except Exception:
            pass
        _panel_base = im
    return _panel_base.copy()


def fmt_dist(m):
    ft = m * FT
    return "%d ft" % (round(ft / 10) * 10) if ft < 1000 else "%.2f nm" % (m / 1852.0)


def age_text(sec):
    if sec < 90:
        return "%d s" % sec
    if sec < 5400:
        return "%d min" % (sec / 60)
    return "%.0f h" % (sec / 3600)


def current_now():
    """Tide / current from the difference between how the boat moves through the water and over the ground.

    water-referenced velocity  = STW along the heading        (boat through the water)
    ground-referenced velocity = SOG along the COG            (boat over the ground)
    current                    = ground - water               (where the water itself is going)

    Returns (drift_kn, set_true_deg_toward) or None if STW, heading or SOG are missing or stale.
    At anchor SOG is ~0, so the current is simply the STW reversed. Paddlewheel STW and heading
    errors make this an ESTIMATE; below about 0.3 kn it is mostly noise.
    """
    sw, sa = nav["stw"], iso_age(nav["stw_t"])
    if sw is None or (sa is not None and sa > 120):
        return None
    hd, so = nav["hdg"], nav["sog"]
    if hd is None or so is None:
        return None
    if so < 0.13:                       # under 0.25 kn: treat as not moving over the ground
        gx = gy = 0.0
    elif nav["cog"] is None:
        return None
    else:
        gx, gy = so * math.sin(nav["cog"]), so * math.cos(nav["cog"])
    wx, wy = sw * math.sin(hd), sw * math.cos(hd)
    cx, cy = gx - wx, gy - wy
    return math.hypot(cx, cy) * 1.9438452, math.degrees(math.atan2(cx, cy)) % 360


_bigfonts = {}


def bigfont(size):
    if size not in _bigfonts:
        _bigfonts[size] = _font(MONO_B, size)
    return _bigfonts[size]


def render_anchor_panel(danger_list, ntargets):
    """Anchor watch is ON, so we are at anchor: DEPTH, WIND, SOG and STW as big as the panel allows."""
    im = panel_base()
    d = ImageDraw.Draw(im)
    WHITE_, DIM_, AMB_ = (236, 243, 250), (138, 154, 171), (245, 166, 35)

    def fresh(ts):
        a = iso_age(ts)
        return a is None or a <= 120

    dp = nav["depth"]
    d_ok = dp is not None and fresh(nav["depth_t"])
    d_hint = "" if dp is None or d_ok else "STALE " + age_text(iso_age(nav["depth_t"]))
    so = nav["sog"]
    cu = current_now()
    sw = nav["stw"]
    sfresh = sw is not None and fresh(nav["stw_t"])
    GREYc = (110, 120, 130)
    y = 36
    LIMIT = 525                         # keep the digits clear of the wind gauge on the right
    tail_h = 78 + 38 + 34 + 12          # CURRENT (STW in its hint), AIS header, one entry, gap
    SIZE = int(((ph_h - y - tail_h) / 2 - 20) / 1.12)

    def bigrow(label, unit, num, hint, col):
        nonlocal y
        head = "%s  (%s)" % (label, unit)
        d.text((24, y), head, font=PF_HEAD, fill=DIM_)
        if hint:
            d.text((24 + d.textlength(head, font=PF_HEAD) + 16, y + 4), hint, font=PF_LBL, fill=AMB_)
        size = SIZE
        while size > 60 and d.textlength(num, font=bigfont(size)) > LIMIT:
            size -= 6
        d.text((24, y + 12), num, font=bigfont(size), fill=col)
        y += int(size * 1.12) + 20

    bigrow("DEPTH", "ft", "---" if dp is None else "%.1f" % (dp * FT), d_hint,
           WHITE_ if d_ok else (AMB_ if dp is not None else GREYc))
    bigrow("SOG", "kn", "---" if so is None else "%.1f" % (so * 1.9438452), stale_hint("sog"),
           WHITE_ if so is not None else GREYc)
    # CURRENT stays normal size; the STW line is folded into its hint
    d.text((24, y), "CURRENT", font=PF_HEAD, fill=DIM_)
    cl = 24 + d.textlength("CURRENT", font=PF_HEAD) + 16
    if cu is None:
        d.text((cl, y + 4), "STW %.1f kn" % (sw * 1.9438452) if sfresh else "needs STW - log not reading",
               font=PF_LBL, fill=AMB_ if not sfresh else DIM_)
        d.text((24, y + 30), "no feed", font=PF_BIG, fill=GREYc)
    else:
        d.text((cl, y + 4), "STW %.1f kn" % (sw * 1.9438452) if sfresh else "STW vs SOG, setting true",
               font=PF_LBL, fill=DIM_)
        d.text((24, y + 30), "%.1f kn \u2192 %03d\u00b0" % cu, font=PF_BIG, fill=(79, 195, 247))
    y += 78 + 6
    d.line([22, y - 6, ph_w - 22, y - 6], fill=(34, 48, 64), width=1)
    d.text((22, y), "DANGEROUS AIS", font=PF_HEAD, fill=(255, 90, 82) if danger_list else (93, 217, 140))
    cnt = "%d tracked" % ntargets
    d.text((ph_w - 22 - d.textlength(cnt, font=PF_LBL), y + 4), cnt, font=PF_LBL, fill=DIM_)
    y += 38
    if not cfg["ais"]:
        d.text((22, y), "AIS is switched off", font=PF_LBL, fill=DIM_)
    elif ais_problem():
        d.text((22, y), ais_problem(), font=PF_LBL, fill=(245, 166, 35))
    elif not danger_list:
        d.text((22, y), "none closing on us", font=PF_LBL, fill=(93, 217, 140))
    else:
        for tg in danger_list[:1]:
            tc = "" if tg["tcpa"] is None else "%d:%02d" % divmod(int(tg["tcpa"]), 60)
            d.text((22, y), "%s  %s  CPA %s in %s" % (tg["name"], fmt_dist(tg["rng"]), fmt_dist(tg["cpa"]), tc),
                   font=PF_MID, fill=(255, 120, 110))
            y += 34
    return im


def render_panel(danger_list, ntargets):
    if _aw_cache["cfg"].get("armed"):
        return render_anchor_panel(danger_list, ntargets)
    im = panel_base()
    d = ImageDraw.Draw(im)
    # title, blackletter, over the logo
    y = 110

    def line(label, value, colour=(236, 243, 250), small=False):
        nonlocal y
        tag = ""
        if "  STALE" in value:                       # keep the number big, the age as a small amber tag
            value, tag = value.split("  STALE", 1)
            tag = "STALE" + tag
        f = PFN_BIG if (tag or not small) else PFN_MID
        d.text((22, y + 10), label, font=PFN_LBL, fill=(138, 154, 171))
        d.text((125, y), value, font=f, fill=colour)
        if tag:
            d.text((125 + d.textlength(value, font=f) + 16, y + 14), tag, font=PF_LBL, fill=(245, 166, 35))
        y += 62

    def ang(x):
        return "---" if x is None else "%03.0f\u00b0" % (math.degrees(x) % 360)

    line("HDG", ang(nav["hdg"]) + "  true" + ("  " + stale_hint("hdg") if stale_hint("hdg") else ""))
    line("SOG", "---" if nav["sog"] is None else "%.1f kn" % (nav["sog"] * 1.9438452)
         + ("  " + stale_hint("sog") if stale_hint("sog") else ""))
    # STW: speed through the water. At anchor SOG is ~0, so any STW is the tide or current.
    sw = nav["stw"]
    sa = iso_age(nav["stw_t"])
    sfresh = sw is not None and (sa is None or sa <= 120)
    line("STW", "%.1f kn" % (sw * 1.9438452) if sfresh else "no feed",
         (236, 243, 250) if sfresh else (110, 120, 130), small=not sfresh)
    cu_ = current_now()
    line("CUR", "no feed" if cu_ is None else "%.1f kn \u2192 %03d\u00b0" % cu_,
         (110, 120, 130) if cu_ is None else (79, 195, 247), small=True)
    dp = nav["depth"]
    da = iso_age(nav["depth_t"])
    if dp is None:
        line("DEPTH", "---")
    else:
        stale = da is not None and da > 120
        line("DEPTH", "%.1f ft" % (dp * FT) + ("  STALE %s" % age_text(da) if stale else ""),
             (245, 166, 35) if stale else (236, 243, 250), small=stale)
    pos = nav["pos"]
    line("POS", "---" if not pos else "%.4f, %.4f" % (pos["latitude"], pos["longitude"])
         + ("  " + stale_hint("pos") if stale_hint("pos") else ""), small=True)
    y += 6
    d.line([22, y, ph_w - 22, y], fill=(34, 48, 64), width=1)
    y += 10

    cur = state["cursor"]
    if cur:
        ft = cur[4] * NM_FT
        txt = "CURSOR  %s   REL %s   TRUE %s" % (
            "%.0f ft" % ft if ft < 1200 else "%.2f nm" % cur[4],
            "---" if cur[2] is None else "%03.0f" % cur[2],
            "---" if cur[3] is None else "%03.0f" % cur[3])
        d.text((22, y), txt, font=PF_LBL, fill=(79, 195, 247))
    else:
        d.text((22, y), "CURSOR  click the scope to measure", font=PF_LBL, fill=(90, 106, 120))
    y += 44

    d.text((22, y), "DANGEROUS AIS", font=PF_HEAD, fill=(255, 90, 82) if danger_list else (93, 217, 140))
    d.text((ph_w - 22 - d.textlength("%d tracked" % ntargets, font=PF_LBL), y + 4),
           "%d tracked" % ntargets, font=PF_LBL, fill=(138, 154, 171))
    y += 40
    if not cfg["ais"]:
        d.text((22, y), "AIS is switched off", font=PF_LBL, fill=(138, 154, 171))
    elif ais_problem():
        d.text((22, y), ais_problem(), font=PF_LBL, fill=(245, 166, 35))
    elif not danger_list:
        d.text((22, y), "none closing on us", font=PF_LBL, fill=(93, 217, 140))
    else:
        for tg in danger_list[:5]:
            tc = "" if tg["tcpa"] is None else "%d:%02d" % divmod(int(tg["tcpa"]), 60)
            d.text((22, y), tg["name"], font=PF_MID, fill=(255, 120, 110))
            y += 33
            d.text((22, y), "%s  %03.0f\u00b0T   CPA %s  in %s   %.1f kn" % (
                fmt_dist(tg["rng"]), tg["brg"], fmt_dist(tg["cpa"]), tc, tg["sog"] * 1.9438),
                font=PF_LBL, fill=(236, 243, 250))
            y += 34
    d.text((22, ph_h - 26), "A second opinion, not the ship's radar. Navigate on the Axiom.",
           font=PF_SMALL, fill=(90, 106, 120))
    return im


_aw_cache = {"t": 0.0, "cfg": {}, "st": {}}


def aw_refresh():
    if time.time() - _aw_cache["t"] < 1.0:
        return
    _aw_cache["t"] = time.time()
    _aw_cache["cfg"] = aw_read(AW_CFG)
    _aw_cache["st"] = aw_read(AW_STATUS)
    c, s = _aw_cache["cfg"], _aw_cache["st"]
    armed = bool(c.get("armed"))
    rad = float(c.get("radius_ft", 150))
    awrad.configure(text="%d ft" % rad)
    awbtn.configure(text="WATCH ON" if armed else "WATCH OFF",
                    bg="#1a4d1a" if armed else "#3a1a1a")
    alive = s and (time.time() - s.get("t", 0)) < 20
    state_ = s.get("state", "off") if alive else "nowatcher"
    dist = s.get("dist_ft")
    if not armed:
        awstate.configure(text="", fg=GREY)          # the WATCH OFF button already says so
        awinfo.configure(text="", fg=GREY)
    elif not alive:
        awstate.configure(text="NOT RUNNING", fg=RED)
        awinfo.configure(text="The anchor-watch service is not answering. Nothing is watching.", fg=RED)
    elif state_ == "alarm":
        awstate.configure(text="ALARM  %d ft" % (dist or 0), fg=RED)
        awinfo.configure(text="The boat is outside the circle. Switch the watch off to stop it.", fg=RED)
    elif state_ in ("nogps", "nogps_alarm"):
        awstate.configure(text="NO GPS", fg=AMBER)
        awinfo.configure(text="Waiting for a fresh position. A watch with no GPS is not watching.", fg=AMBER)
    else:
        awstate.configure(text="", fg=GREEN)        # watching and inside the circle: nothing to say
        awinfo.configure(text="", fg=GREY)
    # the state line and the message only take room when there is something to say
    if awstate.cget("text"):
        awhead.pack(fill="x", padx=12, pady=(4, 0), before=awrow)
    else:
        awhead.pack_forget()
    if awinfo.cget("text"):
        awinfo.pack(fill="x", padx=12, pady=(0, 4))
    else:
        awinfo.pack_forget()


ROSE_W, ROSE_H = 300, 300          # drawing size
ROSE_SHOW = 330                  # size on screen
_GF = _font(SANS_B, 17)
_GF_BIG = _font(SANS_B, 62)
_GF_MID = _font(SANS_B, 20)


def render_rose():
    """Wind gauge in the style of the chartplotter's: bow at the top, port red / starboard green
    sectors, big apparent wind speed in the middle, orange A = apparent wind angle,
    yellow T = true wind angle (over the ground: no log speed feeds the boat's true wind)."""
    BGc = (17, 17, 17)
    im = Image.new("RGB", (ROSE_W, ROSE_H), BGc)
    d = ImageDraw.Draw(im)
    cx = cy = ROSE_W // 2
    R = 140
    box = [cx - R, cy - R, cx + R, cy + R]
    d.ellipse(box, outline=(90, 106, 120), width=2)

    def xy(rad_ang, r):
        return cx + r * math.sin(rad_ang), cy - r * math.cos(rad_ang)

    # sectors (bearing from the bow, clockwise; PIL arcs start at 3 o'clock so subtract 90)
    arcbox = [cx - R + 6, cy - R + 6, cx + R - 6, cy + R - 6]
    for lo, hi in ((30, 60), (120, 150)):
        d.arc(arcbox, lo - 90, hi - 90, fill=(90, 205, 100), width=11)          # starboard
        d.arc(arcbox, 360 - hi - 90, 360 - lo - 90, fill=(215, 70, 70), width=11)  # port
    # ticks and numbers
    for deg in range(0, 360, 10):
        a = math.radians(deg)
        big = deg % 30 == 0
        d.line([xy(a, R - (16 if big else 8)), xy(a, R)], fill=(150, 170, 185) if big else (90, 106, 120),
               width=2 if big else 1)
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        n = deg if deg <= 180 else 360 - deg
        t = str(n)
        px, py = xy(a, R - 34)
        d.text((px - d.textlength(t, font=_GF) / 2, py - 10), t, font=_GF, fill=(200, 212, 222))
    # little boat, bow up
    d.polygon([(cx, cy - 70), (cx + 30, cy - 20), (cx + 26, cy + 62), (cx - 26, cy + 62), (cx - 30, cy - 20)],
              outline=(70, 82, 95), width=2)

    ang, spd = nav["wangle"], nav["wind"]
    age = iso_age(nav["wangle_t"])
    stale = ang is None or (age is not None and age > 120)
    sage = iso_age(nav["wind_t"])
    sstale = spd is None or (sage is not None and sage > 120)
    grey = (110, 120, 130)

    # true wind wedge (yellow T)
    tang = nav.get("tangle")
    tage = iso_age(nav.get("tangle_t"))
    if tang is not None and not (tage is not None and tage > 120):
        pts = [xy(tang, 80), xy(tang - 0.13, R - 22), xy(tang + 0.13, R - 22)]   # starts outside the speed number
        d.polygon(pts, fill=(235, 215, 40) if not stale else grey)
        lx, ly = xy(tang, R * 0.72)
        d.text((lx - 6, ly - 11), "T", font=_GF_MID, fill=(20, 20, 20))
    # apparent wind marker (orange A) on the ring
    if ang is not None:
        col = grey if stale else (245, 160, 40)
        mx, my = xy(ang, R - 20)
        d.ellipse([mx - 17, my - 17, mx + 17, my + 17], fill=col)
        d.text((mx - 7, my - 12), "A", font=_GF_MID, fill=(20, 20, 20))

    # speed in the middle
    d.text((cx - d.textlength("AWS", font=_GF) / 2, cy - 54), "AWS", font=_GF, fill=(138, 154, 171))
    sp = "---" if spd is None else "%.1f" % (spd * 1.9438452)
    d.text((cx - d.textlength(sp, font=_GF_BIG) / 2, cy - 36), sp, font=_GF_BIG,
           fill=grey if sstale else (236, 243, 250))
    d.text((cx - d.textlength("kn", font=_GF) / 2, cy + 36), "kn", font=_GF, fill=(138, 154, 171))
    if stale or sstale:
        t = "STALE %s" % age_text(max(age or 0, sage or 0)) if (age is not None or sage is not None) else "NO WIND"
        d.text((cx - d.textlength(t, font=_GF) / 2, cy + 62), t, font=_GF, fill=(245, 166, 35))
    side_ = 330 if _aw_cache["cfg"].get("armed") else 400
    return im.resize((side_, side_), Image.LANCZOS)


def render_rudder():
    W, H = RUD_W, RUD_H
    im = Image.new("RGB", (W, H), (17, 17, 17))
    d = ImageDraw.Draw(im)
    d.text((14, 8), "RUDDER", font=PF_LBL, fill=(138, 154, 171))
    x0, x1, mid, yb = 150, W - 230, 0, 0
    mid = (x0 + x1) // 2
    half = (x1 - x0) / 2
    top, bot = 6, 26
    d.rectangle([x0, top, x1, bot], outline=(50, 66, 82), width=2)
    for deg in range(-35, 36, 5):
        x = mid + deg / 35.0 * half
        major = deg % 10 == 0
        d.line([x, bot + 1, x, bot + (11 if major else 6)], fill=(138, 154, 171) if major else (80, 96, 110), width=2 if major else 1)
        if deg % 10 == 0 and deg != 0 and abs(deg) in (10, 20, 30):
            d.text((x - 10, bot + 9), str(abs(deg)), font=PF_SMALL, fill=(110, 126, 140))
    d.line([mid, top - 2, mid, bot + 2], fill=(200, 210, 220), width=3)
    r = nav["rudder"]
    age = iso_age(nav["rudder_t"])
    if r is None or (age is not None and age > 120):
        d.text((mid - 90, 14), "no rudder data", font=PF_LBL, fill=(110, 120, 130))
        txt = "---"
    else:
        deg = max(-35.0, min(35.0, math.degrees(r)))
        x = mid + deg / 35.0 * half
        col = (255, 77, 87) if deg < -0.5 else (34, 224, 106) if deg > 0.5 else (200, 210, 220)
        d.rectangle([min(mid, x), top + 4, max(mid, x), bot - 4], fill=col)
        d.polygon([(x, top - 4), (x - 8, top - 14), (x + 8, top - 14)], fill=(255, 255, 255))
        txt = "midships" if abs(math.degrees(r)) < 0.5 else "%d\u00b0 %s" % (
            round(abs(math.degrees(r))), "stbd" if r > 0 else "port")
    d.text((W - 220, 10), txt, font=PF_MID, fill=(236, 243, 250))
    d.text((x0 - 4, 4), "", font=PF_SMALL)
    d.text((x0 + 8, top + 3), "PORT", font=PF_SMALL, fill=(255, 100, 100))
    d.text((x1 - 52, top + 3), "STBD", font=PF_SMALL, fill=(60, 220, 120))
    return im


def swell_now():
    """A fresh swell reading from ~/.swell.json, or None. Nothing is invented; with no file nothing is drawn.

    {"t": <unix time>, "hs_ft": 3.0, "period_s": 8, "from_true_deg": 45}
    from_true_deg is optional: without it the height and period are shown but no direction bars are drawn.
    Experimental: needs something on your boat to write the file (see the README).
    """
    try:
        s = json.load(open(SWELL_FILE))
        if time.time() - float(s.get("t", 0)) < 600:
            frm = s.get("from_true_deg")
            return dict(frm=None if frm is None else float(frm), hs=float(s["hs_ft"]),
                        per=float(s.get("period_s", 0)))
    except Exception:
        pass
    return None


ECHO_X = [0.0, 0.5, 1.0]            # weak -> strong return
ECHO_R = [255, 255, 255]
ECHO_G = [225, 130, 40]
ECHO_B = [0, 0, 10]

# Echo colours. These follow the stock mayara page: the radar publishes a 128-level colour legend (dark blue ->
# green -> yellow -> red) and we read it from mayara at run time (set_palette). Until then, or if mayara is not
# running, this built-in ramp, sampled from the same legend, is used.
_DEFAULT_LEGEND = [(0, (0, 0, 0)), (8, (0, 0, 48)), (16, (0, 0, 97)), (24, (0, 0, 145)), (32, (0, 0, 194)),
                   (40, (0, 0, 242)), (48, (0, 36, 218)), (56, (0, 85, 170)), (64, (0, 133, 121)),
                   (72, (0, 182, 72)), (80, (0, 230, 24)), (88, (24, 236, 0)), (96, (72, 188, 0)),
                   (104, (121, 139, 0)), (112, (170, 91, 0)), (120, (218, 42, 0)), (127, (238, 18, 0))]


def _default_palette():
    xs = [p[0] for p in _DEFAULT_LEGEND]
    pal = np.zeros((256, 3), np.uint8)
    for i in range(256):
        k = min(127, i >> 1)
        for c in range(3):
            pal[i, c] = int(np.interp(k, xs, [p[1][c] for p in _DEFAULT_LEGEND]))
    return pal


PALETTE = _default_palette()


def set_palette(legend):
    """Build the 256-entry echo palette from a Signal K Radar API legend. Ignores a legend it cannot read."""
    global PALETTE
    try:
        px = legend["pixels"]
        n = int(legend.get("pixelColors") or 128)
        cols = []
        for p in px[:n]:
            h = p["color"].lstrip("#")
            cols.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        if len(cols) < 16:
            return
        pal = np.zeros((256, 3), np.uint8)
        for i in range(256):
            pal[i] = cols[min(len(cols) - 1, i * len(cols) // 256)]
        PALETTE = pal
    except Exception:
        pass



def draw():
    global V
    with lock:
        naz, ncell = V.shape
        snap = V.copy()
        V *= 0.97 if cfg["trails"] else 0.80
    h = hdg_deg()
    up = upsample_spokes(snap)                               # smooth, like the stock page's texture sampling
    nazu, ncu = up.shape
    fl = _flat_index(nazu, ncu)
    off = 0
    if cfg["northup"] and h is not None:
        off = int(round(h / 360.0 * nazu))
    lin = ((fl["az"] - off) % nazu) * ncu + fl["cm"] if off else fl["lin0"]
    vv = up.ravel().take(lin)                                # only the pixels inside the scope

    thr = gain.get()
    buf = np.zeros((SC * SC, 3), np.uint8)                   # pure black, like the stock mayara page
    lit = vv > thr
    buf[fl["inside"][lit]] = PALETTE[np.minimum(vv[lit], 255).astype(np.uint8)]
    im = Image.fromarray(buf.reshape(SC, SC, 3), "RGB")
    # faint Exodus mark in the lower-right corner of the scope, outside the range circle
    try:
        _s = max(120, SC // 6)
        _g = _logo_img().resize((_s, _s)).point(lambda p: int(p * 0.16))
        _box = (SC - _s - 10, SC - _s - 10, SC - 10, SC - 10)
        im.paste(ImageChops.add(im.crop(_box), Image.merge("RGB", (_g, _g, _g))), _box)
    except Exception:
        pass
    d = SSDraw(im)

    # range rings
    for frac in (0.25, 0.5, 0.75, 1.0):
        rr = RAD * frac
        d.ellipse([C - rr, C - rr, C + rr, C + rr], outline=(0, 255, 0), width=2)
        rng = cfg["range"] * frac
        lbl = ("%.2f nm" % rng) if rng >= 0.25 else ("%d ft" % round(rng * NM_FT))
        d.text((C + 6, C - rr - 18), lbl, font=F, fill=(0, 255, 0))

    # bearing scale
    for deg in range(0, 360, 5):
        a = math.radians(deg - 90)
        big = deg % 30 == 0
        r0 = RAD + (4 if big else 8)
        r1 = RAD + (20 if big else 13)
        d.line([C + r0 * math.cos(a), C + r0 * math.sin(a),
                C + r1 * math.cos(a), C + r1 * math.sin(a)],
               fill=(0, 200, 0) if big else (0, 110, 0), width=2 if big else 1)
        if big:
            rt = RAD + 36
            t = "%03d" % deg
            w = d.textlength(t, font=F)
            d.text((C + rt * math.cos(a) - w / 2, C + rt * math.sin(a) - 9),
                   t, font=F, fill=(0, 255, 0))

    # heading line and north marker
    if h is not None:
        ha = math.radians((0 if not cfg["northup"] else h) - 90)
        d.line([C, C, C + RAD * math.cos(ha), C + RAD * math.sin(ha)],
               fill=(0, 255, 0), width=2)
        na = math.radians((-h if not cfg["northup"] else 0) - 90)
        nx, ny = C + (RAD + 36) * math.cos(na), C + (RAD + 36) * math.sin(na)
        d.text((nx - 7, ny - 11), "N", font=FB, fill=(0, 255, 0))

    # own ship
    d.ellipse([C - 4, C - 4, C + 4, C + 4], fill=(255, 240, 160))

    def to_xy(dx_m, dy_m):
        """metres east/north of us -> pixels on this scope, honouring HEAD/NORTH UP"""
        brg = math.degrees(math.atan2(dx_m, dy_m))
        if not cfg["northup"]:
            if h is None:
                return None
            brg -= h
        r = math.hypot(dx_m, dy_m) / (cfg["range"] * 1852.0) * RAD
        a = math.radians(brg)
        return C + r * math.sin(a), C - r * math.cos(a), r

    # swell: ONLY while the anchor watch is ON. Underway, a boat driving into waves reads its own pitching and
    # the bow-on sea as "swell", so nothing is drawn then. At anchor: a neon light-blue two-row arc on the side
    # the swell comes FROM (when a direction is known) and a label; with no sensor the label says 0.0 ft.
    sw_ = swell_now() if _aw_cache["cfg"].get("armed") else None
    if sw_:
        has_dir = sw_["frm"] is not None and (cfg["northup"] or h is not None)
        if has_dir:
            th = sw_["frm"] - (0 if cfg["northup"] else h)
            a = math.radians(th)
            px_, py_ = math.cos(a), math.sin(a)
            # two rows of pointy waves (zig-zag crests): one on the outer ring, one just outside it,
            # across the arc the swell comes from; taller swell = taller crests
            amp = max(6.0, min(11.0, sw_["hs"] * 2.5))
            for k, (rr, wd) in enumerate(((RAD, 4), (RAD + 30, 3))):
                pts = []
                n_pts = 241
                for n_ in range(n_pts):
                    t_ = n_ / (n_pts - 1.0)
                    deg_ = -36.0 + 72.0 * t_                              # across the arc, degrees from the swell bearing
                    tri = (2.0 / math.pi) * math.asin(math.sin(2.0 * math.pi * (deg_ / 6.0)))      # both rows in step, crests 6 degrees apart
                    r_ = rr + amp * tri                                   # triangle wave = sharp peaks
                    phi = math.radians(th + deg_)
                    pts.append((C + r_ * math.sin(phi), C - r_ * math.cos(phi)))
                d.line(pts, fill=(0, 229, 255), width=wd, joint="curve")
            # and an arrow OUTSIDE the ring, pointing in at the arc: the way the swell is travelling
            ox, oy = math.sin(a), -math.cos(a)                    # outward unit vector
            t_x, t_y = C + (RAD + 5) * ox, C + (RAD + 5) * oy      # tip, just touching the arc
            k_x, k_y = t_x + 24 * ox, t_y + 24 * oy                # back of the head
            b_x, b_y = C + (RAD + 46) * ox, C + (RAD + 46) * oy    # end of the shaft
            d.line([k_x, k_y, b_x, b_y], fill=(0, 229, 255), width=6)
            d.polygon([(t_x, t_y), (k_x + 12 * px_, k_y + 12 * py_), (k_x - 12 * px_, k_y - 12 * py_)], fill=(0, 229, 255))
        lab = "SWELL  %.1f ft  %d s" % (sw_["hs"], round(sw_["per"]))
        if sw_["frm"] is not None:
            lab += "  from %03d\u00b0" % (round(sw_["frm"]) % 360)
        tw_ = d.textlength(lab, font=F)
        if has_dir:
            lx, ly = C + (RAD - 96) * math.sin(a), C - (RAD - 96) * math.cos(a)
            lx = min(max(lx - tw_ / 2, 8), SC - tw_ - 8)
        else:
            lx, ly = 24, SC - 150
        d.rectangle([lx - 6, ly - 12, lx + tw_ + 6, ly + 14], fill=(4, 18, 24), outline=(0, 229, 255))
        d.text((lx, ly - 10), lab, font=F, fill=(120, 240, 255))

    # anchor watch circle
    aw_refresh()
    acfg = _aw_cache["cfg"]
    if acfg.get("armed") and acfg.get("anchor") and nav["pos"]:
        try:
            lat0, lon0 = nav["pos"]["latitude"], nav["pos"]["longitude"]
            ax = (acfg["anchor"]["lon"] - lon0) * 111320.0 * math.cos(math.radians(lat0))
            ay = (acfg["anchor"]["lat"] - lat0) * 110540.0
            p = to_xy(ax, ay)
            if p:
                rpx = float(acfg.get("radius_ft", 150)) / FT / (cfg["range"] * 1852.0) * RAD
                alarm = (_aw_cache["st"] or {}).get("state") == "alarm"
                col = (255, 90, 82) if alarm else (245, 166, 35)
                d.ellipse([p[0] - rpx, p[1] - rpx, p[0] + rpx, p[1] + rpx], outline=col, width=3)
                d.line([p[0] - 9, p[1], p[0] + 9, p[1]], fill=col, width=2)
                d.line([p[0], p[1] - 9, p[0], p[1] + 9], fill=col, width=2)
        except Exception:
            pass

    # AIS targets
    tgts = compute_ais() if cfg["ais"] else []
    for tg in tgts:
        p = to_xy(tg["dx"], tg["dy"])
        if not p or p[2] > RAD:
            continue
        # like the stock mayara page: every target is a cyan triangle pointing the way it is going, with its name
        col = (255, 24, 24) if tg["danger"] else (0, 255, 255)
        x, y = p[0], p[1]
        s = 11 if tg["danger"] else 9
        if tg["danger"]:
            d.ellipse([x - s * 1.8, y - s * 1.8, x + s * 1.8, y + s * 1.8], outline=(255, 255, 255), width=2)
        cg = tg["cog"] if tg["cog"] is not None else 0.0
        hd = cg - (math.radians(h) if (not cfg["northup"] and h is not None) else 0)
        tri = [(x + math.cos(hd - math.pi / 2) * s * 1.6, y + math.sin(hd - math.pi / 2) * s * 1.6),
               (x + math.cos(hd + math.pi / 2 + 0.55) * s, y + math.sin(hd + math.pi / 2 + 0.55) * s),
               (x + math.cos(hd + math.pi / 2 - 0.55) * s, y + math.sin(hd + math.pi / 2 - 0.55) * s)]
        d.polygon(tri, fill=col)
        if tg["moving"] and tg["cog"] is not None:
            vx = math.sin(tg["cog"]) * tg["sog"] * 360
            vy = math.cos(tg["cog"]) * tg["sog"] * 360          # where it will be in 6 minutes
            q = to_xy(tg["dx"] + vx, tg["dy"] + vy)
            if q:
                d.line([x, y, q[0], q[1]], fill=col, width=2)
        d.text((x + 13, y - 10), tg["name"], font=F, fill=(255, 120, 110) if tg["danger"] else (0, 216, 216))
    danger_list = sorted([t_ for t_ in tgts if t_["danger"]],
                         key=lambda q: (q["tcpa"] is None, q["tcpa"] or 0))

    # cursor
    cur = state["cursor"]
    if cur:
        x, y = cur[0], cur[1]
        d.line([x - 12, y, x + 12, y], fill=(90, 200, 255), width=1)
        d.line([x, y - 12, x, y + 12], fill=(90, 200, 255), width=1)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(90, 200, 255), width=1)

    d.text((10, SC - 100), fmt_rng(cfg["range"]) + " range", font=FB,
           fill=(0, 255, 0))
    if not rc["ok"]:
        d.text((10, SC - 132), "radar range not verified", font=F, fill=(245, 166, 35))

    im = d.finish()
    ph = ImageTk.PhotoImage(im)
    scope.configure(image=ph)
    scope.image = ph

    pim = render_panel(danger_list, len(tgts))
    pph = ImageTk.PhotoImage(pim)
    panel.configure(image=pph)
    panel.image = pph

    rim = ImageTk.PhotoImage(render_rose())
    rose_lbl.configure(image=rim)
    rose_lbl.place_configure(x=-rim.width() - 18, y=(72 if rim.width() > 350 else 56))
    rose_lbl.image = rim
    rd_ = ImageTk.PhotoImage(render_rudder())
    rudder_lbl.configure(image=rd_)
    rudder_lbl.image = rd_

    live = (time.time() - state["last"]) < 3 if state["last"] else False
    if state["err"]:
        status.configure(text=state["err"], fg=AMBER)
    else:
        status.configure(
            text="%s   %3.0f spokes/s   bearing %3d/%d   %d cells   %s"
                 % ("RADAR LIVE" if live else "NO RADAR DATA - is it transmitting?",
                    state["pps"], state["az"], state["naz"], state["ncell"],
                    state["joined"]),
            fg=GREEN if live else AMBER)
    root.after(int(1000 / FPS), draw)


threading.Thread(target=reader, daemon=True).start()
threading.Thread(target=navloop, daemon=True).start()
threading.Thread(target=aisloop, daemon=True).start()
threading.Thread(target=radarctl_loop, daemon=True).start()
draw()
root.after(1000, rc_tick)
root.mainloop()
