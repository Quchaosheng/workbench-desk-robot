# Procurement engineering package

This package turns the PCB, mechanical, and manufacturing design inputs into a
controlled purchasing workflow. It is intentionally honest about what is and is
not known: rows marked `QUOTE_REQUIRED`, `AVL_REQUIRED`, or `NOT_RELEASED` are
not purchase claims. A buyer can use the quote register and PO checklist to
close those gates without changing the engineering baseline.

## Files

- `bom.csv`: controlled line-item BOM with quantity, candidate, source, owner,
  and release status.
- `quote-register.csv`: two or more quote-request channels for each critical
  item; supplier prices remain blank until a quote is received.
- `supplier-scorecard.csv`: repeatable quality/lead-time/cost/technical review.
- `cost-and-leadtime.md`: calculation rules and decision gates.
- `po-checklist.csv`: order-release checks and required evidence.
- `inventory-policy.md`: receiving, quarantine, traceability, and spares rules.

Run `python hardware/procurement/tools/validate_procurement.py` to regenerate
the deterministic report under `generated/`.
