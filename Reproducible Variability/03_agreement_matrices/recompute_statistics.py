#!/usr/bin/env python3
"""
recompute_statistics.py - reproduces every statistical result reported in the
article from deposited aggregate data alone. No patient-level records are needed.

    python3 recompute_statistics.py [pairwise_all_runs.json]

Input is the 27 x 27 aggregate matrix of between-reproduction Jaccard indices and
each reproduction's Jaccard index against the reference cohort. Both are indices
computed from cohort membership; neither discloses membership.
"""
import json, sys, itertools, statistics as st
from pathlib import Path
import numpy as np
from scipy import stats

SEED = 20261101          # fixed so the permutation p values are reproducible
NPERM = 50_000
ARMS = {"A": "Human team definitions", "B": "AI runs, original paper",
        "C": "AI runs, de-contradicted methods"}

src = Path(sys.argv[1] if len(sys.argv) > 1 else "pairwise_all_runs.json")
D = json.loads(src.read_text())
runs, M, FID = D["runs"], D["matrix"], D["fidelity"]
members = {a: [f"{a}{i}" for i in range(1, 10)] for a in ARMS}
fid = {a: [FID[r] for r in members[a]] for a in ARMS}
within = {a: [M[x][y] for x, y in itertools.combinations(members[a], 2)] for a in ARMS}
mean_pw = {a: [st.mean(M[r][o] for o in members[a] if o != r) for r in members[a]] for a in ARMS}

def cliffs(x, y):
    x, y = np.asarray(x), np.asarray(y)
    return float((np.sign(x[:, None] - y[None, :]).sum()) / (len(x) * len(y)))

def holm(ps):
    idx = np.argsort(ps); out = np.empty(len(ps)); run = 0.0
    for k, i in enumerate(idx):
        run = max(run, (len(ps) - k) * ps[i]); out[i] = min(run, 1.0)
    return out

print("=" * 72); print("FIDELITY TO THE REFERENCE COHORT  (9 values per arm)"); print("=" * 72)
for a in ARMS:
    print(f"  Arm {a}  median {st.median(fid[a]):.3f}   range {min(fid[a]):.3f}-{max(fid[a]):.3f}   {ARMS[a]}")
H, p_kw = stats.kruskal(*[fid[a] for a in ARMS])
print(f"\n  Kruskal-Wallis            H = {H:.3f}   p = {p_kw:.2e}")

rng = np.random.default_rng(SEED)
def jt(groups):
    return sum((np.sign(np.asarray(groups[j])[:, None] - np.asarray(groups[i])[None, :]).sum()
                + len(groups[i]) * len(groups[j])) / 2
               for i, j in itertools.combinations(range(len(groups)), 2))
obs = jt([fid[a] for a in ARMS]); pool = np.concatenate([fid[a] for a in ARMS])
cnt = sum(jt(np.split(rng.permutation(pool), 3)) >= obs for _ in range(NPERM))
print(f"  Jonckheere-Terpstra       JT = {obs:.0f}   p = {(cnt + 1) / (NPERM + 1):.2e}  (ordered A < B < C)")

pairs = [("A", "B"), ("A", "C"), ("B", "C")]
raw = [stats.mannwhitneyu(fid[x], fid[y], alternative="two-sided").pvalue for x, y in pairs]
print("\n  Pairwise Mann-Whitney U, Holm-adjusted:")
for (x, y), p, pa in zip(pairs, raw, holm(raw)):
    print(f"    Arm {x} vs Arm {y}   p = {p:.4f}   Holm p = {pa:.4f}   Cliff's delta = {cliffs(fid[y], fid[x]):+.2f}")

print("\n" + "=" * 72); print("REPRODUCIBILITY  (36 within-arm pairs per arm; the run is the unit)"); print("=" * 72)
for a in ARMS:
    print(f"  Arm {a}  median pairwise {st.median(within[a]):.3f}   range {min(within[a]):.3f}-{max(within[a]):.3f}")
print("\n  Label-permutation test on the within-group median pairwise Jaccard")
print(f"  (runs reassigned to arms at random; {NPERM:,} permutations, two-sided):")
for x, y in pairs:
    pooled = members[x] + members[y]
    def med_diff(g1, g2):
        return abs(st.median([M[i][j] for i, j in itertools.combinations(g1, 2)])
                 - st.median([M[i][j] for i, j in itertools.combinations(g2, 2)]))
    o = med_diff(members[x], members[y]); c = 0
    for _ in range(NPERM):
        pm = list(rng.permutation(pooled)); c += med_diff(pm[:9], pm[9:]) >= o
    print(f"    Arm {x} vs Arm {y}   observed difference {o:.3f}   p = {(c + 1) / (NPERM + 1):.1e}")
print("\n  Unit-level Mann-Whitney U on each run's mean pairwise Jaccard:")
for x, y in pairs:
    p = stats.mannwhitneyu(mean_pw[x], mean_pw[y], alternative="two-sided").pvalue
    print(f"    Arm {x} vs Arm {y}   p = {p:.2e}   Cliff's delta = {cliffs(mean_pw[y], mean_pw[x]):+.2f}")
print("\n  Arm C: all fidelity and all pairwise values exactly 1.000 ->",
      all(v == 1.0 for v in fid["C"] + within["C"]))
