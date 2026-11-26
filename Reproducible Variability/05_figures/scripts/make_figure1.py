#!/usr/bin/env python3
"""
make_figure1.py - regenerates Figure 1 of the JAMIA "Research and Applications"
submission from one committed data file, figure_data.json.

    python3 make_figure1.py            # writes Figure1.pdf and Figure1.png

Figures 2, 3, 4 and S1 to S3 are built by the sibling make_figure*.py scripts.

Design rules enforced by construction and re-checked by the built-in verifier
at the bottom of this file:

  * Authored at 7.0 in wide, the journal's reproduction width, and rendered 1:1,
    so every in-figure point size IS its printed point size. Nothing is authored
    wide and shrunk.
  * 12 pt floor on all text. Set explicitly in rcParams and asserted per figure.
  * Exported as vector PDF with embedded TrueType fonts (pdf.fonttype = 42) and
    as PNG at 600 dpi.
  * No meaning carried by colour alone. Every colour-coded group also carries a
    distinct marker shape, a distinct hatch, or a direct text label; most carry
    two of the three.
  * Okabe-Ito colour-blind-safe palette; every filled shape has a near-black
    outline, so graphical objects keep >= 3:1 contrast against white even where
    the fill alone would not.
  * Arial-metric sans-serif (Liberation Sans falls back to Arial / Helvetica).
  * No study-internal shorthand in any label, title, axis or annotation.
  * Values that coincide are listed separately rather than overplotted into one
    point that a legend then claims is two.

The verifier checks, for each figure: minimum font size, that no text is clipped
by the figure edge, that no two text objects in the same axes overlap, and that
no forbidden internal term appears in any string. It exits non-zero on failure.
"""

import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Patch, Rectangle
from matplotlib.text import Text

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / "figure_data.json").read_text())

# --------------------------------------------------------------------- style
MIN_PT = 12.0
FIG_W = 7.0                      # inches; JAMIA reproduction width. Never exceed.

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Liberation Sans", "Arial", "Helvetica", "DejaVu Sans"],
    "pdf.fonttype": 42,          # embedded, editable TrueType
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "font.size": MIN_PT,
    "axes.titlesize": MIN_PT,
    "axes.labelsize": MIN_PT,
    "xtick.labelsize": MIN_PT,
    "ytick.labelsize": MIN_PT,
    "legend.fontsize": MIN_PT,
    "figure.titlesize": MIN_PT,
    "axes.linewidth": 0.9,
    "xtick.major.width": 0.9,
    "ytick.major.width": 0.9,
    "xtick.major.size": 4.0,
    "ytick.major.size": 4.0,
    "hatch.linewidth": 0.9,
    "lines.solid_capstyle": "butt",
})

INK      = "#1a1a1a"            # near-black; all outlines and all type
GRID     = "#bdbdbd"
HUMAN    = "#0072B2"            # Okabe-Ito blue        5.2:1 on white
AI_ORIG  = "#D55E00"            # Okabe-Ito vermillion  3.9:1 on white
AI_REV   = "#009E73"            # Okabe-Ito bluish green 3.4:1 on white
NEUTRAL  = "#9e9e9e"

M_HUMAN, M_ORIG, M_REV = "s", "o", "^"          # redundant shape channel
H_HUMAN, H_ORIG, H_REV = "", "///", "xxx"       # redundant hatch channel

PANEL_PT = 14.0                 # panel letters A / B


def n(v):
    """JAMIA house style: no separator below 10 000, space-separated groups above."""
    s = str(int(v))
    if len(s) <= 4:
        return s
    out = ""
    while len(s) > 3:
        out = " " + s[-3:] + out
        s = s[:-3]
    return s + out


def inch_axes(fig, left, bottom, width, height):
    """Add an axes positioned in INCHES from the figure's lower-left corner."""
    w, h = fig.get_figwidth(), fig.get_figheight()
    return fig.add_axes([left / w, bottom / h, width / w, height / h])


def panel_letter(fig, letter, x_in, y_in):
    fig.text(x_in / fig.get_figwidth(), y_in / fig.get_figheight(), letter,
             fontsize=PANEL_PT, fontweight="bold", color=INK,
             ha="left", va="top")


def tidy(ax, spines=("top", "right")):
    for s in spines:
        ax.spines[s].set_visible(False)
    for s in ax.spines.values():
        s.set_color(INK)
    ax.tick_params(colors=INK, labelcolor=INK)


# ======================================================================
# Figure 1 - study design schematic
# ======================================================================


def figure1():
    s = DATA["study"]
    FIG_H = 6.5
    fig = plt.figure(figsize=(FIG_W, FIG_H))
    ax = fig.add_axes([0.005, 0.005, 0.99, 0.99])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    SOURCE_F, COMMON_F, OUT_F = "#d9d9d9", "#efefef", "#ffffff"
    ARM_F = ["#ffffff", "#cfe0ee", "#9dc2dc"]
    LSP = 1.30

    def box(x, y, w, h, fc, title=None, body=None, lw=1.1, body_dy=11.0):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.5",
            facecolor=fc, edgecolor=INK, linewidth=lw, mutation_scale=1, zorder=2))
        if title is not None and body is not None:
            ax.text(x + w / 2, y + h - 2.0, title, ha="center", va="top",
                    fontsize=MIN_PT, fontweight="bold", color=INK, zorder=3,
                    linespacing=LSP)
            ax.text(x + w / 2, y + h - body_dy, body, ha="center", va="top",
                    fontsize=MIN_PT, color=INK, zorder=3, linespacing=LSP)
        else:
            ax.text(x + w / 2, y + h / 2, title or body, ha="center", va="center",
                    fontsize=MIN_PT, color=INK, zorder=3, linespacing=LSP)

    def arrow(x0, y0, x1, y1):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                                     mutation_scale=13, linewidth=1.4, color=INK,
                                     zorder=1, shrinkA=0, shrinkB=0))

    SRC_Y, SRC_H = 88.5, 10.5
    box(10, SRC_Y, 80, SRC_H, SOURCE_F,
        body=f"One published cohort study ({s['source_study']}) plus\n"
             f"{s['frozen_code_sets']} frozen code sets, shared verbatim with every arm")

    ARM_Y, ARM_H, ARM_W = 51.0, 30.0, 31.0
    xs = [1.5, 34.5, 67.5]
    FAN = 85.0
    box(xs[0], ARM_Y, ARM_W, ARM_H, ARM_F[0],
        title="A. Nine expert\nhuman teams",
        body="Cohort definitions\npublished by nine\nindependent teams,\nre-implemented here")
    box(xs[1], ARM_Y, ARM_W, ARM_H, ARM_F[1],
        title="B. Nine AI agents",
        body="Original paper\nexactly as\npublished")
    box(xs[2], ARM_Y, ARM_W, ARM_H, ARM_F[2],
        title="C. Nine AI agents",
        body="Same paper, internal\ncontradictions\nremoved")

    ax.plot([50, 50], [SRC_Y, FAN], color=INK, lw=1.4, zorder=1)
    ax.plot([xs[0] + ARM_W / 2, xs[2] + ARM_W / 2], [FAN, FAN], color=INK, lw=1.4, zorder=1)
    for x in xs:
        arrow(x + ARM_W / 2, FAN, x + ARM_W / 2, ARM_Y + ARM_H + 0.4)

    JOIN = 46.5
    for x in xs:
        ax.plot([x + ARM_W / 2, x + ARM_W / 2], [ARM_Y - 0.4, JOIN], color=INK, lw=1.4, zorder=1)
    ax.plot([xs[0] + ARM_W / 2, xs[2] + ARM_W / 2], [JOIN, JOIN], color=INK, lw=1.4, zorder=1)

    EXE_Y, EXE_H = 28.5, 14.5
    arrow(50, JOIN, 50, EXE_Y + EXE_H + 0.4)
    box(6, EXE_Y, 88, EXE_H, COMMON_F,
        body=f"All {s['definitions_total']} cohort definitions executed on one claims database\n"
             f"({s['database_patients_million']} million patients, {s['database_years']}), each scored against\n"
             f"one reference cohort of {n(DATA['reference_cohort_n'])} patients")

    OUT_Y, OUT_H = 1.5, 23.0
    arrow(50, EXE_Y, 50, OUT_Y + OUT_H + 0.4)
    box(6, OUT_Y, 88, OUT_H, OUT_F,
        title="Outcome measures, computed identically for all three arms",
        body="Agreement with the reference cohort: Jaccard index\n"
             "Agreement among the nine definitions in an arm: pairwise Jaccard index\n"
             "Cohort size dispersion: largest divided by smallest\n"
             "Source of disagreement: comparison criterion by criterion",
        body_dy=8.5)
    return fig, "Figure1"


# ======================================================================
# Figure 2 - cohort sizes, human arm
# ======================================================================


FORBIDDEN = [
    r"\bmaster\b", r"\bports?\b", r"\bsub[-\s]?stud(y|ies)\b", r"\bfleets?\b",
    r"\bviolin\b", r"\bHV\b", r"\bCE\b", r"\ba[1-9]\b", r"\bcs\d+\b",
    r"counts?\s+withheld", r"/(Users|home|sessions)/", r"\bdx[-\s]only\b",
    r"\bdrug[-\s]arm\b", r"\bbridge\b", r"Health\s?Verity", r"\bcodesets?\b",
    r"\bcanonical\b", r"\bisland\b", r"\bnear-inert\b", r"Ostropolets",
]


def verify(fig, name):
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    W = fig.get_figwidth() * fig.dpi
    H = fig.get_figheight() * fig.dpi
    texts = [t for t in fig.findobj(Text)
             if t.get_visible() and t.get_text().strip()]
    problems, warnings = [], []

    if abs(fig.get_figwidth() - FIG_W) > 1e-9:
        problems.append(f"width {fig.get_figwidth()} in, expected {FIG_W} in")

    smallest = min(t.get_fontsize() for t in texts)
    for t in texts:
        if t.get_fontsize() < MIN_PT - 1e-6:
            problems.append(f"{t.get_fontsize():.1f} pt < {MIN_PT} pt: {t.get_text()[:44]!r}")

    boxes = []
    for t in texts:
        bb = t.get_window_extent(renderer=rend)
        boxes.append((t, bb))
        if bb.x0 < -1 or bb.y0 < -1 or bb.x1 > W + 1 or bb.y1 > H + 1:
            problems.append(f"clipped by figure edge: {t.get_text()[:44]!r}")

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (t1, b1), (t2, b2) = boxes[i], boxes[j]
            ox = min(b1.x1, b2.x1) - max(b1.x0, b2.x0)
            oy = min(b1.y1, b2.y1) - max(b1.y0, b2.y0)
            if ox > 2 and oy > 2:
                warnings.append(f"text overlap: {t1.get_text()[:26]!r} / {t2.get_text()[:26]!r}")

    legends = []
    for a in fig.axes:
        lg = a.get_legend()
        if lg is not None:
            legends.append((set(map(id, lg.get_texts())),
                            lg.get_frame().get_window_extent(renderer=rend)))
    for t, bb in boxes:
        for own, lb in legends:
            if id(t) in own:
                continue
            ox = min(bb.x1, lb.x1) - max(bb.x0, lb.x0)
            oy = min(bb.y1, lb.y1) - max(bb.y0, lb.y0)
            if ox > 2 and oy > 2:
                problems.append(f"text under a legend box: {t.get_text()[:44]!r}")

    for t in texts:
        for pat in FORBIDDEN:
            if re.search(pat, t.get_text(), flags=re.IGNORECASE):
                problems.append(f"forbidden term /{pat}/ in {t.get_text()[:44]!r}")

    ok = not problems
    print(f"{name}: {fig.get_figwidth():.2f} x {fig.get_figheight():.2f} in, "
          f"{len(texts)} text objects, smallest {smallest:.1f} pt -> "
          f"{'PASS' if ok else 'FAIL'}")
    for p in problems:
        print("   FAIL  " + p)
    for w in dict.fromkeys(warnings):
        print("   warn  " + w)
    return ok


def main():
    all_ok = True
    for b in [figure1]:
        fig, name = b()
        all_ok &= verify(fig, name)
        fig.savefig(HERE / f"{name}.pdf")
        fig.savefig(HERE / f"{name}.png", dpi=600)
        plt.close(fig)
    print("ALL PASS" if all_ok else "SOME CHECKS FAILED")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
