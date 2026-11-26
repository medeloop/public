#!/usr/bin/env python3
# Two-panel overlap figure -> FigureS1.png / .pdf
#   A = the nine team cohorts as published by Ostropolets et al (2023), on that study's database
#   B = the same nine team definitions re-implemented here  (= panel A of fig4_combined_v2)
# Style copied verbatim from make_fig4_combined_v2.py so the two figures sit together in one set.
#
# Panel A inputs are all published values:
#   cohort sizes      Ostropolets et al, Supplementary Table 3, row "Total, n"
#   agreement (J)     Ostropolets et al, Figure 4 data labels (one decimal place)
#   master cohort     6196 (that study's main text; its Suppl Table 3 gives 6356)
# The shared segment is NOT published; it is derived from the two that are, via the Jaccard
# identity  |A and B| = J x (team n + master n) / (1 + J).  Panel B's shared segment is measured.
import os as _os; _HERE=_os.path.dirname(_os.path.abspath(__file__))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
plt.rcParams.update({"font.family":"DejaVu Sans"})

PUR="#440154"; TEAL="#21918c"; YEL="#fde725"
WIDTH=0.88; XLIM=(-0.55,8.55); YLIM=(0,90000); YTICKS=[0,20000,40000,60000,80000]; PCT_FS=7

def panel(ax, labels, ro, both, mo, pct, letter, title, show_y):
    x=range(len(labels))
    ax.bar(x, ro,   width=WIDTH, color=PUR)
    ax.bar(x, both, width=WIDTH, bottom=ro, color=TEAL)
    ax.bar(x, mo,   width=WIDTH, bottom=[r+b for r,b in zip(ro,both)], color=YEL)
    for i in x:
        ax.text(i, ro[i]+both[i]+mo[i]+1200, pct[i], ha="center", va="bottom", fontsize=PCT_FS)
    ax.set_xlim(*XLIM); ax.set_ylim(*YLIM); ax.set_yticks(YTICKS)
    ax.tick_params(axis="both", labelsize=10)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=90)
    if show_y: ax.set_ylabel("Number of subjects", fontsize=12)
    else:      ax.tick_params(labelleft=False)
    ax.set_title(title, fontsize=12)
    ax.text(0.02, 0.98, letter, transform=ax.transAxes, fontsize=14, fontweight="bold", va="top", ha="left")
    ax.grid(axis="y", color="#e9e9e9", lw=0.9); ax.set_axisbelow(True)
    for sp in ["top","right"]: ax.spines[sp].set_visible(False)

fig,(axA,axB)=plt.subplots(1,2,figsize=(9.2,5.8),sharey=True)
fig.subplots_adjust(left=0.095, right=0.985, top=0.82, bottom=0.26, wspace=0.05)

# ---------------- Panel A: as published ----------------
P_MASTER=6196
p_sz=[43641,18701,11260,8417,3126,2159,63619,12618,31253]      # Suppl Table 3, "Total, n"
p_J  =[0.128,0.153,0.161,0.008,None,0.153,0.094,0.354,0.172]   # Figure 4 data labels
p_in=[0 if j is None else j*(s+P_MASTER)/(1+j) for s,j in zip(p_sz,p_J)]
p_pct=["<0.1%" if j is None else f"{j*100:.1f}%" for j in p_J]
for s,i in zip(p_sz,p_in):                                     # sanity: shared <= min(team, master)
    assert i <= min(s,P_MASTER)+1, (s,i)
panel(axA,[f"Team {i}" for i in range(1,10)],
      [s-i for s,i in zip(p_sz,p_in)], list(p_in), [P_MASTER-i for i in p_in],
      p_pct, "A", "As published by Ostropolets et al\nreference cohort 6196", True)

# ---------------- Panel B: re-implemented here ----------------
MASTER=17158
h_sz=[73560,41020,14886,17995,2614,9155,83706,31381,45329]
h_in=[15729,12220,6589,441,0,5839,16003,16355,14420]           # measured, not derived
h_J =[i/(s+MASTER-i) for s,i in zip(h_sz,h_in)]
panel(axB,[f"Team {i}" for i in range(1,10)],
      [s-i for s,i in zip(h_sz,h_in)], list(h_in), [MASTER-i for i in h_in],
      [f"{j*100:.1f}%" for j in h_J], "B", "Re-implemented on this database\nreference cohort 17 158", False)

fig.legend(handles=[Patch(fc=YEL,label="Reference cohort only"),Patch(fc=TEAL,label="Both"),
                    Patch(fc=PUR,label="Reproduction only")],
           loc="lower center", bbox_to_anchor=(0.54,0.005), ncol=3, frameon=False,
           fontsize=11, handlelength=1.4, columnspacing=2.2)
fig.suptitle("The same nine team definitions, as published and re-implemented here", fontsize=14, y=0.975)
for ext,kw in (("png",{"dpi":600}),("pdf",{})):
    fig.savefig(f"{_HERE}/FigureS1.{ext}", **kw)
plt.close()
from PIL import Image
print("saved FigureS1.png", Image.open(_HERE+"/FigureS1.png").size)
print("derived shared counts (panel A):", [round(i) for i in p_in])
print("panel A medians  J:", sorted(j for j in p_J if j)[4], " panel B median J:", sorted(h_J)[4])
