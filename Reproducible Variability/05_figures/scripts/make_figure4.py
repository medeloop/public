#!/usr/bin/env python3
"""
make_figure4.py - regenerates Figure 4 of the JAMIA "Research and Applications"
submission: the decision tree of the two interpretive forks that separated the
nine Arm B agent runs.

    python3 make_figure4.py            # writes Figure4.pdf and Figure4.png

Design rules, shared with Figure 1 and enforced by the verifier at the bottom:

  * Authored at 7.0 in wide, the journal's reproduction width, and rendered 1:1,
    so every in-figure point size IS its printed point size.
  * 12 pt floor on all text, set in rcParams and asserted per figure.
  * Exported as vector PDF with embedded TrueType fonts (pdf.fonttype = 42) and
    as PNG at 600 dpi.
  * No meaning carried by colour alone: the tree structure and the text in every
    box carry the grouping; fill tone is redundant with depth.
  * Every filled shape has a near-black outline, so graphical objects keep
    >= 3:1 contrast against white even where the fill alone would not.
  * Arial-metric sans-serif (Liberation Sans falls back to Arial / Helvetica).
  * No study-internal shorthand in any label or annotation.

Values are tabulated inline below, under FORKS.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------- style
MIN_PT = 12.0
FIG_W = 7.0

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Liberation Sans", "Arial", "Helvetica", "DejaVu Sans"],
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "font.size": MIN_PT,
    "figure.titlesize": MIN_PT,
    "lines.solid_capstyle": "butt",
})

INK    = "#1a1a1a"
ROOT_F = "#d9d9d9"      # as Figure 1's source box
NODE_F = "#cfe0ee"      # as Figure 1's arm B box
LEAF_F = "#ffffff"      # as Figure 1's outcome box
LSP    = 1.30

TITLE = ("The nine AI runs in Arm B diverged on CLRD ascertainment\n"
         "and prior exposure washout")

# ---------------------------------------------------------------- tabulated
FORKS = [
    # leaf centre, parent centre, bold head, runs, Jaccard
    (11.5, 24.0, "One-year\nwashout",     "Runs 3, 7, 8", "0.468–0.490"),
    (36.5, 24.0, "All available\nhistory", "Runs 1, 5, 6", "0.426–0.461"),
    (63.5, 76.0, "One-year\nwashout",     "Run 9",        "0.271"),
    (88.5, 76.0, "All available\nhistory", "Runs 2, 4",    "0.222"),
]

fig = plt.figure(figsize=(FIG_W, 6.20))
ax = fig.add_axes([0.005, 0.008, 0.99, 0.878])
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")


def box(x, y, w, h, fc, title=None, body=None, body_dy=None):
    """Rounded node, Figure 1 styling: bold head line over a regular body."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.5",
        facecolor=fc, edgecolor=INK, linewidth=1.1, mutation_scale=1, zorder=2))
    if title is not None and body is not None:
        ax.text(x + w / 2, y + h - 2.0, title, ha="center", va="top",
                fontsize=MIN_PT, fontweight="bold", color=INK, zorder=3,
                linespacing=LSP)
        ax.text(x + w / 2, y + h - (body_dy or 11.0), body, ha="center", va="top",
                fontsize=MIN_PT, color=INK, zorder=3, linespacing=LSP)
    else:
        ax.text(x + w / 2, y + h / 2, title or body, ha="center", va="center",
                fontsize=MIN_PT, fontweight="bold", color=INK, zorder=3,
                linespacing=LSP)


def arrow(x0, y0, x1, y1):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                                 mutation_scale=13, linewidth=1.4, color=INK,
                                 zorder=1, shrinkA=0, shrinkB=0))


def bus(parent_cx, parent_bottom, child_cxs, child_top, bus_y):
    """Orthogonal fan-out, as Figure 1: drop, horizontal bus, drop into each child."""
    ax.plot([parent_cx, parent_cx], [parent_bottom, bus_y], color=INK, lw=1.4, zorder=1)
    ax.plot([min(child_cxs), max(child_cxs)], [bus_y, bus_y], color=INK, lw=1.4, zorder=1)
    for cx in child_cxs:
        arrow(cx, bus_y, cx, child_top + 0.4)


def fork_label(cy, text):
    ax.text(50, cy, text, ha="center", va="center", fontsize=MIN_PT,
            fontweight="bold", color=INK, zorder=5,
            bbox=dict(facecolor="#ffffff", edgecolor="none", pad=3.5))


# ------------------------------------------------------------------- layout
ROOT_Y, ROOT_H, ROOT_W = 88.0, 10.0, 36.0
MID_Y,  MID_H,  MID_W  = 56.0, 16.0, 44.0
LEAF_Y, LEAF_H, LEAF_W = 9.0,  28.0, 22.0
MID_CX = (24.0, 76.0)
BUS1, BUS2 = 79.5, 47.0

box(50 - ROOT_W / 2, ROOT_Y, ROOT_W, ROOT_H, ROOT_F, title="Nine AI runs (Arm B)")

fork_label(83.6, "Fork 1 — CLRD")
bus(50, ROOT_Y, MID_CX, MID_Y + MID_H, BUS1)

box(MID_CX[0] - MID_W / 2, MID_Y, MID_W, MID_H, NODE_F,
    title="Diagnosis required", body="6 runs")
box(MID_CX[1] - MID_W / 2, MID_Y, MID_W, MID_H, NODE_F,
    title="Medication alone accepted", body="3 runs")

fork_label(51.5, "Fork 2 — Prior exposure")
for parent in MID_CX:
    kids = [c for c, p, *_ in FORKS if p == parent]
    bus(parent, MID_Y, kids, LEAF_Y + LEAF_H, BUS2)

for cx, _parent, head, runs, jac in FORKS:
    box(cx - LEAF_W / 2, LEAF_Y, LEAF_W, LEAF_H, LEAF_F,
        title=head, body=f"{runs}\nJaccard\n{jac}", body_dy=13.5)

fig.suptitle(TITLE, fontsize=13.0, fontweight="bold", color=INK,
             y=0.988, va="top", linespacing=LSP)

# -------------------------------------------------------------- verification
fig.canvas.draw()
for t in fig.findobj(plt.Text):
    if t.get_text().strip():
        assert t.get_fontsize() >= MIN_PT, f"{t.get_text()!r} is {t.get_fontsize()} pt"
assert abs(fig.get_size_inches()[0] - FIG_W) < 1e-9, "authoring width must be 7.0 in"

fig.savefig(HERE / "Figure4.pdf")
fig.savefig(HERE / "Figure4.png", dpi=600)
plt.close(fig)
print("wrote Figure4.png and Figure4.pdf (7.0 in wide, 12 pt floor)")
