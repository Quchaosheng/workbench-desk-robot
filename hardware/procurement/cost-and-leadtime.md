# Cost and lead-time model

No supplier quotation is present in the repository. The model therefore keeps
price and lead time blank and reports `QUOTE_REQUIRED`; filling a number here
without a dated quote would create a false commercial commitment.

For each line item:

`extended_cost = quantity * quoted_unit_price`

`planning_total = sum(extended_cost) + freight + tax + 10% contingency`

Use the longest confirmed lead time on the critical path, then add incoming
inspection and quarantine time. A part cannot become `ORDERABLE` until the AVL
owner signs the candidate MPN, the quote has a validity date, and incoming
acceptance evidence is defined.

The current PCB component matrix deliberately uses component classes rather than
orderable MPNs. Procurement must close that gap with the electrical owner before
issuing a PO.
