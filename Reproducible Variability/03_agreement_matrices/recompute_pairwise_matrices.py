#!/usr/bin/env python3
# Recomputes fidelity + 36-pair pairwise Jaccard matrices for all three arms
# directly from the raw co-located cohorts in phase3/Cohorts/.
# Usage: python3 recompute_pairwise_matrices.py <path-to-phase3/Cohorts>
# Writes pairwise_matrix_arm{A,B,C}.csv + pairwise_matrices_all_arms.json to phase3/.
# Validated 2026-11-01: Arm A reproduces archived jaccard_matrix.csv 36/36;
# Arm B reproduces the hardcoded values in figures/make_jaccard_3arms_v2.py 36/36.
import zipfile, re, sys, os, itertools, statistics as st, csv, json
D=sys.argv[1]
def docx_ids(p):
    xml=zipfile.ZipFile(p).read('word/document.xml').decode('utf8')
    txt=re.sub(r'<[^>]+>',' ',xml)
    return set(re.findall(r'\b[0-9a-f]{32}\b',txt))
def pq_ids(p):
    import pandas as pd
    df=pd.read_parquet(p); col=[c for c in df.columns if 'patient' in c.lower()][0]
    return set(df[col].astype(str))
C={}
C['master']=docx_ids(f'{D}/master_cohort_patient_ids.docx')
for i in range(1,10):
    C[f'B{i}']=docx_ids(f'{D}/agent{i}_cohort_patient_ids.docx')
    C[f'C{i}']=docx_ids(f'{D}/ss3_agent{i}_cohort_patient_ids.docx')
    C[f'A{i}']=pq_ids(f'{D}/team_{i}_final_cohort.parquet')
def J(a,b):
    A,B=C[a],C[b]; u=len(A|B)
    return len(A&B)/u if u else 1.0
print("SIZES  master=%d"%len(C['master']))
for arm in 'ABC':
    print(f"  Arm {arm}: "+", ".join(f"{i}={len(C[arm+str(i)])}" for i in range(1,10)))
out={}
for arm in 'ABC':
    ks=[f'{arm}{i}' for i in range(1,10)]
    fid=[J('master',k) for k in ks]
    pw=[J(a,b) for a,b in itertools.combinations(ks,2)]
    out[arm]={'fidelity':fid,'pairwise':pw}
    print(f"\nARM {arm}")
    print(f"  fidelity  median {st.median(fid):.4f}  range {min(fid):.4f}-{max(fid):.4f}")
    print(f"  pairwise  median {st.median(pw):.4f}  range {min(pw):.4f}-{max(pw):.4f}  (n={len(pw)})")
    with open(f'{D}/../pairwise_matrix_arm{arm}.csv','w',newline='') as f:
        w=csv.writer(f); w.writerow(['']+ks)
        for a in ks: w.writerow([a]+[f"{1.0 if a==b else J(a,b):.6f}" for b in ks])
with open(f'{D}/../pairwise_matrices_all_arms.json','w') as f: json.dump(out,f,indent=1)
# Arm C exactness
ident=all(C['C1']==C[f'C{i}'] for i in range(1,10)) and C['C1']==C['master']
print(f"\nARM C EXACTNESS: all nine identical to each other AND to master = {ident}")
print("  symmetric differences vs master:", [len(C[f'C{i}']^C['master']) for i in range(1,10)])
