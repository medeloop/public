#!/usr/bin/env python3
# Revised (v2) Figure 2 for the Sub-study 3 re-run package — disambiguated to the master as-built.
# See ../substudy3_deviation_categorization.md. Output written next to this script.
import os as _os; _HERE=_os.path.dirname(_os.path.abspath(__file__))
import matplotlib; matplotlib.use("Agg")
matplotlib.rcParams.update({"pdf.fonttype":42,"ps.fonttype":42})
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams.update({"font.size":9,"font.family":"DejaVu Sans"})
INCL="#2a9d8f"; EXCL="#e76f51"; ENR="#8d99ae"; ADD="#457b9d"; IDX="#d62828"

fig,ax=plt.subplots(figsize=(9.8,6.7)); ax.axis("off"); ax.set_xlim(0,10); ax.set_ylim(0,10)
def box(x,y,w,h,text,fc,fs=8.2,tc="white",ec="#333"):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.02,rounding_size=0.06",fc=fc,ec=ec,lw=1.2))
    ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=fs,color=tc)
def arrow(x1,y1,x2,y2):
    ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle="-|>",mutation_scale=14,color="#555",lw=1.5))
box(1.4,8.95,7.2,1.05,"Cohort entry (index): earliest QUALIFYING insulin-free GLP-1RA dispensing, 2021-01-01 to 2025-10-31\n(≥365 days continuous medical AND pharmacy enrollment, single record each; fallback to next qualifying fill)",ENR,fs=7.4,tc="white")
arrow(5,8.95,5,8.55)
box(0.3,5.5,4.5,2.9,"Include only if all hold\n\nadult (age > 17 at index)\n≥1 type 2 diabetes diagnosis\nCLRD: inpatient dx  OR  ≥2 dx-dates\n        OR  (dx AND CLRD drug)\nreceiving add-on antidiabetes therapy\n        (drug active at index)",INCL,fs=8.0,tc="white")
box(5.2,4.9,4.5,3.5,"Exclude if any hold\n\nprior GLP-1RA (baseline year)\ntype 1 diabetes\ncystic fibrosis / lung cancer / PE / PH\nthyroid carcinoma\nconditions requiring chronic\n        systemic corticosteroids\npregnancy (women; diagnosis codes only)\nprior DPP-4I\nprior insulin",EXCL,fs=8.0,tc="white")
arrow(2.5,5.5,3.4,4.35); arrow(7.5,4.9,6.6,4.35)
box(3.0,3.25,4,0.95,"GLP-1RA new-user cohort\n(meets all inclusion, no exclusion)",IDX,fs=8.4,tc="white")
ax.text(5,2.5,"All criteria are applied jointly (AND); order of application does not affect cohort membership.\nEach concept is ascertained from its predefined set; diagnoses use ICD-10-qualified records; pregnancy uses diagnosis codes only.",
        ha="center",va="center",fontsize=7.2,style="italic",color="#444")
ax.set_title("Figure 2. Cohort selection",fontsize=10.5)
plt.tight_layout(); plt.savefig(_HERE+"/FigureS3.pdf",bbox_inches="tight")
plt.savefig(_HERE+"/FigureS3.png",dpi=600,bbox_inches="tight"); plt.close()
print("saved FigureS3.png")
