# can_adapters

This directory documents the physical adapter boundary. The Linux reference
implementation is the standard-library `SocketCANTransport` in
`libs/hardware/workbench/hardware/socketcan_transport.py`, hosted by
`SafeCANBus` and the single `DeviceRuntime`. It opens one
`AF_CAN`/`CAN_RAW` descriptor and does not create an adapter-local worker,
queue, callback registry or lifecycle state machine.

Candidate physical paths remain owner-gated:

- isolated USB-CAN-FD prototype adapter (first bring-up path);
- CANable 2.0 (USB, SocketCAN); and
- PCAN-USB (Peak Systems), subject to its Linux driver and licensing setup.

The adapter must preserve the frozen Wire V1 IDs and payload layout. It must
validate standard/extended/RTR/error flags, DLC, raw ID consistency, kernel
timestamps and receive-queue drops before passing a frame to the protocol
decoder. Only validated ACK, STOP_ACK and telemetry frames may become
`CanExternalRecord` projections. Rejected frames remain available through the
bounded receive result and diagnostics, but are not published to the external
queue. An external HTTP/dashboard consumer is read-only: it receives immutable
records and never receives a CAN fd, debugfs handle or write capability.

Run the virtual boundary probe in a privileged environment with a `wbcan0` or
`vcan0` interface:

```bash
python3 kernel/wbcan/test_socketcan_ingress.py wbcan0 \
  --source virtual-wbcan \
  --report /tmp/wbcan-socketcan-ingress-report.json
```

The report is explicitly `virtual-socketcan-ingress`. A missing privilege or
virtual interface is `NOT_EXECUTED`; virtual `PASS` does not prove physical
CAN arbitration, an MCU, an actuator, electrical integrity, PREEMPT_RT or a
hard-real-time deadline.

Physical setup, six-domain discovery, timestamps, raw capture hashing,
calibration references and cleanup requirements are defined in
[`docs/hardware/can_bring_up.md`](../../docs/hardware/can_bring_up.md).
