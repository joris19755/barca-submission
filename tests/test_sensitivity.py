"""Section 3: sensitivity sweep over CHALLENGE_N in {15, 25, 40, 60, 75}.

Diagnostics only: how structural stats and public-window scores move with N. No retuning —
N=40 is the shipped, structurally-chosen default and stays regardless of these numbers.
"""
import os

import pytest

import helpers as H
from test_ablation import build_variant

GRID = [15, 25, 40, 60, 75]


@pytest.fixture(scope="module")
def sweep():
    pm = H.load_pm()
    gt = pm.label_codes(pm.read_label_csv(H.PUBLIC_GT))
    rows = []
    for n in GRID:
        path = build_variant(challenge_n=n, cache_key="challenge_n_{}".format(n))
        labels = H.read_labels(path)
        st = H.structural_stats(labels)
        res = H.score(labels, gt, pm)
        rows.append({
            "challenge_n": n, "n_half_s": round(n / H.FPS, 1),
            "poss_h1": st["possessions"][0], "poss_h2": st["possessions"][1],
            "mean_s": round(sum(st["mean_s"]) / 2, 1),
            "median_s": round(sum(st["median_s"]) / 2, 1),
            "d_share": round(st["shares"]["D"], 4),
            "macro_f1": round(res["macro_f1"], 4),
            "spell_f1": round(res["spell_f1_mean"], 4),
        })
    return rows


def test_sweep_runs_and_reports(sweep):
    by_n = {r["challenge_n"]: r for r in sweep}
    assert set(by_n) == set(GRID)
    # monotonic structure: larger challenge window => fewer possessions (sanity of the knob)
    poss = [by_n[n]["poss_h1"] + by_n[n]["poss_h2"] for n in GRID]
    assert poss == sorted(poss, reverse=True), poss
    # The sweep's N rows run the LEGACY flat-window machine (challenge_n given); the
    # shipped default is the adaptive machine, so row-for-row equality no longer holds.
    # Sanity instead: the shipped adaptive default sits inside the legacy sweep's band.
    default_h1 = H.structural_stats(H.read_labels(H.SUBMISSION))["possessions"][0]
    assert by_n[75]["poss_h1"] < default_h1 < by_n[15]["poss_h1"], \
        (by_n[75]["poss_h1"], default_h1, by_n[15]["poss_h1"])

    lines = ["CHALLENGE_N | window s | poss H1/H2 (total) | mean s | median s | D share | "
             "macroF1* | spellF1*",
             "--- | --- | --- | --- | --- | --- | --- | ---"]
    for r in sweep:
        lines.append("{} | {}s | {}/{} ({}) | {} | {} | {} | {} | {}".format(
            r["challenge_n"], r["n_half_s"], r["poss_h1"], r["poss_h2"],
            r["poss_h1"] + r["poss_h2"], r["mean_s"], r["median_s"], r["d_share"],
            r["macro_f1"], r["spell_f1"]))
    lines.append("")
    lines.append("* public-window diagnostics only; not a tuning signal.")
    narrow = by_n[15]["poss_h1"] + by_n[15]["poss_h2"]
    wide = by_n[75]["poss_h1"] + by_n[75]["poss_h2"]
    cur = by_n[40]
    lines.append("Reading: possession count spans {}..{} across the grid; the legacy "
                 "N=40 row sits at {}/{} per half. The shipped default is the ADAPTIVE "
                 "machine (mean spell ~12-16 s vs the 14.19 s structural anchor), so the "
                 "legacy grid only shows the knob's direction; score columns move within "
                 "a band and are reported without acting on them.".format(
                     wide, narrow, cur["poss_h1"], cur["poss_h2"]))
    report = "## CHALLENGE_N sensitivity sweep\n\n" + "\n".join(lines) + "\n"
    H.json_dump(sweep, os.path.join(H.RESULTS_DIR, "sensitivity_rows.json"))
    assert H.load_section("sensitivity", lambda: report)