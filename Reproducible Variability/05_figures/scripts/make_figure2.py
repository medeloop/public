#!/usr/bin/env python3
# Combined 3-panel overlap figure, v2 -> Figure2.png
#   A = human team definitions · B = AI runs (original paper) · C = AI runs (de-contradicted methods)
# v2 vs v1: wider bars (less inter-bar gap), tighter inter-panel spacing, and the shared legend
# moved INTO panel C's empty top-right corner — no reserved right margin, so the whole figure is
# more compact horizontally and prints larger / more legibly at a fixed journal width.
import os as _os; _HERE=_os.path.dirname(_os.path.abspath(__file__))
import matplotlib; matplotlib.use("Agg")
matplotlib.rcParams.update({"pdf.fonttype":42,"ps.fonttype":42})
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
plt.rcParams.update({"font.family":"DejaVu Sans"})
MASTER=17158
PUR="#440154"; TEAL="#21918c"; YEL="#fde725"
WIDTH=0.88; XLIM=(-0.55,8.55); YLIM=(0,90000); YTICKS=[0,20000,40000,60000,80000]; PCT_FS=7

def panel(ax, labels, ro, both, mo, J, letter, title, show_y):
    x=range(len(labels))
    ax.bar(x, ro,   width=WIDTH, color=PUR)
    ax.bar(x, both, width=WIDTH, bottom=ro, color=TEAL)
    ax.bar(x, mo,   width=WIDTH, bottom=[r+b for r,b in zip(ro,both)], color=YEL)
    for i in x:
        ax.text(i, ro[i]+both[i]+mo[i]+1200, f"{J[i]*100:.1f}%", ha="center", va="bottom", fontsize=PCT_FS)
    ax.set_xlim(*XLIM); ax.set_ylim(*YLIM); ax.set_yticks(YTICKS)
    ax.tick_params(axis="both", labelsize=10)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, rotation=90)
    if show_y:
        ax.set_ylabel("Number of subjects", fontsize=12)
    else:
        ax.tick_params(labelleft=False)
    ax.set_title(title, fontsize=12)
    ax.text(0.02, 0.98, letter, transform=ax.transAxes, fontsize=14, fontweight="bold", va="top", ha="left")
    ax.grid(axis="y", color="#e9e9e9", lw=0.9); ax.set_axisbelow(True)
    for sp in ["top","right"]: ax.spines[sp].set_visible(False)

fig,(axA,axB,axC)=plt.subplots(1,3,figsize=(13.0,5.2),sharey=True)
fig.subplots_adjust(left=0.065, right=0.985, top=0.86, bottom=0.20, wspace=0.05)

# Panel A — human team definitions
h_sz=[73560,41020,14886,17995,2614,9155,83706,31381,45329]
h_in=[15729,12220,6589,441,0,5839,16003,16355,14420]
panel(axA,[f"Team {i}" for i in range(1,10)],
      [s-i for s,i in zip(h_sz,h_in)], list(h_in), [MASTER-i for i in h_in],
      [i/(s+MASTER-i) for s,i in zip(h_sz,h_in)], "A", "Human team definitions", True)

# Panel B — AI runs, original paper
a_sz=[13509,66824,14915,67115,13879,13269,14762,13809,52056]
a_in=[9678,15255,10550,15282,9278,9445,10367,9878,14756]
panel(axB,[f"Agent {i}" for i in range(1,10)],
      [s-i for s,i in zip(a_sz,a_in)], list(a_in), [MASTER-i for i in a_in],
      [i/(s+MASTER-i) for s,i in zip(a_sz,a_in)], "B", "AI runs — original paper", False)

# Panel C — AI runs, de-contradicted methods (all patient-identical to master)
panel(axC,[f"Agent {i}" for i in range(1,10)],
      [0]*9, [MASTER]*9, [0]*9, [1.0]*9, "C", "AI runs — de-contradicted methods", False)

# Shared legend inside panel C's empty top-right corner (white fill masks the gridlines, no border)
axC.legend(handles=[Patch(fc=YEL,label="Reference cohort only"),Patch(fc=TEAL,label="Both"),
                    Patch(fc=PUR,label="Reproduction only")], title="Cohort",
           loc="upper right", frameon=True, facecolor="white", edgecolor="none",
           framealpha=1.0, fontsize=11, title_fontsize=12)
fig.suptitle("Cohort overlap with the reference cohort, by arm", fontsize=15, y=0.965)
fig.savefig(_HERE+"/Figure2.pdf")
fig.savefig(_HERE+"/Figure2.png", dpi=600)
plt.close()
from PIL import Image
print("saved Figure2.png", Image.open(_HERE+"/Figure2.png").size)
