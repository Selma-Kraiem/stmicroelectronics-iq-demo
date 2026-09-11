# Fabric IQ — Manufacturing Data Model & Sample Data

Document type: Data dictionary + sample operational data
Domain: SiC automotive front-end / final test — Fictional demo data
Purpose: Structured representation of the live manufacturing state (lot, wafer, tester,
recipe, and final e-test results), used to trace a lot down to the deviating parameter.

## Entity types

1. Lot         — LotID, ProductRef, FabSite, ProductionWeek, Status
2. Wafer       — WaferID, LotID (FK), Position, Yield_pct, TesterID (FK), RecipeID (FK)
3. Tester      — TesterID, Location, LastPM_date
4. Recipe      — RecipeID, Step, AnnealTemp_C, OxideThickness_nm
5. ETestResult — ResultID, WaferID (FK), Parameter, Value, Unit, USL, Status

## Relationships
Lot 1—* Wafer  ·  Wafer *—1 Tester  ·  Wafer *—1 Recipe  ·  Wafer 1—* ETestResult

---

## Sample data

### Lot
| LotID          | ProductRef    | FabSite  | ProductionWeek | Status   |
|----------------|---------------|----------|----------------|----------|
| SiC-AUTO-2451  | SCTW90N65G2V  | Catania  | 2026-W22       | ON HOLD  |
| SiC-AUTO-2450  | SCTW90N65G2V  | Catania  | 2026-W21       | RELEASED |
| SiC-AUTO-2452  | SCTW90N65G2V  | Catania  | 2026-W22       | ON HOLD  |

### Tester
| TesterID | Location | LastPM_date |
|----------|----------|-------------|
| T-07     | Catania  | 2026-05-25  |
| T-04     | Catania  | 2026-04-10  |

### Recipe
| RecipeID | Step        | AnnealTemp_C | OxideThickness_nm |
|----------|-------------|--------------|-------------------|
| R-GOX-12 | Gate-oxide  | 1194         | 50                |
| R-GOX-11 | Gate-oxide  | 1176         | 50                |

### Wafer (lot SiC-AUTO-2451)
| WaferID     | LotID          | Position | Yield_pct | TesterID | RecipeID |
|-------------|----------------|----------|-----------|----------|----------|
| W-2451-03   | SiC-AUTO-2451  | 3        | 71.2      | T-07     | R-GOX-12 |
| W-2451-07   | SiC-AUTO-2451  | 7        | 68.5      | T-07     | R-GOX-12 |
| W-2451-12   | SiC-AUTO-2451  | 12       | 90.1      | T-07     | R-GOX-11 |

### ETestResult
| ResultID | WaferID   | Parameter | Value | Unit | USL  | Status |
|----------|-----------|-----------|-------|------|------|--------|
| E-0001   | W-2451-03 | Vth       | 4.10  | V    | 3.80 | FAIL   |
| E-0002   | W-2451-07 | Vth       | 4.02  | V    | 3.80 | FAIL   |
| E-0003   | W-2451-12 | Vth       | 3.55  | V    | 3.80 | PASS   |
| E-0004   | W-2451-03 | Rds_on    | 78    | mOhm | 90   | PASS   |

## Notes on the sample state
- Lot SiC-AUTO-2451 was produced in week 2026-W22 and tested on Tester T-07 with recipe R-GOX-12.
- Recipe R-GOX-12 anneal temperature is 1194 degC (above the 1190 degC process upper limit).
- Two of three sampled wafers fail Vth (4.10 / 4.02 V vs 3.80 V USL).
- Tester T-07 was last preventively maintained on 2026-05-25; this lot is the first automotive
  lot processed after that PM.
