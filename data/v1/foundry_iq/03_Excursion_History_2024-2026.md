# Excursion History — SiC Automotive (2024–2026)

Document type: Historical excursion log (extract)
Owner: Quality Engineering — Fictional demo data

Record of past quality excursions on the automotive SiC MOSFET family, the equipment
involved, the root cause found, and the resolution.

## EX-2024-017
- Date: 2024-09
- Symptom: Vth shift above USL on 2 lots.
- Fab / Tester: Catania / Tester T-07.
- Root cause: gate-oxide anneal drift (+18 degC) after a preventive-maintenance mis-calibration.
- Resolution: tester re-calibration, 8D closed, affected lots scrapped, no field return.
- Remark: Tester T-07 shows a recurring Vth bias in the first lots tested after a PM event.

## EX-2025-006
- Date: 2025-03
- Symptom: Rds(on) drift (FM-02).
- Fab / Tester: Catania / Tester T-04.
- Root cause: epi doping variation from a supplier lot.
- Resolution: supplier containment, incoming spec tightened.

## EX-2025-021
- Date: 2025-11
- Symptom: gate leakage Igss high (FM-03).
- Fab / Tester: Catania / Tester T-07.
- Root cause: particle contamination in gate-oxide module.
- Resolution: chamber clean, filter replacement.

## Recurring theme
Vth excursions on this family concentrate on Tester T-07 following preventive maintenance,
pointing to a post-PM anneal-calibration weakness.
