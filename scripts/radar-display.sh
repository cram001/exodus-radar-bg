#!/bin/bash
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
# Exodus Radar - the working display. Separate from Radar Scope, which is the
# raw-bytes view built for the video.
export DISPLAY=:0
EXISTING=$(wmctrl -l 2>/dev/null | grep -F "Exodus Radar" | grep -v Scope | tail -n 1 | cut -d' ' -f1)
if [ -n "$EXISTING" ]; then
    wmctrl -i -a "$EXISTING" 2>/dev/null
    exit 0
fi
exec /usr/bin/python3 /home/pi/radar-display.py
