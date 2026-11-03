"""Section 2: ablation matrix — which pipeline stage buys what.

Four variants: (a) no smart dead-ball, (b) no ball fill, (c) no hysteresis (raw nearest),
(d) full default. Official-scorer numbers on the public 5-minute window are DIAGNOSTICS ONLY
(no tuning may be driven by them — see the report's verdict).
"""
import os

import pytest

import helpers as H


def build_variant(smart_dead=True, ball_fill=True, challenge_n=None, cache_key=None):
    """Run the pipeline with ablation switches; cache variant CSVs under tests/_cache/."""
    if cache_key:
        path = os.path.join(H.CACHE_DIR, cache_key + ".csv")
        if os.path.isfile(path):
            return path
    from possessed import pipeline as pl
    labels, _, _, _, _, _ = pl.build_full(verbose=False, smart_dead=smart_dead,
                                           ball_fill=ball_fill, challenge_n=challenge_n)
    os.makedirs(H.CACHE_DIR, exist_ok=True)
    return H.write_labels_csv(labels, path if cache_key else
                              os.path.join(H.CACHE_DIR, (cache_key or "tmp") + ".csv"))


VARIANTS = [
    ("no_smart_dead", dict(smart_dead=False)),
    ("no_ball_fill", dict(ball_fill=False)),
    ("no_hysteresis", dict(challenge_n=1)),
    ("full_default", dict()),
]


@pytest.fixture(scope="module")
def built():
    return {name: build_variant(cache_key=name, **kw) for name, kw in VARIANTS}


def _row(labels, pm, gt):
    st = H.structural_stats(labels)
    res = H.score(labels, gt, pm)
    return {
        "poss_h1": st["possessions"][0], "poss_h2": st["possessions"][1],
        "mean_s": round(sum(st["mean_s"]) / 2, 1),
        "median_s": round(sum(st["median_s"]) / 2, 1),
        "d_share": round(st["shares"]["D"], 4),
        "h_share": round(st["shares"]["H"], 4),
        "a_share": round(st["shares"]["A"], 4),
        "x_share": round(st["shares"]["X"], 4),
        "macro_f1": round(res["macro_f1"], 4),
        "spell_f1": round(res["spell_f1_mean"], 4),
        "n_pred_spells": res["n_pred_spells"],
    }


def test_ablation_matrix_and_report(built):
    pm = H.load_pm()
    gt = pm.label_codes(pm.read_label_csv(H.PUBLIC_GT))
    rows = {name: _row(H.read_labels(path), pm, gt) for name, path in built.items()}
    # sanity: ablations must actually differ from the default output
    full = rows["full_default"]
    assert full["d_share"] > 0  # default has dead ball
    assert rows["no_smart_dead"]["d_share"] < full["d_share"] / 2, \
        "no_smart_dead should sharply reduce D share"
    assert rows["no_hysteresis"]["poss_h1"] > full["poss_h1"], \
        "raw nearest must fragment possessions vs hysteresis"
    # full default must reproduce the shipped submission byte-for-byte
    assert H.md5_file(built["full_default"]) == H.SHIPPED_MD5

    header = ("variant | poss H1/H2 | mean s | median s | D share | H/A/X share | "
              "macroF1* | spellF1* | n spells*")
    lines = [header, "--- | --- | --- | --- | --- | --- | --- | --- | ---"]
    notes = []
    for name, _ in VARIANTS:
        r = rows[name]
        lines.append("{} | {}/{} | {} | {} | {} | {}/{}/{} | {} | {} | {}".format(
            name, r["poss_h1"], r["poss_h2"], r["mean_s"], r["median_s"], r["d_share"],
            r["h_share"], r["a_share"], r["x_share"], r["macro_f1"], r["spell_f1"],
            r["n_pred_spells"]))
    notes.append("* official-scorer columns are public-window diagnostics only — "
                 "never a tuning signal, except the published 14.19 s mean-duration "
                 "metadata anchor (rules: no tuning on the public 5-min window).")
    notes.append("Observations: smart dead-ball is what creates the D class and the restart "
                 "priors (no_smart_dead collapses D and loses possession structure at "
                 "restarts); ball fill stabilises the raw signal in camera gaps "
                 "(no_ball_fill churns); hysteresis is the main possession-count control "
                 "(no_hysteresis reproduces the raw-baseline fragmentation, ~{} -> {}+ "
                 "possessions/half vs {}/{} full).".format(
                     rows["no_hysteresis"]["poss_h1"], rows["no_hysteresis"]["poss_h1"],
                     rows["full_default"]["poss_h1"], rows["full_default"]["poss_h2"]))
    report = "## Ablation matrix\n\n" + "\n".join(lines + [""] + notes) + "\n"
    H.json_dump(rows, os.path.join(H.RESULTS_DIR, "ablation_rows.json"))
    assert H.load_section("ablation", lambda: report)