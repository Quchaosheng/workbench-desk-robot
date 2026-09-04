# BSP Bring-up Closure Checklist

This checklist is the release gate for moving the BSP from candidate selection
to a physically reproducible prototype image. A checked item must link to raw
evidence; a simulation result or CI pass is not physical evidence.

## 1. Hardware identity

- [ ] Carrier-board MPN, revision, schematic and pinmux are recorded.
- [ ] Jetson module SKU and board revision are recorded.
- [ ] CAN transceiver, connector, harness, termination and measured bitrate are recorded.
- [ ] Camera serial, USB topology, stream modes and calibration artifact are recorded.
- [ ] Arm and tool controller MPN, firmware, protocol and safety I/O are recorded.
- [ ] U2 exact MPN, input range, isolation rating, derating curve, footprint and thermal review are approved.

## 2. Reproducible software

- [ ] JetPack/L4T release, vendor package URLs and SHA256 values are locked.
- [ ] Kernel source, compiler, merged `.config`, Image/modules and DTB hashes are locked.
- [ ] Rootfs package lock, firmware bundle, recovery image and rollback procedure are attached.
- [ ] ROS 2 distribution and third-party package versions are pinned per deployment image.

## 3. Safety and performance evidence

- [ ] Power-on, brownout, thermal and sustained-load logs pass the acceptance limits.
- [ ] CAN loss, watchdog, emergency-stop and brake tests pass with measured trip times.
- [ ] Tip-stability tests cover every declared pose, payload and floor condition.
- [ ] Fault injection and recovery transcripts are archived with board and firmware identity.

## 4. Release decision

- [ ] Safety owner signs the hazard-analysis and external-inhibit review.
- [ ] Legal owner signs third-party license, NOTICE and redistribution review.
- [ ] Release owner verifies every manifest hash and evidence link.

Until all applicable boxes are checked, keep `bsp/readiness.yaml` at
`PRODUCTION_RELEASE_BLOCKED` and keep image inputs at `inputs_unresolved`.
