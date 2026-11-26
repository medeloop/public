# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_2  (v2, DrugEra team)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-09
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new standalone
# analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist to
# Parquet under /workspace/.ostro_steps/team_2/ — never to stdout.
# HOW TO RUN: python team_2_port.py preflight | 0..11 | final. Delete the step dir first.
#
# Built from Team_2.json + Team_2.sql (CIRCE). Team_2 is a DRUG-ERA team.
# INDEX = PrimaryCriteria DrugEra cs4 (GLP-1RA-WITHOUT-insulin, NDC 163 — SAME codeset as Master,
#   NOT cs38). First=true (ordinal=1, no fallback), AgeAtStart>17, ObservationWindow 365d.
#   A first drug-era's START date == the person's earliest cs4 fill, so index = FIRST-EVER cs4
#   fill kept iff in [D0,D1] with >=365d prior medical AND pharmacy coverage (single-span gate,
#   probe-validated). age>17 as step 1 (identical result: tested at that first fill, no fallback).
#   (idx differs from Teams 1/6/7 which index on cs38, and from Master which uses a fallback.)
#
# ERA RECONSTRUCTION (the new machinery, reused by Teams 4/5): OMOP DRUG_ERA / CONDITION_ERA are
# built by the CDM ETL by merging exposures/occurrences with a 30-DAY persistence gap. We
# reconstruct them here via a gaps-and-islands CTE (restricted to idx patients): sort events by
# start; a new era begins when start > (running max end of prior events) + 30 days; era_start =
# MIN(start), era_end = MAX(end) per island. Drug-era end = fill_date + COALESCE(days_supply,1)
# (CIRCE COALESCE(end_date, fill+days_supply, fill+1); the ,1 fallback is a NO-OP here since
# days_supply is probe-clean: 0% null/noncast/nonpos, p50=30, p95=90 — the COALESCE is defensive +
# uniform across all era ports; a 999-day sentinel tail is used AS-IS — capping it would deviate
# from faithful OMOP era construction; REVIEW NOTE flagged). Condition-
# era end = the diagnosis date (claims dx are point events; condition_end := date_start).
#
# DRUG ERAS ARE PER-INGREDIENT: OMOP DRUG_ERA is per RxNorm ingredient. cs10 fills are tagged by
# ingredient via the frozen partition (sha c3a2fb1c...; NDC->ingredient map reviewed x3) and eras are
# built PARTITION BY (patient, ingredient). Replaces the earlier merge-all-cs10 approximation, which
# (a) was permissive for r9's >=1 (bridged ingredient switches) and (b) could not express a >=N count.
# CONDITION eras (cs50 pregnancy, r5) stay merge-all: r5 is an EXISTENCE check, not a count, so grain
# is immaterial there (and no ICD->condition-concept map exists).
#
# DISTINCTIVE RULES:
#  * r9 "Add-on antidiabetic therapy": an ongoing PER-INGREDIENT cs10 DRUG ERA with era_start <= idx-1
#    AND era_end >= idx+30 — i.e. a single diabetes ingredient continuously covering index+30d.
#    KNOWN APPROXIMATION (decided 2026-07-09 w/ Josh; reviewer-passed MINOR, strictly permissive):
#    CIRCE also bounds this era by the observation period (Team_2.sql:1124 —
#    "A.START_DATE >= OP_START ... AND A.END_DATE <= OP_END"). This port OMITS that per-patient
#    OP clamp for r9, to keep the OP~=ABS-window coverage model UNIFORM across all ports (every
#    backward criterion likewise approximates OP_START by the ABS_LO 2020 data-start floor). Effect
#    is one-directional: r9 here can only OVER-include vs CIRCE (a patient whose add-on era
#    nominally runs >= idx+30 but whose coverage lapsed earlier is kept here, dropped by CIRCE) —
#    never spuriously beyond CIRCE. To make r9 EXACT, add to its inner EXISTS:
#      AND EXISTS (SELECT 1 FROM enrollment m WHERE m.patient_id=i.patient_id AND {SQL_MEDICAL}
#                  AND m.date_start <= z.era_start AND m.date_end >= z.era_end)
#    (era fully within one medical coverage span => era_start>=OP_START AND era_end<=OP_END).
#    This same choice applies to any forward-looking era criterion in the other DrugEra teams (4,5).
#  * r5 "No pregnancy at index": NOT( cs50 CONDITION ERA with era_start in [idx-270,idx] AND
#    era_end in [idx,idx+270] ) AND NOT(cs50 procedure in [-60,+60]) AND NOT(cs50 observation at
#    exactly idx-60 [-60,-60] — a degenerate single-day window, reproduced literally).
#  * r0 T2D / r1 CLRD (Type ANY), dx-anchored via OMOP VisitType (OP=9202->cs49 outpatient;
#    IP/ERIP=9201/262->cs11 inpatient): >=2 dx@OP [-365,0] OR >=1 dx@IP [-365,0] OR >=1 drug
#    (cs10 [-365,-1] for T2D; cs6 [-365,0] for CLRD — asymmetric drug windows, reproduced). The
#    >=2 OP arms count DISTINCT (visit_id,diagnosis_code) occurrences (faithful proxy, as Team_7).
#  * DPP-4i exclusion cs8 [-365,0] (index-inclusive). Exclusions CF48/lung43/PE39/PH40 (r2),
#    thyroid42 (r3), corticosteroid45 (r4), T1D16 (r6), insulin cs37 drug+device (r8) all use an
#    UNBOUNDED look-back (-inf,-1] (floored at data start ABS_LO) — NOT [-365,-1].
# ICD-10 dot-stripped. Absolute date bound [2020-01-01,2025-10-31] on every criterion.
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"
GAP = 30                                   # OMOP era persistence gap (days)
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_steps/team_2"

CODESETS = {
    4:  {"col":"ndc","n":163,  "sha":"e2b0ae8663f4f02a","file":"glp_1ra_without_insulin__ndc__verityfoundation.json"},
    6:  {"col":"ndc","n":12025,"sha":"9d157567109e0859","file":"drugs_for_clrd__ndc__verityfoundation.json"},
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
INPAT_v  = "lower(cast(v.inpatient_ind as varchar)) IN ('y','yes','true','t','1')"   # cs11 (IP/ERIP)
OUTPAT_v = ("(v.location_of_care IN ('OFFICE/CLINIC','AMBULATORY SURGICAL CENTER') "  # cs49 (OP)
            "OR (v.location_of_care='HOSPITAL' AND NOT (" + INPAT_v + ")))")

def h(cs): return hashlib.sha256(",".join(cs).encode()).hexdigest()[:16]
IN = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# cs10 "Drugs for diabetes" is loaded PER-INGREDIENT from the frozen ingredient partition (RxNorm
# ingredient grain; the underlying NDC->ingredient map was adversarially reviewed x3). This drives
# the DrugEra "add-on" rule (r9) at ingredient grain; the union serves the DrugExposure arm rx(10).
PART_SHA = "c3a2fb1cacb74c46"
_p = json.load(open(f"{CODEBOOK}/drugs_for_diabetes_by_ingredient.json"))
assert _p["sha"] == PART_SHA, f"cs10 ingredient partition sha {_p['sha']} != {PART_SHA}"
PART = _p["partition"]                                     # {ingredient: [ndc,...]}
IN10_ING = {g: ",".join("'" + c + "'" for c in ndcs) for g, ndcs in PART.items()}
_cs10 = sorted({c for ndcs in PART.values() for c in ndcs})
assert len(_cs10) == 8170, f"cs10 union {len(_cs10)} != 8170"
IN[10] = ",".join("'" + c + "'" for c in _cs10)           # full cs10 for DrugExposure rx(10)

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
def dx(cid, lo, hi):   # ConditionOccurrence / Observation -> diagnosis (any setting)
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
def dx_ip(cid, lo, hi):     # >=1 cid dx in [lo,hi] AT an inpatient (cs11: IP/ERIP) visit
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d JOIN visit v ON v.visit_id=d.visit_id "
            f"WHERE d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND ({INPAT_v}) AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)})")
def dx_op_ge2(cid, lo, hi): # >=2 distinct (visit_id,diagnosis_code) cid dx in [lo,hi] AT outpatient (cs49) visits
    return (f"(SELECT COUNT(DISTINCT CONCAT(CAST(d.visit_id AS varchar),'~',d.diagnosis_code)) "
            f"FROM medicalclaims_diagnosis d JOIN visit v ON v.visit_id=d.visit_id "
            f"WHERE d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND ({OUTPAT_v}) AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)}) >= 2")
def base(cond):
    return f"WITH {IDX} SELECT i.patient_id FROM idx i WHERE {cond}"

# --- era reconstruction (gaps-and-islands, GAP-day persistence), restricted to idx patients ---
def _era_ctes(prefix, src_from, start_col, end_expr):
    return [
      f"{prefix}_f AS (SELECT src.patient_id, {start_col} AS s, {end_expr} AS e FROM {src_from} "
      f"WHERE src.patient_id IN (SELECT patient_id FROM idx))",
      f"{prefix}_m AS (SELECT patient_id, s, e, MAX(e) OVER (PARTITION BY patient_id ORDER BY s,e "
      f"ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM {prefix}_f)",
      f"{prefix}_i AS (SELECT patient_id, s, e, CASE WHEN pme IS NULL THEN 1 "
      f"WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM {prefix}_m)",
      f"{prefix}_g AS (SELECT patient_id, s, e, SUM(ne) OVER (PARTITION BY patient_id ORDER BY s,e) AS era FROM {prefix}_i)",
      f"{prefix} AS (SELECT patient_id, MIN(s) AS era_start, MAX(e) AS era_end FROM {prefix}_g GROUP BY patient_id, era)",
    ]
def drug_era_ctes_by_ingredient(prefix):
    # PER-INGREDIENT cs10 drug eras: tag each fill with its RxNorm ingredient (combos -> one row per
    # ingredient), restrict to idx patients, then gaps-and-islands PARTITION BY (patient, ingredient)
    # so each ingredient has its own era stream (no cross-ingredient bridging). Yields (patient,g,era).
    branches = "\nUNION ALL\n".join(
        f"    SELECT patient_id, fill_date AS s, "
        f"date_add('day', COALESCE(TRY_CAST(days_supply AS integer),1), fill_date) AS e, {g!r} AS g "
        f"FROM prescription WHERE ndc IN ({IN10_ING[g]}) "
        f"AND patient_id IN (SELECT patient_id FROM idx) "
        f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'"
        for g in sorted(IN10_ING))
    return [
      f"{prefix}_f AS (\n{branches}\n)",
      f"{prefix}_m AS (SELECT patient_id, g, s, e, MAX(e) OVER (PARTITION BY patient_id,g ORDER BY s,e "
      f"ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM {prefix}_f)",
      f"{prefix}_i AS (SELECT patient_id, g, s, e, CASE WHEN pme IS NULL THEN 1 "
      f"WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM {prefix}_m)",
      f"{prefix}_g AS (SELECT patient_id, g, s, e, SUM(ne) OVER (PARTITION BY patient_id,g ORDER BY s,e) AS era FROM {prefix}_i)",
      f"{prefix} AS (SELECT patient_id, g, MIN(s) AS era_start, MAX(e) AS era_end FROM {prefix}_g GROUP BY patient_id, g, era)",
    ]
def cond_era_ctes(prefix, cid):   # CONDITION era (merge-all cs50): only used for pregnancy EXISTENCE (r5),
    # not a count, so per-concept grain is immaterial here (an overlapping pregnancy era -> excluded).
    src = (f"(SELECT patient_id, date_start FROM medicalclaims_diagnosis "
           f"WHERE diagnosis_qual='ICD-10' AND diagnosis_code IN ({IN[cid]}) "
           f"AND date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}') src")
    return _era_ctes(prefix, src, "src.date_start", "src.date_start")

# r9 add-on: an ongoing PER-INGREDIENT cs10 drug era (start <= idx-1 AND end >= idx+30). Per-ingredient
# eras cannot bridge across ingredient switches around index (that was the old merge-all approximation).
R9_SQL = ("WITH " + ",\n".join([IDX] + drug_era_ctes_by_ingredient("de10")) +
          "\nSELECT i.patient_id FROM idx i WHERE EXISTS (SELECT 1 FROM de10 z "
          "WHERE z.patient_id=i.patient_id AND z.era_start <= date_add('day',-1,i.index_date) "
          "AND z.era_end >= date_add('day',30,i.index_date))")
# r5 no pregnancy: no cs50 condition era overlapping index, no cs50 procedure [-60,+60], no cs50 obs at idx-60
R5_SQL = ("WITH " + ",\n".join([IDX] + cond_era_ctes("pe50", 50)) +
          "\nSELECT i.patient_id FROM idx i WHERE NOT EXISTS (SELECT 1 FROM pe50 z "
          "WHERE z.patient_id=i.patient_id "
          "AND z.era_start >= date_add('day',-270,i.index_date) AND z.era_start <= i.index_date "
          "AND z.era_end   >= i.index_date AND z.era_end <= date_add('day',270,i.index_date)) "
          f"AND NOT {pr('50p',-60,60)} AND NOT {dx(50,-60,-60)}")

STEPS = [
 ("idx  first-EVER GLP-1RA-w/o-insulin fill (cs4 drug-era start) in [D0,D1] WITH >=365d med+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r_ag age > 17 at index (AgeAtStart)",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r0   T2D: >=2 cs18 dx@OP [-365,0] OR >=1 cs18 dx@IP [-365,0] OR >=1 cs10 drug [-365,-1]",
    base(f"({dx_op_ge2(18,-365,0)} OR {dx_ip(18,-365,0)} OR {rx(10,-365,-1)})")),
 ("r1   CLRD: >=2 cs19 dx@OP [-365,0] OR >=1 cs19 dx@IP [-365,0] OR >=1 cs6 drug [-365,0]",
    base(f"({dx_op_ge2(19,-365,0)} OR {dx_ip(19,-365,0)} OR {rx(6,-365,0)})")),
 ("r2   no CF/lung/PE/PH (cs48,43,39,40) in (unbounded,-1]",
    base(f"NOT {dx(48,None,-1)} AND NOT {dx(43,None,-1)} AND NOT {dx(39,None,-1)} AND NOT {dx(40,None,-1)}")),
 ("r3   no thyroid carcinoma (cs42) in (unbounded,-1]",    base(f"NOT {dx(42,None,-1)}")),
 ("r4   no corticosteroid-conditions (cs45) in (unbounded,-1]", base(f"NOT {dx(45,None,-1)}")),
 ("r5   no pregnancy (cs50 condition-era overlap idx + proc[-60,+60] + obs[-60,-60])", R5_SQL),
 ("r6   no type 1 diabetes (cs16) in (unbounded,-1]",      base(f"NOT {dx(16,None,-1)}")),
 ("r7   no DPP-4i (cs8) in [-365,0] (index-inclusive)",    base(f"NOT {rx(8,-365,0)}")),
 ("r8   no insulin drugs/devices (cs37) in (unbounded,-1]", base(f"NOT {rx(37,None,-1)}")),
 ("r9   add-on antidiabetic: cs10 drug-era start<=idx-1 AND end>=idx+30", R9_SQL),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, str(GAP), SQL_MEDICAL, SQL_PHARMACY, INPAT_v, OUTPAT_v]
                  + [f"cs10_ingredient_partition:{PART_SHA}"]
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
        ("visit.location_of_care (for IP/OP arms)","SELECT location_of_care, COUNT(*) n FROM visit GROUP BY location_of_care ORDER BY n DESC"),
        ("visit.inpatient_ind","SELECT inpatient_ind, COUNT(*) n FROM visit GROUP BY inpatient_ind ORDER BY n DESC")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..11 | final")
