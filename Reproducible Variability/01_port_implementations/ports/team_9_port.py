# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_9  (v2)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-09
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new standalone
# analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist to
# Parquet under /workspace/.ostro_steps/team_9/ — never to stdout.
# HOW TO RUN: python team_9_port.py preflight | 0..6 | final. Delete the step dir first.
#
# Built from Team_9.json + Team_9.sql (CIRCE). INDEX = DrugEra cs38 (GLP-1RA) First=true,
# EraStart 2006-2017, AgeAtStart>=18. = FIRST-EVER cs38 fill in [D0,D1] with >=365d prior
# medical AND pharmacy coverage; age>=18 as step r_ag.
#
# RULE MAP (SQL-anchored). r0/r1 standard exclusions. r2/r3 are visit-correlated with the human
# team's DELIBERATELY ASYMMETRIC windows — reproduced EXACTLY (faithful replication of team config):
#  * r_dpp [AdditionalCriteria gate — Team_9 is the ONLY team with an AdditionalCriteria block; it
#    gates ALL inclusion rules]: DrugEra cs8 (DPP-4I) Occ=0 with era_start in [-365,+0]
#    => EXCLUDE if any DPP-4I drug-era STARTS in [idx-365, idx] (Team_9.sql:404-412, reads DRUG_ERA).
#    Reconstructed as PER-INGREDIENT cs8 eras (gaps-and-islands PARTITION BY (patient,ingredient),
#    30-day gap) then NOT EXISTS era_start in [-365,0] for ANY ingredient. cs8 is a strict subset of
#    cs10, so it is partitioned via the SAME frozen cs10 NDC->ingredient map (Teams 2/4) — no new file;
#    DPP-4I resolves to 4 ingredients (sitagliptin/saxagliptin/linagliptin/alogliptin) that partition
#    cs8 exactly (counts sum to 437). Per-ingredient (not merge-all) so an intra-class DPP-4I SWITCH
#    around index yields a new-ingredient era-start and is caught, matching the OMOP DRUG_ERA grain
#    (consistent with the cs10 per-ingredient decision). Using DrugEra (era_start), NOT DrugExposure
#    (any fill), faithfully avoids excluding patients continuously supplied since >365d before index.
#    The AdditionalCriteria ALSO has DrugEra cs10 Occ>=1 in
#    (-inf,idx+1] = a VERIFIED NO-OP (cs38 GLP-1RA is a strict subset of cs10 -> the index fill always
#    satisfies it; 0/172 GLP-1RA NDCs fall outside cs10); omitted deliberately.
#  * r0 "Insulin treatment": NOT insulin (cs37 drug+device -> prescription) in [-365,-1].
#  * r1 "Other comorbidities" (all [-365,-1], NOT EXISTS): T1D16, CF48, lung43, PE39, PH40,
#    pregnancy cs50 dx+proc+obs, thyroid42, corticosteroid-conditions cs45 (Condition+Obs).
#  * r2 "IP or OP visits for diabetes" (ANY of 2 arms):
#     - Arm A: >=1 cs11 INPATIENT visit (start in [-365,-1]) with EITHER a cs18 dx CONTAINED in the
#       visit span [d.start>=v.start AND d.end<=v.end] (SQL:934) OR a cs10 drug whose exposure END
#       is <= the visit START [e_end<=v.start] (SQL:975 — drug ended by visit start, NOT contained).
#     - Arm B: >=2 distinct cs49 OUTPATIENT visits (start in [-365,-1]) each with a cs18 dx ON the
#       visit start date [d.start=v.start] (SQL:1072) OR a cs10 fill ON the visit start date
#       [e.fill=v.start] (SQL:1113).
#  * r3 "IP or OP visits/meds for CLRD" (ANY of 2 arms):
#     - Arm A: >=1 cs11 INPATIENT visit ([-365,-1]) with EITHER a cs19 dx [d.start>=v.start AND
#       d.end<=v.start] (SQL:1234) OR a cs6 drug [e.fill>=v.start AND e_end<=v.start] (SQL:1275).
#       (These team windows force ~visit-start-day events; kept verbatim.)
#     - Arm B: >=2 distinct cs49 OUTPATIENT visits ([-365,-1]) each with a cs6 fill ON the visit
#       start date [e.fill=v.start] (SQL:1374) OR a cs19 dx starting on/after the visit start
#       [d.start>=v.start] (SQL:1416).
# Visit windows: v.date_start in [idx-365, idx-1] (SW[-365,-1]) for all arms. Big drug lists
# (cs10, cs6) CTE'd ONCE per rule. drug end = fill + COALESCE(days_supply,1) (CIRCE COALESCE);
# dx end = COALESCE(date_end, date_start+1). ICD-10 dot-stripped. ABS bound [2020-01-01,2025-10-31].
# =====================================================================
import os, sys, json, hashlib, time
import pandas as pd
from pyathena import connect

DATASET = "health_verity_foundation"
D0, D1  = "2021-01-01", "2025-10-31"
ABS_LO, ABS_HI = "2020-01-01", "2025-10-31"
GAP = 30
CODEBOOK = "/workspace/.codebook"
OUT_DIR  = "/workspace/.ostro_steps/team_9"

CODESETS = {
    38: {"col":"ndc","n":172,  "sha":"a31e5fa4c7d3ba25","file":"glp_1ra__ndc__verityfoundation.json"},
    6:  {"col":"ndc","n":12025,"sha":"9d157567109e0859","file":"drugs_for_clrd__ndc__verityfoundation.json"},
    10: {"col":"ndc","n":8170, "sha":"f67b4b0aa4b59bec","file":"drugs_for_diabetes__ndc__verityfoundation.json"},
    37: {"col":"ndc","n":1142, "sha":"04f8a0f0e2f9397c","file":"insulin_drugs_and_devices__ndc__verityfoundation.json"},
    8:  {"col":"ndc","n":437,  "sha":"d7773387a9d5a6e6","file":"dpp_4i__ndc__verityfoundation.json"},
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
RAW = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    RAW[cid] = codes
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# cs8 (DPP-4I) is reconstructed as a PER-INGREDIENT drug-era (consistent with cs10 for Teams 2/4).
# cs8 is a strict subset of cs10, so we partition it via the SAME frozen cs10 NDC->RxNorm-ingredient map
# (adversarially reviewed x3) — no new file. DPP-4I resolves to exactly 4 ingredients; every cs8 NDC
# maps to exactly one of them (verified: the four intersection counts sum to len(cs8)=437, no leftover),
# so per-ingredient eras capture intra-class DPP-4I switching that a merge-all era would bridge over.
PART_SHA = "c3a2fb1cacb74c46"
_p = json.load(open(f"{CODEBOOK}/drugs_for_diabetes_by_ingredient.json"))
assert _p["sha"] == PART_SHA, f"cs10 ingredient partition sha {_p['sha']} != {PART_SHA}"
PART = _p["partition"]
DPP4_INGREDIENTS = ["sitagliptin", "saxagliptin", "linagliptin", "alogliptin"]
_cs8 = set(RAW[8])
IN8_ING = {}
for g in DPP4_INGREDIENTS:
    inter = sorted(_cs8 & set(PART[g]))
    assert inter, f"DPP-4I ingredient {g} has no cs8 NDCs"
    IN8_ING[g] = ",".join("'" + c + "'" for c in inter)
_covered = set().union(*(set(PART[g]) for g in DPP4_INGREDIENTS)) & _cs8
assert _covered == _cs8, f"cs8 not fully covered by DPP-4I ingredients: {len(_cs8-_covered)} NDCs unmapped"

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
def dx(cid, lo, hi):   # ConditionOccurrence / Observation -> diagnosis (exclusion rules)
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)})")
def rx(cid, lo, hi):   # DrugExposure / DeviceExposure -> prescription (exclusion rules)
    return (f"EXISTS (SELECT 1 FROM prescription e WHERE e.patient_id=i.patient_id "
            f"AND e.ndc IN ({IN[cid]}) "
            f"AND e.fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('e.fill_date',lo,hi)})")
def pr(cid, lo, hi):   # ProcedureOccurrence -> procedure (exclusion rules)
    return (f"EXISTS (SELECT 1 FROM medicalclaims_procedure pc WHERE pc.patient_id=i.patient_id "
            f"AND pc.procedure_code IN ({IN[cid]}) "
            f"AND pc.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('pc.date_start',lo,hi)})")
def base(cond):
    return f"WITH {IDX} SELECT i.patient_id FROM idx i WHERE {cond}"

# --- r2/r3 visit-correlated arms with team-specific date predicates ---
ABSV = f"v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'"
VW   = "v.date_start>=date_add('day',-365,i.index_date) AND v.date_start<=date_add('day',-1,i.index_date)"  # SW[-365,-1]
DEND = "COALESCE(d.date_end, date_add('day',1,d.date_start))"   # CIRCE COALESCE(condition_end, start+1)
def vjoin(vset):
    return f"JOIN visit v ON v.patient_id=i.patient_id AND ({vset}) AND {ABSV} AND {VW}"
def dxc(cid, pred):    # correlated dx with a custom date predicate relative to visit v
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND {pred})")
def rxc(df, pred):     # correlated drug (from a per-rule fills CTE) with a custom date predicate
    return f"EXISTS (SELECT 1 FROM {df} e WHERE e.patient_id=i.patient_id AND {pred})"
def drugf(df, cid):
    return (f"{df} AS (SELECT patient_id, fill_date, date_add('day', COALESCE(TRY_CAST(days_supply AS integer),1), fill_date) AS e_end "
            f"FROM prescription WHERE ndc IN ({IN[cid]}) AND patient_id IN (SELECT patient_id FROM idx) "
            f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')")

def visit_rule(dxcid, rxcid, df, ipdx, iprx, opdx, oprx):
    return ("WITH " + ",\n".join([IDX, drugf(df, rxcid)]) + "\n"
      # Arm A: >=1 INPATIENT visit with (dx OR drug) matching the arm-A predicate
      f"SELECT DISTINCT i.patient_id FROM idx i {vjoin(INPAT_v)} "
      f"WHERE {dxc(dxcid, ipdx)} OR {rxc(df, iprx)}\n"
      "UNION\n"
      # Arm B: >=2 DISTINCT OUTPATIENT visits each with (dx OR drug) matching the arm-B predicate
      f"SELECT patient_id FROM (SELECT DISTINCT i.patient_id, v.visit_id FROM idx i {vjoin(OUTPAT_v)} "
      f"WHERE {dxc(dxcid, opdx)} OR {rxc(df, oprx)}) t GROUP BY patient_id HAVING COUNT(*) >= 2")

R2_SQL = visit_rule(18, 10, "drugf10",
    ipdx=f"d.date_start>=v.date_start AND {DEND}<=v.date_end",   # cs18 contained in visit span (SQL:934)
    iprx="e.e_end<=v.date_start",                                # cs10 drug ended by visit start (SQL:975)
    opdx="d.date_start=v.date_start",                            # cs18 on visit start date (SQL:1072)
    oprx="e.fill_date=v.date_start")                             # cs10 fill on visit start date (SQL:1113)

R3_SQL = visit_rule(19, 6, "drugf6",
    ipdx=f"d.date_start>=v.date_start AND {DEND}<=v.date_start", # cs19 start>=v.start AND end<=v.start (SQL:1234)
    iprx="e.fill_date>=v.date_start AND e.e_end<=v.date_start",  # cs6 fill>=v.start AND e_end<=v.start (SQL:1275)
    opdx="d.date_start>=v.date_start",                           # cs19 start on/after visit start (SQL:1416)
    oprx="e.fill_date=v.date_start")                             # cs6 fill on visit start date (SQL:1374)

# --- r_dpp AdditionalCriteria gate: DrugEra cs8 Occ=0, era_start in [-365,idx]. PER-INGREDIENT eras
#     (tag each cs8 fill with its DPP-4I ingredient, gaps-and-islands PARTITION BY (patient,ingredient),
#     30-day gap; drug end = fill + COALESCE(days_supply,1) per CIRCE). EXCLUDE if ANY cs8 ingredient
#     era STARTS in [-365,idx] — so an intra-class DPP-4I switch (new ingredient era) is not bridged. ---
def drug_era_ctes_by_ingredient(prefix, ing_map):
    branches = "\nUNION ALL\n".join(
        f"    SELECT patient_id, fill_date AS s, "
        f"date_add('day', COALESCE(TRY_CAST(days_supply AS integer),1), fill_date) AS e, {g!r} AS g "
        f"FROM prescription WHERE ndc IN ({ing_map[g]}) "
        f"AND patient_id IN (SELECT patient_id FROM idx) "
        f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'"
        for g in sorted(ing_map))
    return [
      f"{prefix}_f AS (\n{branches}\n)",
      f"{prefix}_m AS (SELECT patient_id, g, s, e, MAX(e) OVER (PARTITION BY patient_id,g ORDER BY s,e ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM {prefix}_f)",
      f"{prefix}_i AS (SELECT patient_id, g, s, e, CASE WHEN pme IS NULL THEN 1 WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM {prefix}_m)",
      f"{prefix}_g AS (SELECT patient_id, g, s, e, SUM(ne) OVER (PARTITION BY patient_id,g ORDER BY s,e) AS era FROM {prefix}_i)",
      f"{prefix} AS (SELECT patient_id, g, MIN(s) AS era_start FROM {prefix}_g GROUP BY patient_id, g, era)",
    ]
DPP_SQL = ("WITH " + ",\n".join([IDX] + drug_era_ctes_by_ingredient("de8", IN8_ING)) +
           "\nSELECT i.patient_id FROM idx i WHERE NOT EXISTS (SELECT 1 FROM de8 z WHERE z.patient_id=i.patient_id "
           "AND z.era_start >= date_add('day',-365,i.index_date) AND z.era_start <= i.index_date)")

STEPS = [
 ("idx  first-EVER GLP-1RA fill (cs38) in [D0,D1] WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r_ag age >= 18 at index",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) >= 18"),
 ("r_dpp [AdditionalCriteria] no DPP-4I (cs8) drug-era STARTING in [-365,idx] (per-ingredient era, NOT EXISTS)",
    DPP_SQL),
 ("r0   no insulin treatment (cs37 drug+device) in [-365,-1]",  base(f"NOT {rx(37,-365,-1)}")),
 ("r1   no comorbidities (T1D16,CF48,lung43,PE39,PH40,pregnancy50 dx+proc,thyroid42,corticosteroid45) in [-365,-1]",
    base(f"NOT {dx(16,-365,-1)} AND NOT {dx(48,-365,-1)} AND NOT {dx(43,-365,-1)} AND NOT {dx(39,-365,-1)} "
         f"AND NOT {dx(40,-365,-1)} AND NOT {dx(50,-365,-1)} AND NOT {pr('50p',-365,-1)} "
         f"AND NOT {dx(42,-365,-1)} AND NOT {dx(45,-365,-1)}")),
 ("r2   diabetes: >=1 IP(cs11) visit[cs18 contained OR cs10 ended-by-start] OR >=2 OP(cs49) visits[cs18 OR cs10 on visit date]",
    R2_SQL),
 ("r3   CLRD: >=1 IP(cs11) visit[cs19 or cs6 ~at-start] OR >=2 OP(cs49) visits[cs6 on date OR cs19 on/after start]",
    R3_SQL),
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
        ("visit.location_of_care","SELECT location_of_care, COUNT(*) n FROM visit GROUP BY location_of_care ORDER BY n DESC"),
        ("visit.inpatient_ind","SELECT inpatient_ind, COUNT(*) n FROM visit GROUP BY inpatient_ind ORDER BY n DESC")]:
        print(f"-- {label} --"); print(pd.read_sql(sql, c).to_string(index=False))

if __name__ == "__main__":
    print("codesets verified OK; LOGIC_FINGERPRINT:", LOGIC_FINGERPRINT)
    arg = sys.argv[1] if len(sys.argv) > 1 else "info"
    if arg == "preflight": preflight()
    elif arg == "final":   finalize()
    elif arg.isdigit():    run_step(int(arg))
    else: print("usage: preflight | 0..6 | final")
