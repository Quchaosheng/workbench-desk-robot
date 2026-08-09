# USD 5,100 procurement planning baseline

Issue 22 uses USD 5,100 as the planning BOM ceiling for one configured unit.
This is a target allocation, not a quote, purchase price, or approved MPN list.
The controlled `bom.csv` remains order-blocked until dated supplier evidence is
attached. Currency, tax, freight, tooling, NRE, spares, and tariff treatment must
be stated when real quotes replace these allocations.

| Cost group | Planning allocation (USD) |
|---|---:|
| two robot arms and controllers | 2,400 |
| compute, storage, and networking | 850 |
| cameras, safety sensors, and HMI | 550 |
| 48 V battery, BMS, charger, and power distribution | 450 |
| frame, covers, casters, fasteners, and harnesses | 500 |
| PCB assemblies, fixtures amortization, and packaging | 350 |
| **Total** | **5,100** |

Each critical line requires manufacturer, exact MPN, lifecycle status, lead time,
MOQ, warranty, country of origin, substitution policy, and two quote channels.
The buyer records the quote date and validity window. Engineering approves fit,
form, function, interfaces, and safety evidence before Procurement releases a PO.

## Certificate gate

Critical power, battery, charger, mains, radio, safety relay, E-stop, and polymer
parts require the applicable declaration, certificate, report, or material record
before ordering. URLs and sales claims are not certificates. Evidence must name
the manufacturer and exact MPN/revision and be checked against the shipped label.
Battery orders additionally require a valid UN 38.3 test summary for the pack,
not merely for a cell used inside it.

## Supplier scoring

Score quality 30%, technical capability 25%, delivery 20%, total landed cost 15%,
and compliance/continuity 10%. A supplier below 70/100, with a zero in compliance,
or with unresolved counterfeit/traceability risk is not approved regardless of
price. Selection records name the reviewer, date, evidence, exceptions, and expiry.

## Order-release checklist

- Planning total is at or below USD 5,100 or the project owner approves variance.
- Exact MPN and approved alternates are frozen against the engineering baseline.
- Critical certificates are verified before the affected PO is sent.
- Dated quotes, lead times, MOQ, payment, warranty, Incoterms, and freight are known.
- Supplier score is reproducible and conflicts of interest are disclosed.
- Incoming inspection and lot/serial traceability requirements are on the PO.
- Long-lead and single-source risks have an owner, trigger, and mitigation.

Status: `ORDER_RELEASE_BLOCKED` until real quotes, approved MPNs, certificates,
and buyer/engineering sign-off replace the planning assumptions.
