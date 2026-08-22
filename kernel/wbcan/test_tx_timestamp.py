#!/usr/bin/env python3
"""Privileged SocketCAN software TX timestamp regression probe."""

from __future__ import annotations

import ctypes
import errno
import os
import select
import socket
import struct
import subprocess
import sys
import time


SO_TIMESTAMPING = 37
SOF_TIMESTAMPING_TX_HARDWARE = 1 << 0
SOF_TIMESTAMPING_TX_SOFTWARE = 1 << 1
SOF_TIMESTAMPING_RX_HARDWARE = 1 << 2
SOF_TIMESTAMPING_RX_SOFTWARE = 1 << 3
SOF_TIMESTAMPING_SOFTWARE = 1 << 4
SOF_TIMESTAMPING_RAW_HARDWARE = 1 << 6
SOF_TIMESTAMPING_OPT_ID = 1 << 7
SOF_TIMESTAMPING_OPT_TSONLY = 1 << 11
ETHTOOL_GET_TS_INFO = 0x00000041
SIOCETHTOOL = 0x8946
IFNAMSIZ = 16
CAN_FRAME = struct.Struct("=IB3x8s")


class EthtoolTsInfo(ctypes.Structure):
    _fields_ = [
        ("cmd", ctypes.c_uint32),
        ("so_timestamping", ctypes.c_uint32),
        ("phc_index", ctypes.c_int32),
        ("tx_types", ctypes.c_uint32),
        ("tx_reserved", ctypes.c_uint32 * 3),
        ("rx_filters", ctypes.c_uint32),
        ("rx_reserved", ctypes.c_uint32 * 3),
    ]


class Ifreq(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * IFNAMSIZ), ("data", ctypes.c_void_p)]


def run(*args: str) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def raw_socket(iface: str, *, loopback: bool = True, own_messages: bool = False) -> socket.socket:
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, int(loopback))
    sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_RECV_OWN_MSGS, int(own_messages))
    flags = (
        SOF_TIMESTAMPING_TX_SOFTWARE
        | SOF_TIMESTAMPING_SOFTWARE
        | SOF_TIMESTAMPING_OPT_ID
        | SOF_TIMESTAMPING_OPT_TSONLY
    )
    sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPING, flags)
    sock.bind((iface,))
    sock.setblocking(False)
    return sock


def collect_timestamps(sock: socket.socket, timeout: float = 0.8) -> int:
    deadline = time.monotonic() + timeout
    timestamps = 0
    while time.monotonic() < deadline:
        select.select([], [], [sock], min(0.05, deadline - time.monotonic()))
        try:
            _, ancillary, _, _ = sock.recvmsg(256, 512, socket.MSG_ERRQUEUE)
        except BlockingIOError:
            continue
        for level, kind, data in ancillary:
            if level != socket.SOL_SOCKET or kind != SO_TIMESTAMPING:
                continue
            if any(data):
                timestamps += 1
    return timestamps


def send_and_count(
    iface: str,
    can_id: int,
    *,
    loopback: bool = True,
    own_messages: bool = False,
    invalid: bool = False,
) -> tuple[bool, int]:
    with raw_socket(iface, loopback=loopback, own_messages=own_messages) as sock:
        frame = CAN_FRAME.pack(can_id, 1, bytes([can_id & 0xFF]) + bytes(7))
        accepted = True
        try:
            sock.send(frame[:-1] if invalid else frame)
        except OSError as error:
            if not invalid or error.errno not in {errno.EINVAL, errno.EMSGSIZE}:
                raise
            accepted = False
        return accepted, collect_timestamps(sock)


def timestamp_capabilities(iface: str) -> EthtoolTsInfo:
    info = EthtoolTsInfo(cmd=ETHTOOL_GET_TS_INFO)
    request = Ifreq(name=iface.encode("ascii"), data=ctypes.addressof(info))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        result = ctypes.CDLL(None, use_errno=True).ioctl(
            sock.fileno(), SIOCETHTOOL, ctypes.byref(request)
        )
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return info


def arm(debugfs: str, fault: str) -> None:
    with open(os.path.join(debugfs, "inject"), "w", encoding="ascii") as stream:
        stream.write(f"{fault}\n")


def check(name: str, condition: bool) -> bool:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    return condition


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} IFACE DEBUGFS", file=sys.stderr)
        return 2
    iface, debugfs = sys.argv[1:]
    if os.geteuid() != 0 or not os.path.isdir(debugfs):
        print("NOT_EXECUTED  privileged wbcan timestamp probe requires root and debugfs")
        return 77

    vcan = f"wbtstamp{os.getpid() % 100000}"
    results: list[bool] = []
    try:
        run("modprobe", "vcan")
        run("ip", "link", "add", vcan, "type", "vcan")
        run("ip", "link", "set", vcan, "up")

        accepted, count = send_and_count(vcan, 0x740)
        results.append(check("vcan reference emits one software TX timestamp", accepted and count == 1))

        info = timestamp_capabilities(iface)
        software = (
            SOF_TIMESTAMPING_TX_SOFTWARE
            | SOF_TIMESTAMPING_RX_SOFTWARE
            | SOF_TIMESTAMPING_SOFTWARE
        )
        hardware = (
            SOF_TIMESTAMPING_TX_HARDWARE
            | SOF_TIMESTAMPING_RX_HARDWARE
            | SOF_TIMESTAMPING_RAW_HARDWARE
        )
        results.append(
            check(
                "wbcan advertises software-only timestamp capabilities",
                info.so_timestamping & software == software
                and info.so_timestamping & hardware == 0
                and info.phc_index == -1
                and info.tx_types == 0
                and info.rx_filters == 0,
            )
        )

        cases = [
            ("normal loopback", "none 0", {}, 0x741),
            ("own-message enabled", "none 0", {"own_messages": True}, 0x742),
            ("loopback disabled", "none 0", {"loopback": False}, 0x743),
            ("accepted drop-tx", "drop-tx 1", {}, 0x744),
            ("accepted drop-rx", "drop-rx 1", {}, 0x745),
            ("accepted arb-lost error", "arb-lost 1", {}, 0x746),
            ("tx-full successful retry", "tx-full 1", {}, 0x747),
        ]
        for name, fault, options, can_id in cases:
            arm(debugfs, fault)
            accepted, count = send_and_count(iface, can_id, **options)
            results.append(check(f"{name} emits exactly one timestamp", accepted and count == 1))

        arm(debugfs, "none 0")
        accepted, count = send_and_count(iface, 0x748, invalid=True)
        results.append(check("invalid frame emits no timestamp", not accepted and count == 0))
    finally:
        try:
            arm(debugfs, "none 0")
        except OSError:
            pass
        subprocess.run(
            ("ip", "link", "del", vcan),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
