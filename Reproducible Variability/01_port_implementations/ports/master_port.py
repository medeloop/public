# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: MASTER  (v2b, review-fixed)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-06
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets
# persist to Parquet under /workspace/.ostro_master_steps/ — never to stdout.
#
# HOW TO RUN (one shell invocation each): python master_port.py preflight | 0..12 | final.
# For a clean re-derivation, delete /workspace/.ostro_master_steps first, then run 0..12.
#
# FIXES vs v2a (per adversarial review, faithful to Master OMOP JSON/CIRCE SQL):
#  - D#1: index is now the earliest in-window GLP-1RA fill that ITSELF has >=365d prior
#    medical AND pharmacy coverage (CIRCE applies "First" after the observation filter,
#    with fallback to a later qualifying fill). The separate obs step is folded into idx.
#  - D#2: criteria event dates are bounded to the mapped absolute window [2020-01-01,
#    2025-10-31] (matches OccurrenceStartDate; caps the pregnancy +180 forward window).
# Rule 4 (3 arms) and Rule 11 (days_supply) unchanged (were correct). ICD-10 dot-stripped.
# EXPECTED LOGIC_FINGERPRINT printed on load.
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"          # index-eligibility window
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"   # mapped absolute bound on criteria event dates
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_master_steps"

CODESETS = {
    4:  {"col":"ndc","n":163,  "sha":"e2b0ae8663f4f02a","file":"glp_1ra_without_insulin__ndc__verityfoundation.json"},
    6:  {"col":"ndc","n":12025,"sha":"9d157567109e0859","file":"drugs_for_clrd__ndc__verityfoundation.json"},
    8:  {"col":"ndc","n":437,  "sha":"d7773387a9d5a6e6","file":"dpp_4i__ndc__verityfoundation.json"},
    10: {"col":"ndc","n":8170, "sha":"f67b4b0aa4b59bec","file":"drugs_for_diabetes__ndc__verityfoundation.json"},
    16: {"col":"diagnosis_code","n":124, "sha":"a9e2f7016a884a9a","file":"type_1_diabetes_mellitus__diagnosis_code__verityfoundation.json"},
    18: {"col":"diagnosis_code","n":238, "sha":"9a2392ddbdb32de6","file":"type_2_diabetes_mellitus__diagnosis_code__verityfoundation.json"},
    19: {"col":"diagnosis_code","n":48,  "sha":"46ab61bc072b5e9a","file":"chronic_lower_respiratory_disease_clrd__diagnosis_code__verityfoundation.json"},
    37: {"col":"ndc","n":1142, "sha":"04f8a0f0e2f9397c","file":"insulin_drugs_and_devices__ndc__verityfoundation.json"},
    39: {"col":"diagnosis_code","n":13,  "sha":"c09283295125bc0c","file":"pulmonary_embolism__diagnosis_code__verityfoundation.json"},
    40: {"col":"diagnosis_code","n":12,  "sha":"b6e5e8f0e2d099c5","file":"pulmonary_hypertension__diagnosis_code__verityfoundation.json"},
    42: {"col":"diagnosis_code","n":1,   "sha":"27157acafbaa3714","file":"thyroid_carcinoma__diagnosis_code__verityfoundation.json"},
    43: {"col":"diagnosis_code","n":35,  "sha":"faa66a492c7fad54","file":"lung_cancer__diagnosis_code__verityfoundation.json"},
    45: {"col":"diagnosis_code","n":1219,"sha":"4124a5d0a418bf64","file":"conditions_that_frequently_require_chronic_systematic_corticosteroids__diagnosis_code__verityfoundation.json"},
    48: {"col":"diagnosis_code","n":6,   "sha":"dc7421ecb6bd58ec","file":"cystic_fibrosis__diagnosis_code__verityfoundation.json"},
    50: {"col":"diagnosis_code","n":3434,"sha":"90a5ef8949e39494","file":"pregnancy_conditions_procedures_and_observations__diagnosis_code__verityfoundation.json"},
}

SQL_MEDICAL   = "lower(benefit_type) LIKE '%medical%'"
SQL_PHARMACY  = "(lower(benefit_type) LIKE '%pharm%' OR lower(benefit_type) LIKE '%rx%')"
SQL_FEMALE    = "upper(coalesce(gender,'')) IN ('F','FEMALE')"
SQL_INPATIENT = "lower(cast(inpatient_ind as varchar)) IN ('y','yes','true','t','1')"

def h(cs): return hashlib.sha256(",".join(cs).encode()).hexdigest()[:16]
IN = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# Index = earliest cs4 fill in [D0,D1] that ITSELF has >=365d prior medical AND pharmacy
# coverage (single span per benefit). Fallback to a later qualifying fill is automatic (MIN
# over qualifying fills). This mirrors CIRCE "First after observation qualification".
IDX = f"""idx AS (
  SELECT patient_id, MIN(fill_date) AS index_date FROM (
    SELECT x.patient_id, x.fill_date
      FROM prescription x
     WHERE x.ndc IN ({IN[4]}) AND x.fill_date BETWEEN DATE '{D0}' AND DATE '{D1}'
       AND EXISTS (SELECT 1 FROM enrollment m WHERE m.patient_id=x.patient_id AND {SQL_MEDICAL}
                   AND m.date_start<=date_add('day',-365,x.fill_date) AND m.date_end>=x.fill_date)
       AND EXISTS (SELECT 1 FROM enrollment r WHERE r.patient_id=x.patient_id AND {SQL_PHARMACY}
                   AND r.date_start<=date_add('day',-365,x.fill_date) AND r.date_end>=x.fill_date)
  ) q GROUP BY patient_id)"""

def _w(col, lo, hi):
    c = []
    if lo is not None: c.append(f"{col}>=date_add('day',{lo},i.index_date)")
    if hi is not None: c.append(f"{col}<=date_add('day',{hi},i.index_date)")
    return (" AND " + " AND ".join(c)) if c else ""
def dx(cid, lo, hi):
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)})")
def rx(cid, lo, hi):
    return (f"EXISTS (SELECT 1 FROM prescription e WHERE e.patient_id=i.patient_id "
            f"AND e.ndc IN ({IN[cid]}) "
            f"AND e.fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('e.fill_date',lo,hi)})")
def base(cond, join=""):
    return f"WITH {IDX} SELECT i.patient_id FROM idx i {join} WHERE {cond}"

# Rule 4 (CLRD): ANY of 3 arms, window [-365,0], all abs-bounded.
_absd = f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'"
armA = (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d JOIN visit v ON v.visit_id=d.visit_id "
        f"WHERE d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[19]}) {_absd} "
        f"AND d.date_start>=date_add('day',-365,i.index_date) AND d.date_start<=i.index_date AND {SQL_INPATIENT})")
armB = (f"(SELECT COUNT(DISTINCT d.date_start) FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
        f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[19]}) {_absd} "
        f"AND d.date_start>=date_add('day',-365,i.index_date) AND d.date_start<=i.index_date) >= 2")
armC = f"({dx(19,-365,0)} AND {rx(6,-365,0)})"

STEPS = [
 ("idx  first in-window GLP-1RA fill (cs4) WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r0   no GLP1 (cs4) in [-365,-1]",            base(f"NOT {rx(4,-365,-1)}")),
 ("r1   age > 17",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r2   no type 1 diabetes (cs16) in [-365,-1]",base(f"NOT {dx(16,-365,-1)}")),
 ("r3   has type 2 diabetes (cs18) in [-365,0]",base(dx(18,-365,0))),
 ("r4   CLRD (cs19): inpatient dx OR >=2 distinct-day dx OR (dx AND cs6 drug), [-365,0]",
    base(f"({armA} OR {armB} OR {armC})")),
 ("r5   no CF/lung-ca/PE/PH (cs48,43,39,40) in [-365,-1]",
    base(f"NOT EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
         f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[48]},{IN[43]},{IN[39]},{IN[40]}) {_absd} "
         "AND d.date_start>=date_add('day',-365,i.index_date) AND d.date_start<=date_add('day',-1,i.index_date))")),
 ("r6   no thyroid carcinoma (cs42) in [-365,-1]", base(f"NOT {dx(42,-365,-1)}")),
 ("r7   no corticosteroid-conditions (cs45) in [-365,-1]", base(f"NOT {dx(45,-365,-1)}")),
 ("r8   no pregnancy (cs50 dx) in [-180,180] for females",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i LEFT JOIN patient p ON p.patient_id=i.patient_id "
    f"WHERE NOT ({SQL_FEMALE} AND {dx(50,-180,180)})"),
 ("r9   no DPP-4i (cs8) in [-365,0]",           base(f"NOT {rx(8,-365,0)}")),
 ("r10  no insulin drugs/devices (cs37) in [-365,-1]", base(f"NOT {rx(37,-365,-1)}")),
 ("r11  active other-diabetes drug (cs10): fill<index AND fill+days_supply-1>=index",
    base(f"EXISTS (SELECT 1 FROM prescription e WHERE e.patient_id=i.patient_id "
         f"AND e.ndc IN ({IN[10]}) AND e.fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' "
         "AND e.fill_date<=date_add('day',-1,i.index_date) "
         "AND date_add('day', coalesce(TRY_CAST(e.days_supply AS integer),0)-1, e.fill_date) >= i.index_date)")),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, SQL_MEDICAL, SQL_PHARMACY, SQL_FEMALE, SQL_INPATIENT]
                  + [f"{c}:{CODESETS[c]['sha']}" for c in sorted(CODESETS)]
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
        print(f"  {name.split()[0]:5} pass={len(s):>9,}  step_sha={hashlib.sha256(','.join(sorted(s)).encode()).hexdigest()[:16]}  cohort={len(cohort):>9,}   {name}")
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
        ("patient.gender","SELECT gender, COUNT(*) n FROM patient GROUP BY gender ORDER BY n DESC"),
        ("visit.inpatient_ind","SELECT inpatient_ind, COUNT(*) n FROM visit GROUP BY inpatient_ind ORDER BY n DESC")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..12 | final")
