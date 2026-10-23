"""Ensemble grid runner: structural + public-window diagnostics per variant.

Usage:
  python tests/run_ensemble_grid.py            # stage 1: single-knob runs
  python tests/run_ensemble_grid.py combo       # stage 2: combination runs
  python tests/run_ensemble_grid.py all         # everything

Writes tests/_cache/ensemble/<variant>.csv (variant labels) and
tests/_results/ensemble_grid.json (stats table). Public-window scorer numbers are
DIAGNOSTICS ONLY (bootstrap sigma ~0.08 -> deltas < 0.08 are noise); selection is by
structural anchors only.
"""
import json
import os
import sys

import numpy as np

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.dirname(TESTS_DIR))

import helpers as H  # noqa: E402
from possessed import pipeline as pl  # noqa: E402

OUT_DIR = os.path.join(H.CACHE_DIR, "ensemble")
JSON_PATH = os.path.join(H.RESULTS_DIR, "ensemble_grid.json")

# variant name -> build_full kwargs for the adaptive machine (default knobs omitted)
STAGE1 = {
    "base": {},                                    # band 20,60, phase on, x-margin 2.0
    "band_30_50": {"challenge_band": (30, 50)},
    "band_10_80": {"challenge_band": (10, 80)},
    "flat_40": {"challenge_band": (40, 40)},
    "phase_off": {"phase_prior": False},
    "x_1.0": {"x_margin": 1.0},
}
STAGE2 = {
    "combo_30_50_phaseoff": {"challenge_band": (30, 50), "phase_prior": False},
    "combo_30_50_phaseoff_x1": {"challenge_band": (30, 50), "phase_prior": False,
                                "x_margin": 1.0},
}


def bracketing_violations(labels):
    """Same predicate as tests/audit_direct_switches.py main(): every alive spell shorter
    than CHALLENGE_N must be bracketed by D or a graded-run edge on both sides."""
    n = 0
    for start, stop in H.GRADED_RUNS:
        for st, en, _team in H.spells_in(labels, start, stop):
            if en - st >= pl.CHALLENGE_N:
                continue
            left_ok = st == start or labels[st - 1] == "D"
            right_ok = en == stop or labels[en] == "D"
            if not (left_ok and right_ok):
                n += 1
    return n


def row_for(name, kwargs, pm, gt):
    path = os.path.join(OUT_DIR, name + ".csv")
    labels, _, _, _, _, _ = pl.build_full(verbose=False, **kwargs)
    H.write_labels_csv(labels, path)
    labels = H.read_labels(path)
    st = H.structural_stats(labels)
    res = H.score(labels, gt, pm)
    inside = np.zeros(pl.N_FRAMES, dtype=bool)
    for a, b in H.GRADED_RUNS:
        inside[a:b] = True
    return {
        "variant": name,
        "knobs": {k: v for k, v in kwargs.items()},
        "poss_h1": st["possessions"][0], "poss_h2": st["possessions"][1],
        "possessions": st["possessions"][0] + st["possessions"][1],
        "mean_s": [round(x, 2) for x in st["mean_s"]],
        "median_s": [round(x, 2) for x in st["median_s"]],
        "shares": {k: round(v, 4) for k, v in st["shares"].items()},
        "x_inside_runs": round(float((labels[inside] == "X").mean()), 4),
        "violations": bracketing_violations(labels),
        "macro_f1": round(res["macro_f1"], 4),      # diagnostics only
        "spell_f1": round(res["spell_f1_mean"], 4),  # diagnostics only
        "md5": H.md5_file(path),
    }


def main(argv):
    stage = argv[1] if len(argv) > 1 else "stage1"
    specs = dict(STAGE1)
    if stage in ("combo", "all"):
        specs.update(STAGE2)
    if stage == "combo":
        specs = dict(STAGE2)
    os.makedirs(OUT_DIR, exist_ok=True)
    pm = H.load_pm()
    gt = pm.label_codes(pm.read_label_csv(H.PUBLIC_GT))
    rows = []
    for name, kwargs in specs.items():
        row = row_for(name, kwargs, pm, gt)
        rows.append(row)
        print(json.dumps(row))
    table = {}
    if os.path.isfile(JSON_PATH):
        with open(JSON_PATH) as fh:
            table = json.load(fh)
    table.update({r["variant"]: r for r in rows})
    H.json_dump(table, JSON_PATH)
    print("wrote", JSON_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))