# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_8  (v2)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-12
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new standalone
# analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist to
# Parquet under /workspace/.ostro_steps/team_8/ — never to stdout.
# HOW TO RUN: python team_8_port.py preflight | 0..10 | final. Delete the step dir first.
#
# Built from Team_8.json + Team_8.sql (CIRCE). Simplest team: all-diagnosis/drug rules, NO visit
# correlation, NO drug-era, NO per-ingredient partition. AdditionalCriteria carries NO event criteria
# but DOES carry a DemographicCriteriaList (age > 17) — reproduced as step r_ag (Team_8.sql:393).
# INDEX = PrimaryCriteria DrugExposure cs4 (GLP-1RA-without-insulin), PrimaryCriteriaLimit First
#   (first-ever, no fallback), OccurrenceStartDate 2006-2017, ObservationWindow prior 365 =>
#   FIRST-EVER cs4 fill in [D0,D1] with >=365d prior medical AND pharmacy coverage.
#   age > 17 at index as step r_ag — compiled CIRCE: YEAR(index)-year_of_birth > 17 (Team_8.sql:393).
#
# RULE MAP (SQL-anchored). All windows are INDEX-INCLUSIVE [-N,+0] (hi=0):
#  * r0 "At least one IP or two OP encounters for T2DM": coded as plain ConditionOccurrence cs18
#    Occ>=1 in [-365,0] — NO visit correlation despite the rule NAME (faithful: reproduce as coded).
#  * r1 "prior CLRD": plain ConditionOccurrence cs19 Occ>=1 in [-365,0] (again, no visit logic).
#  * r2 "No prior T1D": NOT cs16 [-365,0].
#  * r3 "No CF/lung cancer/PE/PH": NOT cs48 AND NOT cs43 AND NOT cs39 AND NOT cs40, each [-365,0].
#  * r4 "No pregnancy at index": NOT cs50 dx+proc+obs in [-30,0] (30-day pre-index window).
#  * r5 "No thyroid carcinoma": NOT cs42 [-365,0].
#  * r6 "No corticosteroid-requiring conditions": NOT cs45 [-365,0].
#  * r7 "No prior DPP-4i": NOT cs8 DrugExposure [-365,0].
#  * r8 "No prior insulin": NOT cs37 DeviceExposure [-365,0] AND NOT cs37 DrugExposure [-356,0].
#    ***HUMAN TYPO reproduced***: the DrugExposure window is -356 (not -365); the DeviceExposure
#    window is -365. In claims, cs37 drug+device both map to `prescription` (no drug/device split),
#    so the two arms collapse to their UNION window = [-365,0] (the device arm's -365 is wider and
#    subsumes the drug arm's -356). Net faithful effect: NOT any cs37 fill in [-365,0]. The -356 typo
#    is immaterial here because [-356,0] is a strict subset of [-365,0].
# CensoringCriteria (1) is cohort-EXIT (follow-up), out of scope for a membership port.
# ICD-10 dot-stripped. Absolute date bound [2020-01-01,2025-10-31] on every criterion.
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_steps/team_8"

CODESETS = {
    4:  {"col":"ndc","n":163,  "sha":"e2b0ae8663f4f02a","file":"glp_1ra_without_insulin__ndc__verityfoundation.json"},
    8:  {"col":"ndc","n":437,  "sha":"d7773387a9d5a6e6","file":"dpp_4i__ndc__verityfoundation.json"},
    37: {"col":"ndc","n":1142, "sha":"04f8a0f0e2f9397c","file":"insulin_drugs_and_devices__ndc__verityfoundation.json"},
    18: {"col":"diagnosis_code","n":238, "sha":"9a2392ddbdb32de6","file":"type_2_diabetes_mellitus__diagnosis_code__verityfoundation.json"},
    19: {"col":"diagnosis_code","n":48,  "sha":"46ab61bc072b5e9a","file":"chronic_lower_respiratory_disease_clrd__diagnosis_code__verityfoundation.json"},
    16: {"col":"diagnosis_code","n":124, "sha":"a9e2f7016a884a9a","file":"type_1_diabetes_mellitus__diagnosis_code__verityfoundation.json"},
    48: {"col":"diagnosis_code","n":6,   "sha":"dc7421ecb6bd58ec","file":"cystic_fibrosis__diagnosis_code__verityfoundation.json"},
    43: {"col":"diagnosis_code","n":35,  "sha":"faa66a492c7fad54","file":"lung_cancer__diagnosis_code__verityfoundation.json"},
    39: {"col":"diagnosis_code","n":13,  "sha":"c09283295125bc0c","file":"pulmonary_embolism__diagnosis_code__verityfoundation.json"},
    40: {"col":"diagnosis_code","n":12,  "sha":"b6e5e8f0e2d099c5","file":"pulmonary_hypertension__diagnosis_code__verityfoundation.json"},
    42: {"col":"diagnosis_code","n":1,   "sha":"27157acafbaa3714","file":"thyroid_carcinoma__diagnosis_code__verityfoundation.json"},
    45: {"col":"diagnosis_code","n":1219,"sha":"4124a5d0a418bf64","file":"conditions_that_frequently_require_chronic_systematic_corticosteroids__diagnosis_code__verityfoundation.json"},
    50: {"col":"diagnosis_code","n":3434,"sha":"90a5ef8949e39494","file":"pregnancy_conditions_procedures_and_observations__diagnosis_code__verityfoundation.json"},
    "50p": {"col":"procedure_code","n":42,"sha":"b2fe8c1bbd144be5","file":"pregnancy_conditions_procedures_and_observations__procedure_code__verityfoundation.json"},
}

SQL_MEDICAL  = "lower(benefit_type) LIKE '%medical%'"
SQL_PHARMACY = "(lower(benefit_type) LIKE '%pharm%' OR lower(benefit_type) LIKE '%rx%')"

def h(cs): return hashlib.sha256(",".join(cs).encode()).hexdigest()[:16]
IN = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# Index = FIRST-EVER cs4 fill (= first drug-era start), kept iff in [D0,D1] with >=365d coverage.
IDX = f"""idx AS (
  SELECT patient_id, first_fill AS index_date FROM (
    SELECT patient_id, MIN(fill_date) AS first_fill FROM prescription WHERE ndc IN ({IN[4]}) GROUP BY patient_id
  ) f
  WHERE f.first_fill BETWEEN DATE '{D0}' AND DATE '{D1}'
    AND EXISTS (SELECT 1 FROM enrollment m WHERE m.patient_id=f.patient_id AND {SQL_MEDICAL}
                AND m.date_start<=date_add('day',-365,f.first_fill) AND m.date_end>=f.first_fill)
    AND EXISTS (SELECT 1 FROM enrollment r WHERE r.patient_id=f.patient_id AND {SQL_PHARMACY}
                AND r.date_start<=date_add('day',-365,f.first_fill) AND r.date_end>=f.first_fill))"""

def _w(col, lo, hi):
    c = []
    if lo is not None: c.append(f"{col}>=date_add('day',{lo},i.index_date)")
    if hi is not None: c.append(f"{col}<=date_add('day',{hi},i.index_date)")
    return (" AND " + " AND ".join(c)) if c else ""
def dx(cid, lo, hi):   # ConditionOccurrence / Observation -> diagnosis
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)})")
def rx(cid, lo, hi):   # DrugExposure / DeviceExposure -> prescription
    return (f"EXISTS (SELECT 1 FROM prescription e WHERE e.patient_id=i.patient_id "
            f"AND e.ndc IN ({IN[cid]}) "
            f"AND e.fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('e.fill_date',lo,hi)})")
def pr(cid, lo, hi):   # ProcedureOccurrence -> procedure
    return (f"EXISTS (SELECT 1 FROM medicalclaims_procedure pc WHERE pc.patient_id=i.patient_id "
            f"AND pc.procedure_code IN ({IN[cid]}) "
            f"AND pc.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('pc.date_start',lo,hi)})")
def base(cond):
    return f"WITH {IDX} SELECT i.patient_id FROM idx i WHERE {cond}"

STEPS = [
 ("idx  first-EVER GLP-1RA-w/o-insulin fill (cs4) in [D0,D1] WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r_ag age > 17 at index (AdditionalCriteria.DemographicCriteriaList; Team_8.sql:393)",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r0   T2DM: >=1 cs18 dx in [-365,0] (rule name says IP/OP encounters; coded as plain dx>=1)",
    base(f"{dx(18,-365,0)}")),
 ("r1   CLRD: >=1 cs19 dx in [-365,0] (coded as plain dx>=1)",
    base(f"{dx(19,-365,0)}")),
 ("r2   no prior type 1 diabetes (cs16) in [-365,0]",  base(f"NOT {dx(16,-365,0)}")),
 ("r3   no CF(48)/lung(43)/PE(39)/PH(40) in [-365,0]",
    base(f"NOT {dx(48,-365,0)} AND NOT {dx(43,-365,0)} AND NOT {dx(39,-365,0)} AND NOT {dx(40,-365,0)}")),
 ("r4   no pregnancy (cs50 dx+proc+obs) in [-30,0]",
    base(f"NOT {dx(50,-30,0)} AND NOT {pr('50p',-30,0)}")),
 ("r5   no thyroid carcinoma (cs42) in [-365,0]",  base(f"NOT {dx(42,-365,0)}")),
 ("r6   no corticosteroid-requiring conditions (cs45) in [-365,0]",  base(f"NOT {dx(45,-365,0)}")),
 ("r7   no prior DPP-4i (cs8) in [-365,0]",  base(f"NOT {rx(8,-365,0)}")),
 ("r8   no prior insulin (cs37) in [-365,0] (device -365 UNION drug -356 typo => [-365,0])",
    base(f"NOT {rx(37,-365,0)}")),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, SQL_MEDICAL, SQL_PHARMACY]
                  + [f"{c}:{CODESETS[c]['sha']}" for c in sorted(CODESETS, key=str)]
                  + [f"{name}:::{sql}" for name, sql in STEPS])
LOGIC_FINGERPRINT = hashlib.sha256(fp_src.encode()).hexdigest()[:16]

def _conn():
    return connect(work_group=os.environ["ATHENA_WORKGROUP"], schema_name=DATASET,
                   s3_staging_dir=os.environ["ATHENA_S3_STAGING_DIR"])
def _sf(i): return f"{OUT_DIR}/step_{i:02d}.parquet"

def run_step(i):
    os.makedirs(OUT_DIR, exist_ok=True)
    name, sql = STEPS[i]
    print(f"[step {i}] {name}\n  LOGIC_FINGERPRINT={LOGIC_FINGERPRINT}")
    t0 = time.time()
    ids = sorted(set(pd.read_sql(sql, _conn())["patient_id"].astype(str)))
    pd.DataFrame({"patient_id": ids}).to_parquet(_sf(i), index=False)
    print(f"  pass={len(ids):,}  step_sha={hashlib.sha256(','.join(ids).encode()).hexdigest()[:16]}"
          f"  elapsed={time.time()-t0:.0f}s -> {_sf(i)}")

def finalize():
    print("LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT, "\n=== attrition ===")
    cohort = None
    for i, (name, _) in enumerate(STEPS):
        s = set(pd.read_parquet(_sf(i))["patient_id"].astype(str))
        cohort = s if cohort is None else (cohort & s)
        print(f"  {name.split()[0]:5} pass={len(s):>9,}  step_sha={hashlib.sha256(','.join(sorted(s)).encode()).hexdigest()[:16]}  cohort={len(cohort):>9,}")
    final = sorted(cohort)
    print("\n=== RESULT ===")
    print("FINAL_COUNT :", len(final))
    print("COHORT_HASH :", hashlib.sha256(",".join(final).encode()).hexdigest())
    print("LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)

def preflight():
    print("LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT, "\n=== preflight token values ===")
    c = _conn()
    for label, sql in [
        ("enrollment.benefit_type","SELECT benefit_type, COUNT(*) n FROM enrollment GROUP BY benefit_type ORDER BY n DESC"),
        ("prescription cs37/cs8 presence","SELECT COUNT(*) n_rx FROM prescription WHERE ndc IN (" + IN[8] + ")")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..10 | final")
