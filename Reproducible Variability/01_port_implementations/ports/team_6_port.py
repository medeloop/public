# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_6  (v2)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-08
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new
# standalone analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist
# to Parquet under /workspace/.ostro_steps/team_6/ — never to stdout.
# HOW TO RUN: python team_6_port.py preflight | 0..12 | final. Delete the step dir first.
#
# Built from Team_6.json + Team_6.sql (CIRCE), NOT the flat parse. Team_6 shares Team_1's
# skeleton: index = FIRST-EVER cs38 fill kept iff in [D0,D1] with >=365d prior medical AND
# pharmacy coverage (single-span gate, probe-validated 2026-07-08; frac_flip 0.0007 -> keep);
# age>17 at index (Team_6 embeds it in PrimaryCriteria — implemented as step r0, identical
# result: age is checked at the first-ever fill, no fallback); and the SAME ten exclusions
# as Team_1 (DPP-4i cs8 unbounded->index; T1DM 16, CF 48, lung 43, PE 39, PH 40, thyroid 42,
# corticosteroid-conditions 45 dx+obs, pregnancy 50 dx+proc+obs, insulin 37 drug+device; all
# [-365,-1]).
#
# THE ONE DISTINCTIVE RULE (r1) — combined T2DM+CLRD at a qualifying visit:
#   ANY of {  >=2 OUTPATIENT (cs49) visits in [idx-365,idx-1]  |  >=1 INPATIENT (cs11) visit
#   in [idx-365,idx-1]  }  where EACH qualifying visit carries BOTH
#     (cs18 T2DM dx at the visit  OR  cs10 diabetes drug at the visit)   -- Group 1 (ANY)
#     AND (cs19 CLRD dx at the visit OR cs6 CLRD drug at the visit).      -- Group 2 (ANY)
#   CIRCE compiles RestrictVisit=true as "correlated event shares the anchor visit's
#   visit_occurrence_id" (Team_6.sql: "AND A.visit_occurrence_id = P.visit_occurrence_id").
#   "dx at visit" = medicalclaims_diagnosis.visit_id = v.visit_id (99.99% link, probe-validated).
#   "drug at visit" would be prescription.visit_id = v.visit_id — but HV prescription.visit_id is
#   PHARMACY-namespace (the ~1.1B 'PRESCRIPTION FILL' visits), never a cs49/cs11 medical visit.
#   PROBE 2026-07-08 returned 0 prescription fills linked to any OFFICE/CLINIC / ASC / HOSPITAL /
#   ER visit, so the cs10/cs6 drug-at-visit arms are PROVABLY EMPTY. They are OMITTED (cs6/cs10
#   dropped) — this is EXACT (identical result set) and keeps r1 under Athena's 256KB query-string
#   limit. It is also faithful to the teams' OMOP data, where NDC (pharmacy) drug_exposures carry
#   the pharmacy visit_occurrence_id, not the anchored office/inpatient VisitOccurrence, so those
#   arms are inert there too. r1 therefore = a visit with BOTH a cs18 T2DM dx AND a cs19 CLRD dx
#   at that same visit (dx-only). If HV pharmacy<->visit linkage ever changes, restore the arms.
# ICD-10 dot-stripped. Absolute date bound [2020-01-01,2025-10-31] on every criterion.
# EXPECTED LOGIC_FINGERPRINT printed on load.
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_steps/team_6"

CODESETS = {
    38: {"col":"ndc","n":172,  "sha":"a31e5fa4c7d3ba25","file":"glp_1ra__ndc__verityfoundation.json"},
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
INPAT_v  = "lower(cast(v.inpatient_ind as varchar)) IN ('y','yes','true','t','1')"   # cs11
OUTPAT_v = ("(v.location_of_care IN ('OFFICE/CLINIC','AMBULATORY SURGICAL CENTER') "  # cs49
            "OR (v.location_of_care='HOSPITAL' AND NOT (" + INPAT_v + ")))")

def h(cs): return hashlib.sha256(",".join(cs).encode()).hexdigest()[:16]
IN = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# Index = FIRST-EVER cs38 fill (no date restriction), kept iff in [D0,D1] with >=365d coverage.
IDX = f"""idx AS (
  SELECT patient_id, first_fill AS index_date FROM (
    SELECT patient_id, MIN(fill_date) AS first_fill FROM prescription WHERE ndc IN ({IN[38]}) GROUP BY patient_id
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

# --- r1 combined-visit rule: correlated dx / drug share the anchor visit's visit_id ---
def dx_at_v(cid):   # a cid diagnosis recorded at the anchor visit v
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.visit_id=v.visit_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')")
# drug-at-visit arms (cs10/cs6) omitted: PROBE 2026-07-08 -> 0 Rx fills link to medical visits
# (pharmacy visit_id is a separate namespace), so they are provably empty. r1 is dx-only.
R1_SQL = f"""WITH {IDX},
qvis AS (
  SELECT i.patient_id, v.visit_id, ({INPAT_v}) AS is_ip, ({OUTPAT_v}) AS is_op
  FROM idx i
  JOIN visit v ON v.patient_id=i.patient_id
    AND v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'
    AND v.date_start>=date_add('day',-365,i.index_date)
    AND v.date_start<=date_add('day',-1,i.index_date)
  WHERE (({INPAT_v}) OR ({OUTPAT_v}))
    AND {dx_at_v(18)}
    AND {dx_at_v(19)}
)
SELECT patient_id FROM qvis
GROUP BY patient_id
HAVING COUNT(DISTINCT CASE WHEN is_op THEN visit_id END) >= 2
    OR COUNT(DISTINCT CASE WHEN is_ip THEN visit_id END) >= 1"""

STEPS = [
 ("idx  first-EVER GLP-1RA fill (cs38) in [D0,D1] WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r0   age > 17 at index",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r1   >=2 OP(cs49) or >=1 IP(cs11) visit [-365,-1], each with cs18 T2DM dx AND cs19 CLRD dx at-visit (drug arms provably empty, omitted)",
    R1_SQL),
 ("r2   no prior DPP-4i (cs8) up to index [None,0]",       base(f"NOT {rx(8,None,0)}")),
 ("r3   no type 1 diabetes (cs16) in [-365,-1]",           base(f"NOT {dx(16,-365,-1)}")),
 ("r4   no cystic fibrosis (cs48) in [-365,-1]",           base(f"NOT {dx(48,-365,-1)}")),
 ("r5   no lung cancer (cs43) in [-365,-1]",               base(f"NOT {dx(43,-365,-1)}")),
 ("r6   no pulmonary embolism (cs39) in [-365,-1]",        base(f"NOT {dx(39,-365,-1)}")),
 ("r7   no pulmonary hypertension (cs40) in [-365,-1]",    base(f"NOT {dx(40,-365,-1)}")),
 ("r8   no thyroid carcinoma (cs42) in [-365,-1]",         base(f"NOT {dx(42,-365,-1)}")),
 ("r9   no corticosteroid-conditions (cs45 dx+obs) in [-365,-1]", base(f"NOT {dx(45,-365,-1)}")),
 ("r10  no pregnancy (cs50 dx+proc+obs) in [-365,-1]",     base(f"NOT {dx(50,-365,-1)} AND NOT {pr('50p',-365,-1)}")),
 ("r11  no insulin drugs/devices (cs37) in [-365,-1]",     base(f"NOT {rx(37,-365,-1)}")),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, SQL_MEDICAL, SQL_PHARMACY, INPAT_v, OUTPAT_v]
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
        ("visit.location_of_care (for OP arm)","SELECT location_of_care, COUNT(*) n FROM visit GROUP BY location_of_care ORDER BY n DESC"),
        ("visit.inpatient_ind","SELECT inpatient_ind, COUNT(*) n FROM visit GROUP BY inpatient_ind ORDER BY n DESC")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..12 | final")
