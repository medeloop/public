# =====================================================================
# Ostropolets x Violin — Sub-study 1 DETERMINISTIC reference port: TEAM_4  (v2, DrugEra team)
# Target: health_verity_foundation (Verity Foundation)  |  2026-07-09
#
# ***RUN THIS SCRIPT EXACTLY AS WRITTEN.***  Do NOT modify/optimize/correct/re-order.
# Do NOT call find_codes. Report printed output VERBATIM. Treat as a brand-new standalone
# analysis; do not consult memory or prior workspace files.
#
# PHI: only aggregate counts + SHA-256 hashes printed. Per-step patient_id sets persist to
# Parquet under /workspace/.ostro_steps/team_4/ — never to stdout.
# HOW TO RUN: python team_4_port.py preflight | 0..13 | final. Delete the step dir first.
#
# Built from Team_4.json + Team_4.sql (CIRCE). Team_4 is a DRUG-ERA team.
# INDEX = PrimaryCriteria DrugEra cs38 (GLP-1RA), First=true (ordinal=1, no fallback), AgeAtStart>17,
#   365d obs. First drug-era START = earliest cs38 fill ⇒ index = FIRST-EVER cs38 fill kept iff in
#   [D0,D1] with >=365d prior medical AND pharmacy coverage (single-span). age>17 as step r_ag.
#
# ***FAITHFUL QUIRK (r3): "No insulin prior to index date" is a MISNOMER.*** The coded definition
# (Team_4.json + Team_4.sql:894 HAVING COUNT>=1, in contrast to the =0 exclusions) REQUIRES >=1
# insulin (cs37) exposure in (-inf, index]. We reproduce it AS CODED (require prior insulin) — the
# study measures how faithfully AI vs the human teams reproduce Albogami, so human-team errors are
# replicated, not corrected (decided w/ Josh 2026-07-09). This makes Team_4 an insulin-experienced,
# poly-therapy add-on cohort (small).
#
# DRUG ERAS ARE PER-INGREDIENT (shared helper; frozen partition sha c3a2fb1c..., NDC->ingredient map
# reviewed x3). r2 counts DISTINCT diabetes INGREDIENTS. cs10/cs6 DrugExposure arms use the full union.
#
# RULE MAP (SQL-anchored):
#  * r0 T2D / r1 CLRD (Type ANY): (A) >=1 INPATIENT visit (cs11) starting [-365,-1] with a cs18/cs19
#    dx OR cs10/cs6 drug whose date is CONTAINED IN THE VISIT SPAN [visit.date_start,visit.date_end]
#    (date-containment, NOT visit_id/RestrictVisit, NOT VisitType — Team_4.sql:523); OR (B) >=2 dx
#    [-365,-1]; OR (C) >=2 drug fills [-365,-1]. (>=2 counted as DISTINCT (visit,code)/(fill_date,ndc).)
#  * r2 "add-on": cs10 DrugEra, COUNT(DISTINCT ingredient) >=2 spanning index (era_start<=idx AND
#    era_end>=idx) [Team_4.sql:845].
#  * r3: REQUIRE >=1 insulin cs37 in (-inf, idx] (the quirk above).
#  * r4-r8,r10 exclusions =0, window (-inf, idx] (index-INCLUSIVE): T1D16, CF48, lung43, PE39, PH40,
#    thyroid42.  * r9 "No pregnancy": NOT a cs50 CONDITION-ERA starting within +/-280d of index
#    (merge-all cond-era; existence, documented grain caveat).
#  * r11 "No corticosteroid": CONJUNCTIVE — exclude if a cs47 corticosteroid DRUG in [-inf,idx-1]
#    co-occurs with a cs45 CONDITION dated <= that drug (Team_4.sql:1289/1351).
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
OUT_DIR  = "/workspace/.ostro_steps/team_4"

CODESETS = {
    38: {"col":"ndc","n":172,  "sha":"a31e5fa4c7d3ba25","file":"glp_1ra__ndc__verityfoundation.json"},
    6:  {"col":"ndc","n":12025,"sha":"9d157567109e0859","file":"drugs_for_clrd__ndc__verityfoundation.json"},
    37: {"col":"ndc","n":1142, "sha":"04f8a0f0e2f9397c","file":"insulin_drugs_and_devices__ndc__verityfoundation.json"},
    47: {"col":"ndc","n":7625, "sha":"18781ec58e92f5e2","file":"systematic_corticosteroids__ndc__verityfoundation.json"},
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
}

SQL_MEDICAL  = "lower(benefit_type) LIKE '%medical%'"
SQL_PHARMACY = "(lower(benefit_type) LIKE '%pharm%' OR lower(benefit_type) LIKE '%rx%')"
INPAT_v  = "lower(cast(v.inpatient_ind as varchar)) IN ('y','yes','true','t','1')"   # cs11 inpatient

def h(cs): return hashlib.sha256(",".join(cs).encode()).hexdigest()[:16]
IN = {}
for cid, m in CODESETS.items():
    codes = json.load(open(f"{CODEBOOK}/{m['file']}"))["codes_list"]
    assert len(codes) == m["n"], f"codeset {cid}: count {len(codes)} != {m['n']}"
    assert h(codes) == m["sha"], f"codeset {cid}: checksum mismatch vs frozen canonical"
    IN[cid] = ",".join("'" + c + "'" for c in codes)

# cs10 per-ingredient partition (drives r2 ingredient count; union serves the cs10 DrugExposure arms).
PART_SHA = "c3a2fb1cacb74c46"
_p = json.load(open(f"{CODEBOOK}/drugs_for_diabetes_by_ingredient.json"))
assert _p["sha"] == PART_SHA, f"cs10 ingredient partition sha {_p['sha']} != {PART_SHA}"
PART = _p["partition"]
IN10_ING = {g: ",".join("'" + c + "'" for c in ndcs) for g, ndcs in PART.items()}
_cs10 = sorted({c for ndcs in PART.values() for c in ndcs})
assert len(_cs10) == 8170, f"cs10 union {len(_cs10)} != 8170"
IN[10] = ",".join("'" + c + "'" for c in _cs10)

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
def dx(cid, lo, hi):   # ConditionOccurrence -> diagnosis (EXISTS, any setting)
    return (f"EXISTS (SELECT 1 FROM medicalclaims_diagnosis d WHERE d.patient_id=i.patient_id "
            f"AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[cid]}) "
            f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('d.date_start',lo,hi)})")
def rx(cid, lo, hi):   # DrugExposure / DeviceExposure -> prescription (EXISTS)
    return (f"EXISTS (SELECT 1 FROM prescription e WHERE e.patient_id=i.patient_id "
            f"AND e.ndc IN ({IN[cid]}) "
            f"AND e.fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'{_w('e.fill_date',lo,hi)})")
def base(cond):
    return f"WITH {IDX} SELECT i.patient_id FROM idx i WHERE {cond}"

# --- r0/r1: inpatient-visit date-containment (arm A) OR >=2 dx (B) OR >=2 drug (C).
# Big drug list (cs10/cs6) is CTE'd ONCE so the step stays under the 256KB query limit. UNION of arms.
def t2d_clrd_sql(dxcid, rxcid):
    df = f"drugf{rxcid}"
    W  = "v.date_start>=date_add('day',-365,i.index_date) AND v.date_start<=date_add('day',-1,i.index_date)"
    return ("WITH " + ",\n".join([IDX,
        f"{df} AS (SELECT patient_id, fill_date, ndc, COALESCE(TRY_CAST(days_supply AS integer),1) AS dsup "
        f"FROM prescription WHERE ndc IN ({IN[rxcid]}) AND patient_id IN (SELECT patient_id FROM idx) "
        f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')"]) + "\n"
      # arm A: dx date-contained in an inpatient visit span
      f"SELECT i.patient_id FROM idx i "
      f"JOIN visit v ON v.patient_id=i.patient_id AND ({INPAT_v}) AND v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND {W} "
      f"JOIN medicalclaims_diagnosis d ON d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[dxcid]}) "
      f"AND d.date_start BETWEEN v.date_start AND v.date_end\n"
      "UNION\n"
      # arm A: drug date-contained in an inpatient visit span
      f"SELECT i.patient_id FROM idx i "
      f"JOIN visit v ON v.patient_id=i.patient_id AND ({INPAT_v}) AND v.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND {W} "
      f"JOIN {df} e ON e.patient_id=i.patient_id AND e.fill_date>=v.date_start AND date_add('day',e.dsup,e.fill_date)<=v.date_end\n"
      "UNION\n"
      # arm B: >=2 distinct (visit,code) dx in [-365,-1]
      f"SELECT patient_id FROM (SELECT i.patient_id, COUNT(DISTINCT CONCAT(CAST(d.visit_id AS varchar),'~',d.diagnosis_code)) c "
      f"FROM idx i JOIN medicalclaims_diagnosis d ON d.patient_id=i.patient_id AND d.diagnosis_qual='ICD-10' AND d.diagnosis_code IN ({IN[dxcid]}) "
      f"AND d.date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}' AND d.date_start>=date_add('day',-365,i.index_date) AND d.date_start<=date_add('day',-1,i.index_date) "
      f"GROUP BY i.patient_id) t WHERE c>=2\n"
      "UNION\n"
      # arm C: >=2 distinct (fill_date,ndc) drug fills in [-365,-1]
      f"SELECT patient_id FROM (SELECT e.patient_id, COUNT(DISTINCT CONCAT(CAST(e.fill_date AS varchar),'~',e.ndc)) c "
      f"FROM {df} e JOIN idx i ON i.patient_id=e.patient_id AND e.fill_date>=date_add('day',-365,i.index_date) AND e.fill_date<=date_add('day',-1,i.index_date) "
      f"GROUP BY e.patient_id) t WHERE c>=2")

# --- r2: per-ingredient cs10 drug eras; COUNT(DISTINCT ingredient) spanning index >= 2 ---
def drug_era_ctes_by_ingredient(prefix):
    branches = "\nUNION ALL\n".join(
        f"    SELECT patient_id, fill_date AS s, date_add('day', COALESCE(TRY_CAST(days_supply AS integer),1), fill_date) AS e, {g!r} AS g "
        f"FROM prescription WHERE ndc IN ({IN10_ING[g]}) AND patient_id IN (SELECT patient_id FROM idx) "
        f"AND fill_date BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}'"
        for g in sorted(IN10_ING))
    return [
      f"de10_f AS (\n{branches}\n)",
      f"de10_m AS (SELECT patient_id, g, s, e, MAX(e) OVER (PARTITION BY patient_id,g ORDER BY s,e ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM de10_f)",
      f"de10_i AS (SELECT patient_id, g, s, e, CASE WHEN pme IS NULL THEN 1 WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM de10_m)",
      f"de10_gg AS (SELECT patient_id, g, s, e, SUM(ne) OVER (PARTITION BY patient_id,g ORDER BY s,e) AS era FROM de10_i)",
      f"de10 AS (SELECT patient_id, g, MIN(s) AS era_start, MAX(e) AS era_end FROM de10_gg GROUP BY patient_id, g, era)",
    ]
R2_SQL = ("WITH " + ",\n".join([IDX] + drug_era_ctes_by_ingredient("de10")) +
          "\nSELECT i.patient_id FROM idx i WHERE (SELECT COUNT(DISTINCT z.g) FROM de10 z "
          "WHERE z.patient_id=i.patient_id AND z.era_start <= i.index_date AND z.era_end >= i.index_date) >= 2")

# --- r9: no cs50 CONDITION-era starting within +/-280d of index ---
COND50 = [
  f"pe50_f AS (SELECT patient_id, date_start AS s, date_start AS e FROM medicalclaims_diagnosis "
  f"WHERE diagnosis_qual='ICD-10' AND diagnosis_code IN ({IN[50]}) AND patient_id IN (SELECT patient_id FROM idx) "
  f"AND date_start BETWEEN DATE '{ABS_LO}' AND DATE '{ABS_HI}')",
  "pe50_m AS (SELECT patient_id, s, e, MAX(e) OVER (PARTITION BY patient_id ORDER BY s,e ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pme FROM pe50_f)",
  f"pe50_i AS (SELECT patient_id, s, e, CASE WHEN pme IS NULL THEN 1 WHEN s<=date_add('day',{GAP},pme) THEN 0 ELSE 1 END AS ne FROM pe50_m)",
  "pe50_gg AS (SELECT patient_id, s, e, SUM(ne) OVER (PARTITION BY patient_id ORDER BY s,e) AS era FROM pe50_i)",
  "pe50 AS (SELECT patient_id, MIN(s) AS era_start FROM pe50_gg GROUP BY patient_id, era)",
]
R9_SQL = ("WITH " + ",\n".join([IDX] + COND50) +
          "\nSELECT i.patient_id FROM idx i WHERE NOT EXISTS (SELECT 1 FROM pe50 z WHERE z.patient_id=i.patient_id "
          "AND z.era_start >= date_add('day',-280,i.index_date) AND z.era_start <= date_add('day',280,i.index_date))")

# --- r11: NOT EXISTS a cs47 corticosteroid drug (-inf,idx-1] with a cs45 condition dated <= that drug ---
R11_SQL = base(
  f"NOT EXISTS (SELECT 1 FROM prescription e1 "
  f"JOIN medicalclaims_diagnosis d ON d.patient_id=e1.patient_id AND d.diagnosis_qual='ICD-10' "
  f"AND d.diagnosis_code IN ({IN[45]}) AND d.date_start BETWEEN DATE '{ABS_LO}' AND e1.fill_date "
  f"WHERE e1.patient_id=i.patient_id AND e1.ndc IN ({IN[47]}) "
  f"AND e1.fill_date BETWEEN DATE '{ABS_LO}' AND date_add('day',-1,i.index_date))")

STEPS = [
 ("idx  first-EVER GLP-1RA fill (cs38 drug-era start) in [D0,D1] WITH >=365d medical+pharmacy coverage",
    f"WITH {IDX} SELECT patient_id FROM idx"),
 ("r_ag age > 17 at index",
    "WITH " + IDX + " SELECT i.patient_id FROM idx i JOIN patient p ON p.patient_id=i.patient_id "
    "WHERE (year(i.index_date) - TRY_CAST(p.year_of_birth AS integer)) > 17"),
 ("r0   T2D: >=1 IP visit(cs11) w/ cs18 dx|cs10 drug date-contained [-365,-1] OR >=2 cs18 dx OR >=2 cs10 drug [-365,-1]",
    t2d_clrd_sql(18, 10)),
 ("r1   CLRD: >=1 IP visit(cs11) w/ cs19 dx|cs6 drug date-contained [-365,-1] OR >=2 cs19 dx OR >=2 cs6 drug [-365,-1]",
    t2d_clrd_sql(19, 6)),
 ("r2   add-on: >=2 DISTINCT cs10 diabetes INGREDIENTS with a drug-era spanning index",
    R2_SQL),
 ("r3   [QUIRK: misnamed 'No insulin'] REQUIRE >=1 insulin (cs37) in (-inf, idx]",
    base(f"{rx(37, None, 0)}")),
 ("r4   no type 1 diabetes (cs16) in (-inf, idx]",        base(f"NOT {dx(16,None,0)}")),
 ("r5   no cystic fibrosis (cs48) in (-inf, idx]",        base(f"NOT {dx(48,None,0)}")),
 ("r6   no lung cancer (cs43) in (-inf, idx]",            base(f"NOT {dx(43,None,0)}")),
 ("r7   no pulmonary embolism (cs39) in (-inf, idx]",     base(f"NOT {dx(39,None,0)}")),
 ("r8   no pulmonary hypertension (cs40) in (-inf, idx]", base(f"NOT {dx(40,None,0)}")),
 ("r9   no pregnancy (cs50 condition-era starting within +/-280d of index)", R9_SQL),
 ("r10  no thyroid carcinoma (cs42) in (-inf, idx]",      base(f"NOT {dx(42,None,0)}")),
 ("r11  no corticosteroid: cs47 drug [-inf,idx-1] with a correlated cs45 condition (<= drug date)", R11_SQL),
]

fp_src = "|".join([DATASET, D0, D1, ABS_LO, ABS_HI, str(GAP), SQL_MEDICAL, SQL_PHARMACY, INPAT_v,
                   f"cs10_ingredient_partition:{PART_SHA}"]
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
    else: print("usage: preflight | 0..13 | final")
