# FMEA — SiC MOSFET (Automotive) — SCTW90N65G2V

Document type: Failure Mode and Effects Analysis (extract)
Product family: 650 V / 900 V SiC Power MOSFET, automotive grade (AEC-Q101)
Owner: Quality & Reliability Engineering
Revision: 3.2 — Fictional demo data

## Scope
This FMEA extract lists the dominant failure modes observed on automotive SiC MOSFETs used
in EV traction inverters and on-board chargers (OBC), with likely causes, detection method,
and severity ranking.

## Failure modes

### FM-01 — Threshold voltage shift (Vth drift)
- Symptom: Vth measured at final e-test drifts above the upper spec limit (USL).
- Typical cause: gate-oxide process deviation (anneal temperature or oxide thickness out of window).
- Severity (S): 8 / 10 — can degrade switching behaviour and long-term reliability in traction use.
- Detection: parametric final test (Vth), gate-stress reliability screen.
- Remarks: historically the leading contributor to automotive excursions on this family.

### FM-02 — On-resistance drift (Rds(on) increase)
- Symptom: Rds(on) above USL, higher conduction losses.
- Typical cause: epitaxial layer thickness/doping variation, contact resistance.
- Severity (S): 6 / 10 — thermal derating impact in high-current inverters.
- Detection: parametric final test (Rds(on)).

### FM-03 — Gate-oxide integrity / early gate leakage
- Symptom: elevated gate leakage (Igss), potential infant mortality.
- Typical cause: gate-oxide defect density, particle contamination, anneal deviation.
- Severity (S): 8 / 10 — safety-relevant for traction inverters.
- Detection: Igss screen, burn-in.

### FM-04 — Body-diode / third-quadrant degradation
- Symptom: increased forward voltage after stress.
- Typical cause: basal plane dislocations in SiC substrate.
- Severity (S): 5 / 10.
- Detection: reliability stress + Vsd measurement.

## Cross-reference
A Vth shift above USL on an automotive lot is associated with FM-01 (gate-oxide process
deviation) and should be correlated with the gate-oxide process window (see Process
Specification) and the production equipment used.
