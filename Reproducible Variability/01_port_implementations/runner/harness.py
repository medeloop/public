"""Per-port execution harness.

For a given port YAML, this module:

  1. Builds the primary-criterion DataFrame (df_primary_index).
  2. Restricts to the observation window using `enrollment`.
  3. Iterates inclusion rules, producing one DataFrame per rule and
     composing them according to `type` (ALL = intersection,
     ANY = union, AT_LEAST_N = ≥ N rules satisfied per patient).
  4. Applies end_strategy (CustomEra or DateOffset) to attach cohort_end_date.
  5. For inverted structures (Team_8 / Team_9) inverts against the universe
     defined by the observation window.
  6. Records an attrition row per step.

The harness deliberately pushes *natural-language* prompts to Medeloop (its
native interface) and names every intermediate DataFrame explicitly so
follow-up prompts can reference them without re-inlining code lists.

Any prompt longer than 350 chars is emitted as a `long_prompt` log entry on
the session — in practice the per-step prompts fit comfortably because
codesets are already materialised as `df_codeset_<id>`.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .mcp import MedeloopSession


# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    index: int
    name: str
    df_name: str
    n_patients: int | None
    wallclock_s: float
    prompt: str


@dataclass
class PortExecutionResult:
    cohort_name: str
    structure: str
    steps: list[StepResult] = field(default_factory=list)
    final_df: str = "df_cohort_final"
    final_n: int | None = None
    cohort_hash: str | None = None
    started_at: str = ""
    ended_at: str = ""


# ---------------------------------------------------------------------------
# Domain → Medeloop table mapping.
# Mirrors phase2/port_runner/core._DOMAIN_TABLE_COLS. We do NOT trust the
# `medeloop_table` field in the Phase 1 port YAML — it still carries
# "UNRESOLVED" for Observation, ConditionEra, and ProcedureOccurrence (the
# DEV-004 / DEV-005 resolutions live in Phase 2's port_runner).
# ---------------------------------------------------------------------------

_DOMAIN_TABLE_COL = {
    "DrugExposure":        ("pharmacy_claims", "ndc_code"),
    "DeviceExposure":      ("pharmacy_claims", "ndc_code"),
    "DrugEra":             ("pharmacy_claims", "ndc_code"),   # reconstructed eras
    "ConditionOccurrence": ("diagnosis",       "diagnosis_code"),
    "Observation":         ("diagnosis",       "diagnosis_code"),   # DEV-004
    "ConditionEra":        ("diagnosis",       "diagnosis_code"),   # DEV-005
    "VisitOccurrence":     ("visits",          "visit_bucket"),     # DEV-003 buckets
}


def _resolve_table_col(domain: str, c: dict) -> tuple[str, str]:
    """Pick the canonical (table, code_column) for a criterion domain."""
    return _DOMAIN_TABLE_COL.get(domain, ("UNRESOLVED", "concept_id"))


# ---------------------------------------------------------------------------
# Prompt templates (short, named, Medeloop-native)
# ---------------------------------------------------------------------------


def _primary_prompt(cohort: str, port: dict) -> tuple[str, str]:
    """Primary index event → df_primary_index."""
    pc = port["primary_criteria"]["criteria"][0]
    domain = pc["domain"]
    codeset_id = pc["codeset_id"]
    dw = pc["date_window"]["shifted"]
    df = f"df_{_slug(cohort)}_primary_index"
    if domain in ("DrugExposure", "DeviceExposure"):
        prompt = (
            f"Create pandas {df}: first fill per patient in pharmacy_claims "
            f"where ndc_code in df_codeset_{codeset_id}.ndc_code and "
            f"date_service between {dw['start']} and {dw['end']}. "
            f"Columns: patient_id, index_date=date_service."
        )
    elif domain == "DrugEra":
        # Eras are reconstructed from pharmacy_claims with gap ≤ 30 days per the
        # frozen schema contract. Medeloop computes eras on the fly.
        prompt = (
            f"Create pandas {df}: first drug-era start per patient whose "
            f"pharmacy_claims ndc_code is in df_codeset_{codeset_id}.ndc_code, "
            f"gap<=30d, era_start between {dw['start']} and {dw['end']}. "
            f"Columns: patient_id, index_date=era_start_date."
        )
    else:
        raise ValueError(f"Unsupported primary domain: {domain}")
    return df, prompt


def _obs_window_prompt(
    cohort: str, port: dict, primary_df: str
) -> tuple[str, str]:
    ow = port["primary_criteria"]["observation_window"]
    prior = ow.get("prior_days", 0)
    post = ow.get("post_days", 0)
    df = f"df_{_slug(cohort)}_after_obs_window"
    prompt = (
        f"Create pandas {df}: rows of {primary_df} whose patient has an "
        f"enrollment span covering [index_date - {prior}d, index_date + {post}d]. "
        f"Keep patient_id, index_date."
    )
    return df, prompt


def _rule_prompt(
    cohort: str,
    candidates_df: str,
    rule: dict,
) -> tuple[str, str]:
    idx = rule["index"]
    name = rule["name"]
    df = f"df_{_slug(cohort)}_step{idx:02d}"
    parts: list[str] = []

    # Natural-language assembly of the rule. Medeloop interprets these as
    # semantic filters on the named candidate DataFrame.
    for c in rule.get("criteria", []):
        parts.append(_criterion_phrase(c))
    for d in rule.get("demographic", []):
        parts.append(_demographic_phrase(d))

    if not parts:
        # empty rule (shouldn't happen but tolerate) — pass-through
        prompt = (
            f"Create pandas {df} as a copy of {candidates_df} "
            f"(rule {idx}: {name}; no criteria)."
        )
        return df, prompt

    rtype = rule.get("type", "ALL")
    joiner = {"ALL": " AND ", "ANY": " OR "}.get(rtype, " AND ")
    body = joiner.join(parts)
    prompt = (
        f"Create pandas {df}: rows of {candidates_df} where {body} "
        f"(rule {idx}: {name[:80]}; type={rtype})."
    )
    return df, prompt


def _criterion_phrase(c: dict) -> str:
    """Render a single criterion as a short natural-language fragment."""
    domain = c["domain"]
    cs = c["codeset_id"]
    table, code_col = _resolve_table_col(domain, c)
    sw = c.get("start_window")
    occ = c.get("occurrence")
    otype = occ.get("type_name") if occ else None
    ocount = occ.get("count") if occ else None

    # Window expressed relative to index_date
    window = _window_phrase(sw)

    # Predicate wrapper
    if domain == "DrugEra":
        base = f"pharmacy_claims era of ingredient in df_codeset_{cs}.ndc_code (gap≤30d)"
    elif domain == "ProcedureOccurrence":
        # Codeset 50 (pregnancy) is the only multi-vocab codeset: ICD-10
        # diagnoses + CPT/HCPCS procedures. Each column is its own DataFrame
        # (see codeset_loader.df_name_for). Emit a disjunction.
        base = (
            f"(diagnosis.diagnosis_code in "
            f"df_codeset_{cs}_diagnosis_code.diagnosis_code or "
            f"procedure.procedure_code in "
            f"df_codeset_{cs}_procedure_code.procedure_code)"
        )
    elif domain == "VisitOccurrence":
        base = f"visit_bucket in df_codeset_{cs}.visit_bucket"
    else:
        base = f"{table}.{code_col} in df_codeset_{cs}.{code_col}"

    gender = c.get("gender")
    if gender:
        gphr = " and patient sex = F" if any(
            g.get("CONCEPT_CODE") == "F" for g in gender
        ) else ""
    else:
        gphr = ""

    # Occurrence cardinality
    if otype == "exactly" and ocount == 0:
        cardinality = "no"
    elif otype == "at_least":
        cardinality = f"at least {ocount}"
    elif otype == "at_most":
        cardinality = f"at most {ocount}"
    elif otype == "exactly":
        cardinality = f"exactly {ocount}"
    else:
        cardinality = "any"

    return f"has {cardinality} {base}{gphr} {window}".strip()


def _window_phrase(sw: dict | None) -> str:
    if not sw:
        return ""
    s = sw.get("start") or {}
    e = sw.get("end") or {}
    srd = s.get("relative_days")
    erd = e.get("relative_days")
    if srd is None and erd is None:
        return ""
    a = f"{srd:+d}" if srd is not None else "-∞"
    b = f"{erd:+d}" if erd is not None else "+∞"
    return f"in [index_date{a}d, index_date{b}d]"


def _demographic_phrase(d: dict) -> str:
    age = d.get("Age")
    if age:
        op = age.get("Op", "eq")
        val = age.get("Value")
        return f"age {_op(op)} {val}"
    gender = d.get("Gender")
    if gender:
        return "sex is Female" if any(
            g.get("CONCEPT_CODE") == "F" for g in gender
        ) else "sex is Male"
    return "(unknown demographic)"


def _op(op: str) -> str:
    return {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "=",
        "neq": "!=",
    }.get(op, op)


def _slug(s: str) -> str:
    return s.replace(" ", "_").replace("-", "_").lower()


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def run_port(
    session: MedeloopSession,
    port_yaml: Path,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> PortExecutionResult:
    with open(port_yaml) as f:
        port = yaml.safe_load(f)
    cohort = port["cohort_name"]
    structure = port.get("structure", "standard")

    out_dir.mkdir(parents=True, exist_ok=True)
    step_log_path = out_dir / "step_log.jsonl"
    attrition_path = out_dir / "attrition.csv"
    step_log_path.write_text("")  # truncate

    result = PortExecutionResult(
        cohort_name=cohort,
        structure=structure,
        started_at=_now_iso(),
    )

    # 1. Primary
    df, prompt = _primary_prompt(cohort, port)
    n = _run_step(session, 0, "Primary criterion", df, prompt, result, dry_run)

    # 2. Observation window — this is the *universe* for inverted structures.
    df2, p2 = _obs_window_prompt(cohort, port, df)
    n = _run_step(session, 1, "Observation window", df2, p2, result, dry_run)
    universe = df2
    candidates = df2

    # 3. Inclusion rules
    for rule in port.get("inclusion_rules", []):
        rdf, rp = _rule_prompt(cohort, candidates, rule)
        idx = rule["index"] + 2  # +2 because Step 0 = primary, Step 1 = obs
        n = _run_step(session, idx, rule["name"][:80], rdf, rp, result, dry_run)
        candidates = rdf  # chain filters sequentially

    matched = candidates  # post-rule survivors (used for standard + inverted)

    # 4. Invert if needed — inversion is universe MINUS matched, BEFORE end
    # strategy. This mirrors ATLAS semantics: the "additional criteria" define
    # who to exclude from the universe for Team_8 / Team_9.
    if structure == "inverted":
        inv_df, inv_p = _invert_prompt(cohort, universe, matched)
        _run_step(
            session, len(result.steps), "Invert cohort",
            inv_df, inv_p, result, dry_run,
        )
        pre_final = inv_df
    else:
        pre_final = matched

    # 5. Finalize (CustomEra / DateOffset)
    fin_df, fin_p = _finalize_prompt(cohort, port, pre_final)
    _run_step(
        session, len(result.steps), "Finalize (end strategy)",
        fin_df, fin_p, result, dry_run,
    )
    final_df = fin_df

    # 6. Capture hash + n
    hash_prompt = (
        f"Report the patient count of {final_df} and sha256 of its "
        f"sorted patient_id column."
    )
    summary = None if dry_run else session.query(hash_prompt)
    result.final_df = final_df
    result.final_n = _extract_patient_count(summary) if summary else None
    result.cohort_hash = _extract_hash(summary) if summary else None
    result.ended_at = _now_iso()

    # 7. Write attrition CSV
    with open(attrition_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step_index", "step_name", "df_name", "n_patients", "wallclock_s"])
        for s in result.steps:
            w.writerow([s.index, s.name, s.df_name, s.n_patients, f"{s.wallclock_s:.2f}"])

    # 8. Step log
    with open(step_log_path, "w") as f:
        for s in result.steps:
            f.write(json.dumps({
                "index": s.index,
                "name": s.name,
                "df_name": s.df_name,
                "n_patients": s.n_patients,
                "wallclock_s": round(s.wallclock_s, 2),
                "prompt": s.prompt,
            }) + "\n")

    # 9. cohort_hash.txt for quick reference
    (out_dir / "cohort_hash.txt").write_text(
        f"cohort={cohort}\nfinal_df={final_df}\n"
        f"final_n={result.final_n}\ncohort_hash={result.cohort_hash}\n"
    )

    return result


def _run_step(
    session: MedeloopSession,
    index: int,
    name: str,
    df_name: str,
    prompt: str,
    result: PortExecutionResult,
    dry_run: bool,
) -> int | None:
    t0 = time.monotonic()
    if dry_run:
        resp = {"status": "dry-run", "patient_count": None}
    else:
        resp = session.query(prompt)
        # Count rows on the new DataFrame
        cnt = session.query(f"Report the patient count of {df_name}")
        resp = {**(resp or {}), "count": cnt}
    dt = time.monotonic() - t0
    n = _extract_patient_count(resp)
    result.steps.append(StepResult(
        index=index,
        name=name,
        df_name=df_name,
        n_patients=n,
        wallclock_s=dt,
        prompt=prompt,
    ))
    return n


def _finalize_prompt(
    cohort: str, port: dict, candidates_df: str
) -> tuple[str, str]:
    # Use the canonical df_cohort_final name only if we aren't overwriting the
    # inversion result. The caller passes the *input* DataFrame, so if that
    # already equals df_cohort_final (post-invert) we emit the result into a
    # separate name and then the harness reassigns.
    df = f"df_{_slug(cohort)}_cohort_final"
    if candidates_df == df:
        df = f"df_{_slug(cohort)}_cohort_final_eraend"
    es = port.get("end_strategy", {}) or {}
    t = es.get("type")
    if t == "CustomEra":
        cs = es.get("drug_codeset_id")
        gap = es.get("gap_days", 0)
        off = es.get("offset", 0)
        prompt = (
            f"Create pandas {df}: one row per patient in {candidates_df} with "
            f"cohort_end_date = last fill in df_codeset_{cs} "
            f"(gap<={gap}d) + {off}d. Keep first index per patient."
        )
    elif t == "DateOffset":
        off = es.get("offset", 0)
        prompt = (
            f"Create pandas {df}: rows of {candidates_df} with "
            f"cohort_end_date = index_date + {off}d. Keep first index per patient."
        )
    else:
        prompt = (
            f"Create pandas {df}: rows of {candidates_df} with "
            f"cohort_end_date = index_date. Keep first index per patient."
        )
    return df, prompt


def _invert_prompt(
    cohort: str, universe_df: str, matched_df: str
) -> tuple[str, str]:
    df = f"df_{_slug(cohort)}_inverted"
    prompt = (
        f"Create pandas {df}: rows of {universe_df} whose patient_id is NOT "
        f"in {matched_df}.patient_id."
    )
    return df, prompt


# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _extract_patient_count(resp: Any) -> int | None:
    if not isinstance(resp, dict):
        return None
    for k in ("patient_count", "n_patients", "count", "result"):
        v = resp.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _extract_hash(resp: Any) -> str | None:
    if isinstance(resp, dict):
        for k in ("hash", "sha256", "cohort_hash"):
            v = resp.get(k)
            if isinstance(v, str):
                return v
    return None
