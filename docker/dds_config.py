#!/usr/bin/env python3
"""Generate a bounded Fast DDS interface profile after validating the host NIC."""

from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path
from xml.sax.saxutils import escape

TEMPLATE = """<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>workbench_udp</transport_id>
      <type>UDPv4</type>
      <interfaceWhiteList><interface>{interface}</interface></interfaceWhiteList>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="workbench_bounded_dds" is_default_profile="true">
    <rtps>
      <userTransports><transport_id>workbench_udp</transport_id></userTransports>
      <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
  </participant>
</profiles>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    interface = os.environ.get("WORKBENCH_DDS_INTERFACE", "")
    valid_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
    if not interface or any(character not in valid_characters for character in interface):
        raise SystemExit("WORKBENCH_DDS_INTERFACE is required and contains invalid characters")
    try:
        socket.if_nametoindex(interface)
    except OSError as exc:
        raise SystemExit(f"DDS interface does not exist: {interface}") from exc
    Path(args.output).write_text(TEMPLATE.format(interface=escape(interface)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
