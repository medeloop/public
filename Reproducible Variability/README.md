# Public repository collateral

Supporting artefacts for *Reproducible variability: assessing human vs. AI discordance in
attempting to reproduce the same observational study*.

Verified 2026-11-25: the 20 code sets pass their checksum check, every published figure
regenerates byte-identically from the scripts here, and every statistical result in the
article recomputes from the deposited aggregate data with no access to patient-level records.

---

## Contents

| Folder | What it holds |
|---|---|
| `01_port_implementations/` | The ten deterministic re-implementations — `ports/master_port.py` (the reference definition) plus `team_1`–`team_9` — with the runner and the two execution scripts |
| `02_frozen_codesets/` | The 20 frozen code sets, 38 935 codes, plus `verify_codebook.py` |
| `03_agreement_matrices/` | Per-reproduction cohort sizes, fidelity and pairwise Jaccard indices for all 27 reproductions, and the scripts that derive them and recompute every reported statistic |
| `04_run_times/` | Wall-clock run time for each of the 27 reproductions, behind Supplementary Table S4 |
| `05_figures/` | The published figures and the scripts that generate them |

---

## A note on the database name

The claims database is named **HealthVerity Base** in the article. HealthVerity renamed it from
*Foundation* to *Base* after these runs were executed, so the code set files, the port
implementations and their checksum manifests still carry `verityfoundation` in their filenames and
`dataset_name` fields. Those names are left exactly as the platform produced them: renaming them
would break the checksums that bind the ports to the code sets, and would misrepresent what was
actually run. Same database, same codes, earlier name.

## Verifying the code sets

```
cd 02_frozen_codesets
python3 verify_codebook.py        # expects: present: 20 / 20   problems: 0   RESULT: OK
```

Every port implementation asserts the same code count and SHA-256 checksum for each code set
at load time and refuses to run on a mismatch. Passing this check establishes that the lists
published here are the ones the reported cohorts were actually built from.

## Regenerating the figures

```
cd 05_figures/scripts
python3 make_figure1.py           # Figure 1, from figure_data.json
python3 make_figure2.py           # Figure 2
python3 make_figure3.py           # Figure 3
python3 make_figure4.py           # Figure 4
python3 make_figureS1.py          # Supplementary Figure S1
python3 make_figureS2.py          # Supplementary Figure S2
python3 make_figureS3.py          # Supplementary Figure S3
```

Requires Python 3.10+ with `matplotlib`, `numpy` and `pillow`. Each script writes only the
figure it is named for; together they produce exactly the seven figures published with the
article and nothing else. `make_figure1.py` and `make_figure4.py` carry accessibility verifiers that
checks the 12 pt minimum type size, that no text is clipped or overlapping, and that no
study-internal shorthand appears in any label; it exits non-zero on failure.

Figure 1 reads its values from `figure_data.json`. Figures 2, 3, 4 and S1 to S3 carry their
values inline, at the top of each script.

## Recomputing the statistics

```
cd 03_agreement_matrices
python3 recompute_statistics.py pairwise_all_runs.json
```

Reproduces every statistical result reported in the article — the Kruskal-Wallis and
Jonckheere-Terpstra tests on fidelity, the Holm-corrected pairwise Mann-Whitney contrasts
with Cliff's delta, and both reproducibility tests — from `pairwise_all_runs.json` alone.
That file holds each reproduction's Jaccard index against the reference cohort and the full
27 x 27 matrix of between-reproduction Jaccard indices. `cohort_sizes_and_fidelity.csv` gives, for
each of the 27, its cohort size, the number of patients it shares with the reference cohort, and the
resulting Jaccard index; every index in it reproduces from the two counts beside it. These are agreement indices computed
from cohort membership; they disclose no membership, so no patient-level access is required.
Requires Python 3.10+ with `numpy` and `scipy`.

The two permutation tests are seeded (`SEED` at the top of the script) so their p values are
reproducible; at these magnitudes a different seed moves the last significant figure.

## Rebuilding the agreement matrices from cohort membership

`recompute_pairwise_matrices.py` derives the indices in `pairwise_all_runs.json` from the
underlying cohorts. That data is licensed from HealthVerity and is not redistributable, so
the script is included as the audit trail for how the deposited matrices were produced
rather than as a runnable step. Its Arm A output reproduces the independently archived
`pairwise_armA_human_teams__archived.csv` on all 36 pairs.

## Running the port implementations

The ports execute against the claims database through the platform runner in
`01_port_implementations/runner/`. Reproducing them requires a HealthVerity licence and the same
database snapshot. Each port asserts the code count and SHA-256 checksum of every code set it loads
and refuses to run on a mismatch, and prints a logic fingerprint identifying the definition it
implements. The cohort each one produced is recorded in
`03_agreement_matrices/cohort_sizes_and_fidelity.csv`.
