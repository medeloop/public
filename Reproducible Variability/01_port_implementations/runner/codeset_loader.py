"""Load the 22 frozen concept-set CSVs into named Medeloop DataFrames.

Each codeset becomes a single DataFrame named `df_codeset_<id>`. Multi-
vocabulary codesets get multiple columns — one per target table so the
executor can reference the codeset in any claim-table filter:

    ndc_code          → pharmacy_claims
    diagnosis_code    → diagnosis        (ICD-10-CM, dot-stripped)
    procedure_code    → procedure        (CPT / HCPCS)
    observation_code  → (reserved; HV has no measurement table per DEV-004)
    visit_bucket      → {IP, ER, ERIP, OP}

Codes come verbatim from `phase1/concept_sets/codeset_<id>_<slug>.csv`.
No semantic expansion — Sub-study 1 must stay deterministic.

Rows whose vocabulary is tagged as unused in the concept-set translation
(e.g. "LOINC (unused — no measurement table)", "ICD9Proc") are dropped and
counted in the returned spec for auditability.
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .mcp import MedeloopSession


# Target columns per source vocabulary.
_VOCAB_TO_COL: dict[str, str] = {
    "NDC": "ndc_code",
    "ICD10CM": "diagnosis_code",
    "CPT4": "procedure_code",
    "CPT": "procedure_code",
    "HCPCS": "procedure_code",
    "Visit": "visit_bucket",
}

# Vocabularies we intentionally drop (no Medeloop table).
_UNUSED_VOCABS = (
    "LOINC (unused",        # prefix-match; Ostropolets translation tagged these
    "ICD9Proc",             # HV data post-dates ICD-9 transition
    "LOINC",                # bare LOINC rows also unused
)

# Visit concept codes → bucket.
_VISIT_BUCKETS = {"IP": "IP", "ER": "ER", "ERIP": "ERIP", "OP": "OP"}


@dataclass(frozen=True)
class CodesetSpec:
    codeset_id: int
    csv_path: Path
    # {column_name: tuple(codes)} preserving CSV order, de-duplicated per column.
    columns: OrderedDict
    dropped: dict[str, int] = field(default_factory=dict)

    @property
    def total_codes(self) -> int:
        return sum(len(v) for v in self.columns.values())


def code_column_for(vocab: str) -> str | None:
    """Return the Medeloop column name for a source vocabulary, or None if
    the vocabulary is intentionally unused."""
    if any(vocab.startswith(p) for p in _UNUSED_VOCABS):
        return None
    return _VOCAB_TO_COL.get(vocab)


# ---------------------------------------------------------------------------


def collect_codeset_specs(concept_sets_dir: Path) -> list[CodesetSpec]:
    """Scan `phase1/concept_sets/` and return one CodesetSpec per CSV."""
    specs: list[CodesetSpec] = []
    for csv_path in sorted(concept_sets_dir.glob("codeset_*.csv")):
        codeset_id = int(csv_path.name.split("_")[1])
        columns, dropped = _extract_codes(csv_path)
        specs.append(
            CodesetSpec(
                codeset_id=codeset_id,
                csv_path=csv_path,
                columns=columns,
                dropped=dropped,
            )
        )
    return specs


def _extract_codes(csv_path: Path) -> tuple[OrderedDict, dict[str, int]]:
    """Read `target_code` column; bucket by target column; dot-strip ICD-10;
    bucketise visits."""
    buckets: OrderedDict[str, list[str]] = OrderedDict()
    dropped: dict[str, int] = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("role", "included") != "included":
                continue
            vocab = row["target_vocabulary"]
            col = code_column_for(vocab)
            if col is None:
                dropped[vocab] = dropped.get(vocab, 0) + 1
                continue
            code = row["target_code"]
            if vocab == "ICD10CM":
                code = code.replace(".", "")
            if vocab == "Visit":
                code = _VISIT_BUCKETS.get(code, code)
            buckets.setdefault(col, []).append(code)
    # Stable de-dup within each column.
    out: OrderedDict[str, tuple[str, ...]] = OrderedDict()
    for col, codes in buckets.items():
        seen: set[str] = set()
        deduped: list[str] = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                deduped.append(c)
        out[col] = tuple(deduped)
    return out, dropped


# ---------------------------------------------------------------------------


def _chunked(codes: Iterable[str], max_chars: int) -> Iterator[list[str]]:
    """Yield successive chunks whose quoted-and-comma-joined length fits in
    `max_chars`."""
    buf: list[str] = []
    used = 0
    for c in codes:
        nxt = used + len(c) + 4  # ~ quote + quote + comma + space
        if buf and nxt > max_chars:
            yield buf
            buf = []
            used = 0
        buf.append(c)
        used += len(c) + 4
    if buf:
        yield buf


# ---------------------------------------------------------------------------


def df_name_for(codeset_id: int, column: str, multi: bool) -> str:
    """Canonical DataFrame name for a codeset-column.

    Single-column codesets use `df_codeset_<id>` (keeps harness references
    unchanged). Multi-column codesets use `df_codeset_<id>_<column>` so each
    column becomes its own independent DataFrame — this avoids the pandas
    length-mismatch trap that would occur if we tried to cram columns of
    different lengths into a single DataFrame.
    """
    if multi:
        return f"df_codeset_{codeset_id}_{column}"
    return f"df_codeset_{codeset_id}"


def bootstrap_codeset(
    session: MedeloopSession,
    spec: CodesetSpec,
    *,
    skeleton_overhead_chars: int = 120,
    hard_cap_chars: int = 350,
    logger: Callable[[str], None] | None = None,
) -> int:
    """Bootstrap the DataFrame(s) for a codeset.

    Single-column codesets produce `df_codeset_<id>`; multi-column codesets
    produce one DataFrame per column (`df_codeset_<id>_<column>`). In both
    cases each DataFrame is built with `create` + zero-or-more `append` +
    one `dedup` prompt.

    Returns the number of `execute_query` calls made.
    """
    log = logger or (lambda _msg: None)
    code_budget = hard_cap_chars - skeleton_overhead_chars
    n_calls = 0
    multi = len(spec.columns) > 1

    for column, codes in spec.columns.items():
        df_name = df_name_for(spec.codeset_id, column, multi)
        chunks = list(_chunked(codes, code_budget))
        for i, chunk in enumerate(chunks):
            csv_chunk = ", ".join(f"'{c}'" for c in chunk)
            if i == 0:
                prompt = (
                    f"Create pandas DataFrame {df_name} with column "
                    f"{column} from values: {csv_chunk}"
                )
            else:
                prompt = (
                    f"Append to {df_name} rows with {column} in: {csv_chunk}"
                )
            session.query(prompt)
            n_calls += 1
            log(
                f"  codeset {spec.codeset_id} col '{column}' chunk "
                f"{i + 1}/{len(chunks)} ({len(chunk)} codes, {len(prompt)} chars)"
            )
        # In-place dedup — explicit reassignment prevents the model from
        # creating a sibling `<name>_dedup` DataFrame.
        session.query(
            f"Reassign {df_name} = {df_name}.drop_duplicates("
            f"subset=['{column}'], keep='first').reset_index(drop=True). "
            f"Print {df_name}.shape."
        )
        n_calls += 1
    return n_calls


def bootstrap_all_codesets(
    session: MedeloopSession,
    specs: list[CodesetSpec],
    *,
    logger: Callable[[str], None] | None = None,
) -> dict[int, int]:
    """Call `bootstrap_codeset` for every spec. Returns {codeset_id: n_calls}."""
    log = logger or print
    result: dict[int, int] = {}
    for spec in specs:
        cols = ", ".join(f"{c}={len(v)}" for c, v in spec.columns.items())
        log(
            f"→ codeset {spec.codeset_id} ({spec.total_codes} codes; "
            f"columns {cols}; dropped {spec.dropped or '0'})"
        )
        result[spec.codeset_id] = bootstrap_codeset(session, spec, logger=log)
    return result
