#!/bin/bash
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
# Exodus Radar Scope - live PPI straight off the Quantum's multicast stream.
# Needs nothing but the radar being powered and transmitting.
MATCH="Exodus Radar Scope"
EXISTING=$(wmctrl -l 2>/dev/null | grep -F "$MATCH" | tail -n 1 | cut -d' ' -f1)
if [ -n "$EXISTING" ]; then
    wmctrl -i -a "$EXISTING" 2>/dev/null
    exit 0
fi
exec /usr/bin/python3 /home/pi/radar-scope.py
