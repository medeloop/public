#!/usr/bin/env python3
# Revised (v2) Figure 1 for the Sub-study 3 re-run package — disambiguated to the master as-built.
# See ../substudy3_deviation_categorization.md. Output written next to this script.
import os as _os; _HERE=_os.path.dirname(_os.path.abspath(__file__))
import matplotlib; matplotlib.use("Agg")
matplotlib.rcParams.update({"pdf.fonttype":42,"ps.fonttype":42})
import matplotlib.pyplot as plt
import matplotlib.patches as mp
from matplotlib.patches import FancyBboxPatch
plt.rcParams.update({"font.size":9,"font.family":"DejaVu Sans"})
INCL="#2a9d8f"; EXCL="#e76f51"; ENR="#8d99ae"; ADD="#457b9d"; IDX="#d62828"
fig,ax=plt.subplots(figsize=(10,6.1))
rows=[
 ("Continuous enrollment — medical AND pharmacy, single record, not merged (≥365d)", -365, 0, ENR, "[-365, 0]"),
 ("Exposure washout — no prior (insulin-free) GLP-1RA; no prior insulin", -365, -1, EXCL, "[-365, -1]"),
 ("Medical-condition exclusions — T1D, CF, lung cancer, PE, PH,\nthyroid carcinoma, corticosteroid-requiring conditions", -365, -1, EXCL, "[-365, -1]"),
 ("Type 2 diabetes diagnosis required (≥1 dx)", -365, 0, INCL, "[-365, 0]"),
 ("CLRD required — inpatient dx OR ≥2 dx-dates OR dx + CLRD-drug", -365, 0, INCL, "[-365, 0]"),
 ("DPP-4I comparator washout", -365, 0, EXCL, "[-365, 0]"),
 ("Pregnancy exclusion — women only, diagnosis codes only", -180, 180, EXCL, "[-180, +180]"),
]
y=len(rows)
for lab,s,e,c,note in rows:
    ax.add_patch(FancyBboxPatch((s,y-0.34),e-s,0.68,boxstyle="round,pad=0,rounding_size=6",
                 mutation_aspect=0.02,fc=c,ec="none",alpha=0.9))
    ax.text(s-14,y,lab,ha="right",va="center",fontsize=8.1)
    ax.text((s+e)/2,y,note,ha="center",va="center",color="white",fontsize=7.4,fontweight="bold")
    y-=1
ax.annotate("",xy=(0,y),xytext=(-230,y),arrowprops=dict(arrowstyle="-|>",color=ADD,lw=2.4))
ax.text(-244,y,"Add-on antidiabetes drug active at index —\nfull antidiabetes set, dispensed before index, supply reaching day 0",ha="right",va="center",fontsize=8.1)
ax.plot([0,0],[y-0.6,len(rows)+0.6],color=IDX,lw=2,zorder=5)
ax.text(0,len(rows)+0.9,"INDEX (day 0) = earliest QUALIFYING insulin-free GLP-1RA dispensing (2021-01-01 to 2025-10-31)\nwith ≥365 days prior enrollment (single record); fallback to the next qualifying fill",ha="center",va="bottom",color=IDX,fontsize=8.2,fontweight="bold")
ax.set_xlim(-585,215); ax.set_ylim(y-0.7,len(rows)+2.2)
ax.set_xlabel("days relative to index date"); ax.set_xticks([-365,-180,0,180]); ax.set_yticks([])
for sp in ["top","right","left"]: ax.spines[sp].set_visible(False)
ax.set_title("Figure 1. Study design and timeline of baseline assessment windows",fontsize=10.5,pad=40)
ax.legend(handles=[mp.Patch(fc=INCL,label="inclusion (require)"),mp.Patch(fc=EXCL,label="exclusion"),
     mp.Patch(fc=ENR,label="enrollment/entry"),mp.Patch(fc=ADD,label="add-on")],
     loc="lower center",bbox_to_anchor=(0.5,1.005),ncol=4,frameon=False,fontsize=7.8)
plt.tight_layout()
foot=("Study period: index dates 2021-01-01 to 2025-10-31; clinical events (diagnoses, dispensings) assessed within 2020-01-01 to 2025-10-31.\n"
      "Day 0 = index. Exclusion windows end the day before index; the type 2 diabetes, CLRD, and DPP-4I windows include the index date.\n"
      "Diagnoses use ICD-10-qualified records, matched verbatim; pregnancy uses diagnosis codes only. All criteria are applied jointly (AND).\n"
      "Enrollment benefit type by substring: medical = value contains 'medical'; pharmacy = contains 'pharm' or 'rx' (one record may satisfy both).")
fig.text(0.5,-0.05,foot,ha="center",va="top",fontsize=7.0,style="italic",color="#444")
plt.savefig(_HERE+"/FigureS2.pdf",bbox_inches="tight",pad_inches=0.18)
plt.savefig(_HERE+"/FigureS2.png",dpi=600,bbox_inches="tight",pad_inches=0.18); plt.close()
print("saved FigureS2.png")
