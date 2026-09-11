# Quality Incident Response Playbook — Automotive SiC (8D / Containment)

Document type: Standard operating procedure (playbook)
Owner: Quality & Operations
Location: SharePoint > Quality Ops > Quality_Ops_Handbook
Revision: 5.0 — Fictional demo data

## 1. Purpose
Standard steps followed when a parametric excursion is detected on an automotive SiC lot,
from containment to customer notification and CAPA.

## 2. Roles
- Quality Engineer (incident owner)
- Fab Process Engineer (root cause)
- Customer Quality Manager (notification)
- Operations (containment / logistics)

## 3. 8D response steps

### D1 — Form the team
Assemble Quality, Process and Customer Quality for any Tier-1 impacting excursion.

### D2 — Describe the problem
Record lot, product, parameter, measured value vs spec limit, tester, and recipe.

### D3 — Containment (immediate)
1. Place the affected lot and adjacent lots (same production week / tester) ON HOLD.
2. Block all inventory still on hand (warehouse and, where possible, in-transit).
3. Quantify field exposure: units already shipped, by customer and application.
4. For safety-critical end use (EV traction), escalate immediately.

### D4 — Root cause
Trace lot -> wafer -> tester -> recipe -> deviating parameter. Confirm against the process
specification window and the equipment/tester correlation history.

### D5 — Corrective actions
Re-calibrate the implicated tester, re-verify the recipe window, and re-test held lots.

### D6 — Validate
Confirm re-tested lots are within spec before release.

### D7 — Prevent recurrence
Add a mandatory post-PM Vth calibration check for the implicated tester.

### D8 — Close and notify
Notify impacted customers per AEC-Q101 guidance, record the disposition in the CAPA system,
and communicate the summary to the Quality team channel.

## 4. Impacted-scope reference
| Information                    | System of record                          |
|--------------------------------|-------------------------------------------|
| Units in field / blockable     | Shipments & Inventory workbook            |
| Root cause / tester / recipe   | Manufacturing data model (Fabric)         |
| Failure mode / spec window     | FMEA & Process specification              |
| Response steps                 | This playbook                             |

## 5. Customer notification template
"Automotive SiC quality notice — Lot {LotID}. Containment status: {status}.
Probable root cause: {root cause}. Field exposure: {units, customers}.
Recommended actions: {containment steps}."
