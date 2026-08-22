# KiCad release hold

No orderable KiCad schematic or PCB is emitted at `CONCEPT-B`. The motor MPN and
current envelope, regenerative-energy path, dual-channel safety interface,
controller/protocol, power protection, connector land patterns, stackup and
thermal solution are unresolved release inputs. Creating a clean-looking board
with placeholder footprints would conceal those gaps.

`../placement-plan.csv`, `traction-childboard-concept.kicad_pcb` and
`../generated/placement-review.svg` provide a deterministic 118 x 82 mm
mechanical/functional review with a 108 x 72 mm four-hole pattern. The concept
board contains no electrical footprints, copper or routing and is explicitly
marked `DO NOT ORDER`; it does not claim land-pattern or circuit completion.
Electrical KiCad artifacts become mandatory after `MTR-MOTOR`, `MTR-POWER`,
`MTR-REGEN`, `MTR-SAFETY`, `MTR-CONTROL` and `MTR-DRV` close. They must then pass
ERC, DRC, connectivity, current-path, thermal and supplier DFM checks before the
`MTR-SCHEMATIC` and `MTR-LAYOUT` gates may pass.

The candidate net and safety contracts that the future schematic must implement
are `../net-topology.csv`, `../safety-gate-connectivity.csv` and
`../schematic-design.md`. They explicitly reserve a single `STAR_GND_01` join,
an isolated CAN power island, and independent `nFAULT` fan-outs to both safety
gates; none of these contracts is an orderable electrical design.
