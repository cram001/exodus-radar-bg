#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Mayara radar-spoke receiver for the Exodus HDMI PPI.

Uses Mayara's documented RadarMessage protobuf stream. No generated protobuf
files are required; the message is decoded via the Google protobuf runtime.
"""
import json
import time
import urllib.request
from urllib.parse import urlparse, urlunparse

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


API_PATH = "/signalk/v2/api/vessels/self/radars"
MAX_SPOKES = 4096
MAX_CELLS = 4096


def _message_class():
    f = descriptor_pb2.FileDescriptorProto()
    f.name = "exodus_mayara_radar.proto"
    f.syntax = "proto3"
    radar = f.message_type.add()
    radar.name = "RadarMessage"
    spoke = radar.nested_type.add()
    spoke.name = "Spoke"
    for number, name, typ in (
        (1, "angle", 13), (2, "bearing", 13), (3, "range", 13),
        (4, "time", 4), (5, "data", 12), (6, "lat", 1), (7, "lon", 1)
    ):
        field = spoke.field.add()
        field.number, field.name, field.type = number, name, typ
        field.label = 1
    field = radar.field.add()
    field.number, field.name, field.type, field.label = 2, "spokes", 11, 3
    field.type_name = ".RadarMessage.Spoke"
    desc = descriptor_pool.DescriptorPool().Add(f)
    return message_factory.GetMessageClass(desc.message_types_by_name["RadarMessage"])


def discover(base_url, preferred_id=None):
    """Return (radar id, data, capabilities). Select deterministically."""
    with urllib.request.urlopen(base_url.rstrip("/") + API_PATH, timeout=5) as resp:
        payload = json.load(resp)
    radars = payload.get("radars", payload)
    if not isinstance(radars, dict) or not radars:
        raise RuntimeError("Mayara found no radars")
    if preferred_id:
        if preferred_id not in radars:
            raise RuntimeError("Configured Mayara radar ID not found: " + preferred_id)
        radar_id = preferred_id
    else:
        # On multi-radar installations, explicitly configure mayara_radar_id.
        radar_id = sorted(radars)[0]
    with urllib.request.urlopen(
        base_url.rstrip("/") + API_PATH + "/" + radar_id + "/capabilities", timeout=5
    ) as resp:
        caps = json.load(resp)
    return radar_id, radars[radar_id], caps


def spoke_url(base_url, radar_id, info):
    """Keep Mayara's advertised path but connect to the configured host."""
    base = urlparse(base_url)
    advertised = info.get("spokeDataUrl") or (API_PATH + "/" + radar_id + "/spokes")
    url = urlparse(advertised)
    scheme = "wss" if base.scheme == "https" else "ws"
    return urlunparse((scheme, base.netloc, url.path, "", url.query, ""))


def run(base_url, on_batch, on_status, preferred_id=None):
    """Blocking reconnecting worker. Call in a background thread.

    on_batch(rows, spokes_per_revolution, range_m): rows contain
    (relative angle, raw intensity bytes); angle zero is directly ahead.
    """
    import websocket  # websocket-client, not the similarly named websocket package
    Message = _message_class()
    while True:
        ws = None
        try:
            radar_id, info, caps = discover(base_url, preferred_id)
            naz = int(caps.get("spokesPerRevolution", 0))
            if not (1 <= naz <= MAX_SPOKES):
                raise ValueError("Invalid spokesPerRevolution: %r" % naz)
            url = spoke_url(base_url, radar_id, info)
            ws = websocket.create_connection(url, timeout=10, enable_multithread=True)
            on_status("Mayara connected: %s" % info.get("name", radar_id), "")
            while True:
                raw = ws.recv()
                if not isinstance(raw, bytes):
                    continue
                msg = Message()
                msg.ParseFromString(raw)
                grouped = {}
                for spoke in msg.spokes:
                    if 0 <= spoke.angle < naz and 0 < len(spoke.data) <= MAX_CELLS and spoke.range > 0:
                        grouped.setdefault((len(spoke.data), spoke.range), []).append(
                            (int(spoke.angle), bytes(spoke.data))
                        )
                for (ncell, range_m), rows in grouped.items():
                    on_batch(rows, naz, range_m)
        except Exception as exc:
            on_status("Mayara disconnected", "Mayara: %s" % exc)
            time.sleep(3)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
