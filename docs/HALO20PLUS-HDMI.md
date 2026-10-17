# B&G HALO 20+ on Raspberry Pi 5 HDMI (development)

This branch adds a **Mayara** radar-spoke backend to the native Tkinter HDMI
display. It retains the Raymarine Quantum UDP reader as the default. This is
experimental software and is **not** a certified navigation display.

## Wiring and software

Connect the HALO 20+ and the Raspberry Pi 5's Ethernet interface to the
radar-capable Navico Ethernet network via a suitable Ethernet switch/adapter.
NMEA 2000 through Signal K/W2K-1 provides navigation data, **not** radar video.
Avoid using the Quantum-only 198.18.x.x static-address helper or the
Raymarine-specific DHCP guard scripts on the Navico network.

Install Mayara for Linux aarch64 per its upstream releases and verify HALO
discovery/echoes with Mayara first. The previous `services/mayara.service`
is an **example for the original author's system**, not a turnkey HALO service:
change its executable path, user and interface before installation.

On Raspberry Pi OS with a desktop and the system Python packages:

```bash
sudo apt update
sudo apt install python3-numpy python3-pil python3-pil.imagetk python3-tk \
  python3-protobuf python3-websocket
# If python3-websocket is unavailable on your distribution, install
# websocket-client in a Python virtual environment with system site packages.
```

Save the following in `~/.radar-display.json` (merge with your existing
preferences instead of overwriting them):

```json
{
  "radar_backend": "mayara",
  "mayara_url": "http://127.0.0.1:6502",
  "mayara_radar_id": "",
  "northup": false
}
```

When `mayara_radar_id` is empty the backend uses the first sorted radar ID
returned by Mayara. On installations with multiple radars set the exact ID.

Start the existing native display using `scripts/radar-display.sh` in an
HDMI desktop session. The spoke stream is decoded from Mayara's documented
`RadarMessage` protobuf binary WebSocket; native radar settings continue
to go through Mayara's existing REST control API.

## Acceptance tests on actual hardware

1. With Mayara running and the HALO in standby, confirm its REST API lists
   the HALO 20+ and the native screen shows the connection state.
2. Transmit using the primary B&G instrument, then verify moving spokes
   and recognizable echo targets on the HDMI screen.
3. Compare PPI orientation and measured target distance against the B&G
   plotter in head-up and north-up; do not rely on overlays until verified.
4. Change radar range on the plotter. Confirm the HDMI range rings and AIS
   scaling follow streamed spoke range.
5. Power-cycle the radar and restart Mayara. Confirm automatic reconnect.
6. Verify Signal K AIS, heading, depth, wind and anchor-watch operation.
7. Only then test control commands from the HDMI application. **Transmit
   requests require the existing two-press confirmation.**

## Notes

- The stream decoder is based on Mayara's public
  `src/lib/protos/RadarMessage.proto`, using clockwise relative angles
  and metres-to-end-of-spoke range. No manufacturer-specific packet
  parsing or hardcoded HALO multicast group is introduced.
- The app remains an experimental secondary instrument; use the B&G
  plotter and proper lookout for primary navigation.
- Features such as Doppler-specific colours, split dual-range selection,
  or ARPA are **not implemented** here.
