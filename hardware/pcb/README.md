# Controller PCB engineering package

Six-layer controller/power-distribution board for a 48 V desk robot. The package
defines the electrical architecture, interfaces, protection, isolated CAN,
stackup, placement/thermal constraints, DFM limits, and manufacturing outputs.

## Reproduce checks

```bash
python hardware/pcb/tools/electrical_checks.py
```

The report is written to `generated/electrical_report.json`. Open
`kicad/controller.kicad_pro` with KiCad 8 for schematic/layout completion and
fabrication export. KiCad CLI is not bundled in this repository; release must run
ERC, DRC, Gerber review, and archive the reports before ordering.

## Critical design-review correction

The original task suggestion (`TPS54160 + RT8059 + AMS1117`) is not load-capable:

- TPS54160 is a 1.5 A regulator and cannot supply the proposed 12 V motor rail.
- RT8059 is a low-current converter and cannot supply a 5 V / 8 A Jetson rail.
- AMS1117 cannot provide 3.3 V / 5 A and would exceed its thermal limit.

The baseline therefore uses a protected 48 V input, an isolated 48-to-12 V
240 W module, a 12-to-5 V 50 W synchronous buck, and a 12-to-3.3 V 20 W
synchronous buck. Exact manufacturer part numbers remain `AVL HOLD` until the
system owner approves the approved-vendor list.

## Release status

PCB1-5 and PCB9-11 have documented design evidence. PCB6/8 require KiCad routing
and field-solver/DRC evidence. PCB7 requires CTO review. PCB12-18 require ordered
boards, lab instruments, EMC facilities, and production operators; see
`verification-matrix.md` for explicit gates.
