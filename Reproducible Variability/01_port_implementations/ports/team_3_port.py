# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_3  (v2, DrugEra add-on)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-09
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new standalone
# analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist to
# Parquet under /workspace/.ostro_steps/team_3/ — never to stdout.
# HOW TO RUN: python team_3_port.py preflight | 0..7 | final. Delete the step dir first.
#
# Built from Team_3.json + Team_3.sql (CIRCE).
# INDEX = PrimaryCriteria DrugExposure cs4 (GLP-1RA-without-insulin), PrimaryCriteriaLimit First
#   (ordinal=1, no fallback), OccurrenceStartDate 2006-2017, ObservationWindow 365. = FIRST-EVER cs4
#   fill in [D0,D1] with >=365d prior medical AND pharmacy coverage. age>17 as step r_ag (rule 1).
#
# RULE MAP (SQL-anchored):
#  * r0 "not exposed to DPP-4i": NOT cs8 DrugExposure in (-inf, idx].
#  * r2 T2D / r3 CLRD (Type ANY, 4 arms each): a cs11 INPATIENT visit (start in [-365,idx]) with a
#    cs18/cs19 dx OR cs10/cs6 drug whose date falls WITHIN THE VISIT SPAN [visit.date_start,
#    visit.date_end] (date-containment on the event START; Team_3.sql:565 — UseEventEnd=False, so no
#    drug-era-end condition); OR >=2 cs49 OUTPATIENT visits (start in [-365,idx]) each with such a
#    contained dx / drug. Four UNION arms: IP-dx, IP-drug, >=2 OP-dx, >=2 OP-drug. Big drug list
#    (cs10/cs6) is CTE'd ONCE for the query-size limit.
#  * r4 "addon to antidiabetic agents": >=1 METFORMIN (cs41) DRUG ERA with era_start in [-365,idx].
#    cs41 is a single ingredient (metformin), so a merge-all gaps-and-islands era (30-day OMOP gap)
#    equals the metformin ingredient era — no per-ingredient partition needed.
#  * r5 "No type 1 diabetes": NOT insulin (cs37 drug+device -> prescription) AND NOT T1D (cs16),
#    both [-365,-1]. (Rule bundles insulin exclusion under the T1D name.)
#  * r6 "No excluded other medical conditions" (all [-365,-1], NOT EXISTS): CF48, lung43, PE39,
#    PH40, pregnancy cs50 dx+proc+obs, thyroid42, corticosteroid-conditions cs45.
# ICD-10 dot-stripped. Absolute date bound [2020-01-01,2025-10-31] on every criterion.
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"
GAP = 30
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_steps/team_3"

CODESETS = {
    4:  {"col":"ndc","n":163,  "sha":"e2b0ae8663f4f02a","file":"glp_1ra_without_insulin__ndc__verityfoundation.json"},
    6:  {"col":"ndc","n":12025,"sha":"9d157567109e0859","file":"drugs_for_clrd__ndc__verityfoundation.json"},
    10: {"col":"ndc","n":8170, "sha":"f67b4b0aa4b59bec","file":"drugs_for_diabetes__ndc__verityfoundation.json"},
    41: {"col":"ndc","n":3930, "sha":"fabaaee5fa2cb139","file":"metformin__ndc__verityfoundation.json"},
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

# --- r2/r3: visit (start in [-365,idx]) with a dx/drug whose date is CONTAINED in the visit span.
#     4 UNION arms: IP-dx, IP-drug, >=2 OP-dx, >=2 OP-drug. Big drug list CTE'd once. ---
def t2d_clrd_sql(dxcid, rxcid):
    df = f"drugf{rxcid}"
    VW = "v.date_start>=date_add('day',-365,i.index_date) AND v.date_start<=i.index_date"
    def dxjoin(vset):
        return (f"SELECT i.patient_id, v.visit_id FROM idx i "
                f"JOIN visit v ON v.patient_id=i.patient_id AND ({vset}) "
                f"AND v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND {VW} "
                f"JOIN medicalclaims_diagnosis d ON d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' "
                f"AND d.diagnosis_code IN ({IN[dxcid]}) AND d.date_start BETWEEN v.date_start AND v.date_end")
    def rxjoin(vset):
        return (f"SELECT i.patient_id, v.visit_id FROM idx i "
                f"JOIN visit v ON v.patient_id=i.patient_id AND ({vset}) "
                f"AND v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND {VW} "
                f"JOIN {df} e ON e.patient_id=i.patient_id AND e.fill_date BETWEEN v.date_start AND v.date_end")
    return ("WITH " + ",\n".join([IDX,
        f"{df} AS (SELECT patient_id, fill_date FROM prescription WHERE ndc IN ({IN[rxcid]}) "
        f"AND patient_id IN (SELECT patient_id FROM idx) AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')"]) + "\n"
      f"SELECT patient_id FROM ({dxjoin(INPAT_v)})\n"
      "UNION\n"
      f"SELECT patient_id FROM ({rxjoin(INPAT_v)})\n"
      "UNION\n"
      f"SELECT patient_id FROM (SELECT patient_id, COUNT(DISTINCT visit_id) c FROM ({dxjoin(OUTPAT_v)}) GROUP BY patient_id) WHERE c>=2\n"
      "UNION\n"
      f"SELECT patient_id FROM (SELECT patient_id, COUNT(DISTINCT visit_id) c FROM ({rxjoin(OUTPAT_v)}) GROUP BY patient_id) WHERE c>=2")

# --- r4: merge-all metformin (cs41, single ingredient) drug eras; >=1 era_start in [-365,idx] ---
def drug_era_ctes(prefix, cid):
    return [
      f"{prefix}_f AS (SELECT patient_id, fill_date AS s, date_add('day', COALESCE(TRY_CAST(days_supply AS integer),1), fill_date) AS e "
      f"FROM prescription WHERE ndc IN ({IN[cid]}) AND patient_id IN (SELECT patient_id FROM idx) "
      f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')",
      f"{prefix}_m AS (SELECT patient_id, s, e, MAX(e) OVER (PARTITION BY patient_id ORDER BY s,e ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM {prefix}_f)",
      f"{prefix}_i AS (SELECT patient_id, s, e, CASE WHEN pme IS NULL THEN 1 WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM {prefix}_m)",
      f"{prefix}_g AS (SELECT patient_id, s, e, SUM(ne) OVER (PARTITION BY patient_id ORDER BY s,e) AS era FROM {prefix}_i)",
      f"{prefix} AS (SELECT patient_id, MIN(s) AS era_start FROM {prefix}_g GROUP BY patient_id, era)",
    ]
R4_SQL = ("WITH " + ",\n".join([IDX] + drug_era_ctes("me41", 41)) +
          "\nSELECT i.patient_id FROM idx i WHERE EXISTS (SELECT 1 FROM me41 z WHERE z.patient_id=i.patient_id "
          "AND z.era_start >= date_add('day',-365,i.index_date) AND z.era_start <= i.index_date)")

STEPS = [
 ("idx  first-EVER GLP-1RA-w/o-insulin fill (cs4) in [D0,D1] WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r_ag age > 17 at index",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r0   not exposed to DPP-4i (cs8) in (-inf, idx]",  base(f"NOT {rx(8,None,0)}")),
 ("r2   T2D: >=1 IP(cs11) or >=2 OP(cs49) visit [-365,idx] with cs18 dx OR cs10 drug date-contained in visit span",
    t2d_clrd_sql(18, 10)),
 ("r3   CLRD: >=1 IP(cs11) or >=2 OP(cs49) visit [-365,idx] with cs19 dx OR cs6 drug date-contained in visit span",
    t2d_clrd_sql(19, 6)),
 ("r4   add-on: >=1 metformin (cs41) drug-era with era_start in [-365,idx]", R4_SQL),
 ("r5   no insulin (cs37) AND no type 1 diabetes (cs16) in [-365,-1]",
    base(f"NOT {rx(37,-365,-1)} AND NOT {dx(16,-365,-1)}")),
 ("r6   no excluded conditions (CF48,lung43,PE39,PH40,pregnancy50 dx+proc,thyroid42,corticosteroid45) in [-365,-1]",
    base(f"NOT {dx(48,-365,-1)} AND NOT {dx(43,-365,-1)} AND NOT {dx(39,-365,-1)} AND NOT {dx(40,-365,-1)} "
         f"AND NOT {dx(50,-365,-1)} AND NOT {pr('50p',-365,-1)} AND NOT {dx(42,-365,-1)} AND NOT {dx(45,-365,-1)}")),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, str(GAP), SQL_MEDICAL, SQL_PHARMACY, INPAT_v, OUTPAT_v]
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
        ("visit.location_of_care","SELECT location_of_care, COUNT(*) n FROM visit GROUP BY location_of_care ORDER BY n DESC"),
        ("visit.inpatient_ind","SELECT inpatient_ind, COUNT(*) n FROM visit GROUP BY inpatient_ind ORDER BY n DESC")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..7 | final")
