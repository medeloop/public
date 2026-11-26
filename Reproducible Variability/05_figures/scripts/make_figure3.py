#!/usr/bin/env python3
# Figure3.png — two-panel strip plot across the three arms:
#   left  = FIDELITY (Jaccard of each run vs the reference cohort; 9 points/arm)
#   right = REPRODUCIBILITY (pairwise Jaccard between runs within an arm; 36 points/arm)
# Arm A = human team definitions (ss1) · Arm B = AI runs, original paper (ss2) · Arm C = AI runs, de-contradicted.
# One colour per arm. Values computed from the raw co-located cohorts in ../Cohorts (hardcoded here for speed).
import os as _os; _HERE=_os.path.dirname(_os.path.abspath(__file__))
import matplotlib; matplotlib.use("Agg")
matplotlib.rcParams.update({"pdf.fonttype":42,"ps.fonttype":42})
import matplotlib.pyplot as plt
import statistics as st, random
random.seed(1)

# --- fidelity: Jaccard vs reference cohort (9 per arm) ---
FID_A=[0.2098,0.2659,0.2588,0.0127,0.0,0.2852,0.1886,0.5082,0.3]
FID_B=[0.4611,0.222,0.4902,0.2215,0.4264,0.4501,0.481,0.4684,0.271]
FID_C=[1.0]*9
# --- reproducibility: within-arm pairwise Jaccard (36 per arm) ---
PW_A=[0.5172,0.1989,0.0115,0.0,0.1245,0.8433,0.3016,0.4044,0.1742,0.0035,0.0,0.1012,0.4614,0.2196,0.2663,
      0.01,0.0,0.2217,0.1731,0.2488,0.2832,0.0,0.0103,0.0129,0.0073,0.0129,0.0,0.0,0.0,0.0,0.1092,0.2836,
      0.2006,0.2722,0.4034,0.4728]
PW_B=[0.1898,0.8789,0.1887,0.8752,0.9438,0.8851,0.9479,0.2542,0.2046,0.9755,0.1926,0.1935,0.2015,0.1922,
      0.6997,0.2057,0.8161,0.863,0.9706,0.921,0.2838,0.1899,0.1938,0.2042,0.1911,0.7041,0.9228,0.8323,
      0.8782,0.2441,0.8829,0.9321,0.2497,0.9326,0.2802,0.2643]
PW_C=[1.0]*36

RED="#c0392b"; BLUE="#1f4e79"; TEAL="#2a9d8f"
rows=[(1,RED,"Human team definitions\n(Arm A)"),(2,BLUE,"AI runs — original paper\n(Arm B)"),(3,TEAL,"AI runs — de-contradicted\n(Arm C)")]

def strip(ax, data, jit, title, xlabel, extra_all9=False):
    for (y,c,_),vals in zip(rows,data):
        for v in vals:
            ax.scatter(v, y+random.uniform(-jit,jit), s=(70 if len(vals)==9 else 34),
                       color=c, alpha=(0.8 if len(vals)==9 else 0.45), zorder=3, edgecolors="none")
        m=st.median(vals)
        ax.plot([m,m],[y-0.30,y+0.30],color=c,lw=2,zorder=4)
        note=f"median {m:.3f}"
        ax.annotate(note,(m,y+0.36),ha="center",fontsize=8.5,color=c)
    ax.set_xlim(-0.02,1.10); ax.set_ylim(0.5,3.75); ax.set_xticks([0,0.2,0.4,0.6,0.8,1.0])
    ax.set_xlabel(xlabel); ax.set_title(title, fontsize=12)
    ax.grid(axis="x", alpha=.3)
    for sp in ["top","right"]: ax.spines[sp].set_visible(False)

fig,(ax1,ax2)=plt.subplots(1,2,figsize=(14.5,5.2),sharey=True)
fig.subplots_adjust(left=0.13, right=0.99, top=0.86, bottom=0.13, wspace=0.06)
strip(ax1,[FID_A,FID_B,FID_C],0.10,"Fidelity — vs the reference cohort","Jaccard index (run vs reference cohort)")
strip(ax2,[PW_A,PW_B,PW_C],0.12,"Reproducibility — run to run","Pairwise Jaccard index (run vs run)")
ax1.set_yticks([1,2,3]); ax1.set_yticklabels([r[2] for r in rows])
fig.suptitle("Reproduction of the reference cohort across the three arms", fontsize=14, y=0.965)
fig.savefig(_HERE+"/Figure3.pdf")
fig.savefig(_HERE+"/Figure3.png",dpi=600); plt.close()
print("saved Figure3.png")
