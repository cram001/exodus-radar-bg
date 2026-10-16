#!/bin/bash
# Exodus Radar - Copyright 2026 Sailing Exodus (https://sailingexodus.net)
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Free to use on your own boat and for any non-commercial purpose. Want to use it in something you sell? Just ask: https://sailingexodus.net
# Mayara's own control GUI - transmit/standby, range, gain, sea, rain.
export DISPLAY=:0
URL="http://localhost:6502/gui/"
EXISTING=$(wmctrl -l 2>/dev/null | grep -iF "Mayara" | tail -n 1 | cut -d' ' -f1)
if [ -n "$EXISTING" ]; then
    wmctrl -i -a "$EXISTING" 2>/dev/null
    exit 0
fi
chromium-browser --new-window --window-size=1900,1000 --window-position=10,30 \
    "$URL" >/dev/null 2>&1 &
