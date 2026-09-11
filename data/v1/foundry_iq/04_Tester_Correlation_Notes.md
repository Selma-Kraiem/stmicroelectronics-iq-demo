# Tester Correlation Notes (extract)

Document type: Engineering correlation notes
Owner: Test Engineering — Fictional demo data

Known correlations between test equipment and parametric drift on the automotive SiC MOSFET
family.

## Tester T-07
- Observed behaviour: a positive Vth bias appears in the first lots tested after a preventive
  maintenance (PM) event when anneal calibration is not re-verified.
- Related incidents: EX-2024-017, EX-2025-021.
- Standing recommendation: after any PM on T-07, run the Vth calibration check before releasing
  automotive lots.

## Tester T-04
- Observed behaviour: sensitive to ambient temperature drift on Rds(on) measurements.
- Related incidents: EX-2025-006.

## Summary
Tester T-07 is the primary equipment associated with Vth drift on this product family,
specifically in the post-PM window.
