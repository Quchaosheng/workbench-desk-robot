# Dashboard design system

The operator dashboard is a quiet, read-only inspection surface. It helps an operator distinguish observed state, action/device state, verifier conclusions, missing evidence, and recovery history. It never exposes robot-control, firmware, emergency-stop, release, or completion authority.

## UI/UX task map

| Task | Artifact / acceptance |
|---|---|
| UI1 design system | this token, component, state, and accessibility contract |
| UI2 interaction framework | run selection, filtering, live/replay tabs, evidence dialog, keyboard model |
| UI3 implementation and integration | `apps/dashboard/` plus read-only backend behavior tests |
| UI4 usability testing | [usability protocol](dashboard-usability-test.md), currently NOT_EXECUTED |
| UI5 feedback iteration | issue #26 audit findings and PR review evidence |
| UI6 production version | release criteria below; no production claim until they pass |

## Visual language

- Neutral white and cool-gray surfaces support scanning; teal indicates selected/verified system state, green indicates confirmed, and amber indicates insufficient evidence or attention.
- Color is never the only signal. Every state has visible text, and uncertainty is never styled or labeled as success.
- Cards are reserved for individual panels or repeated runs. The shell, sidebar, and major workspace regions remain structural bands.
- Typography is compact: task goals carry the strongest emphasis; panel headings, labels, IDs, timestamps, and evidence references step down predictably.
- Lucide icons supplement labels and are hidden from the accessibility tree. Unfamiliar icon-only controls include accessible names and tooltips.

## Stable components

| Component | Contract |
|---|---|
| run filter | three pressed-state buttons; count updates politely |
| run list | active run exposes pressed state and scrolls into view on narrow screens |
| view tabs | one tab in the tab order; arrows cycle, Home/End jump, tab controls named panel |
| status strip | atomic polite summary; status remains text-first |
| attention banner | polite status region; missing evidence remains readable without color/icon |
| replay | named icon controls, pressed play/pause, range value text includes event position/type |
| evidence dialog | native modal semantics, named close control, synthetic source identified |

## Responsive contract

| Viewport | Layout |
|---|---|
| >1080px | fixed scanning sidebar plus two-column operational workspace |
| 781-1080px | narrower sidebar; stacked primary dashboard panels |
| <=780px | run list becomes horizontal; workspace becomes a single column |
| <=460px | compact controls, hidden redundant timestamps, stable 34px replay controls |

At 320px, 390px, 768px, and 1440px there must be no page-level horizontal overflow, incoherent overlap, clipped control label, or inaccessible active run. The run carousel may scroll horizontally by design.

## Accessibility and release criteria

- keyboard-only completion of filter, run selection, tab change, replay, evidence open/close, range, and speed tasks;
- correct tab/tabpanel, pressed, busy, live-region, dialog, and range value semantics;
- visible focus and state text in default, forced-colors, and reduced-motion modes;
- no critical/high accessibility finding in the supported dashboard path;
- usability protocol completed with retained observations and no fabricated participants;
- backend remains GET-only and write-method tests pass;
- desktop/mobile screenshots and console logs attached to the reviewed PR or release evidence.

