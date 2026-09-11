# Process Specification — SiC Gate-Oxide Module (extract)

Document type: Process specification (extract)
Process step: Gate-oxide growth & post-oxidation anneal
Product family: Automotive SiC MOSFET (SCTW90N65G2V)
Document ID: PS-GOX-SiC-012 — Fictional demo data

## Controlled parameters and windows

| Parameter                     | Target | Lower limit | Upper limit | Unit |
|-------------------------------|--------|-------------|-------------|------|
| Post-oxidation anneal temp    | 1175   | 1160        | 1190        | degC |
| Gate-oxide thickness          | 50     | 47          | 53          | nm   |
| Anneal time                   | 120    | 110         | 130         | min  |
| Vth (final e-test)            | 3.2    | 2.6         | 3.8         | V    |
| Igss (gate leakage)           | -      | -           | 100         | nA   |

## Control rules
- An anneal temperature above the upper limit (1190 degC) is associated with a positive
  Vth shift (see FMEA FM-01).
- A Vth reading above the 3.8 V upper spec limit on an automotive lot is a containment
  trigger under the site quality procedure.
- Any parameter excursion is traceable to the tester and recipe that produced the lot
  through the manufacturing execution records.

## Related documents
- FMEA — SiC MOSFET (Automotive)
- Site Quality Incident / 8D Playbook
