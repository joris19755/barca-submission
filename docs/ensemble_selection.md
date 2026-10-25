# Ensemble selection — challenge band / phase prior / X-safety grid

Eight runs around the shipped default (adaptive band [20,60], phase+transition priors on,
X-safety margin 2.0 m), each a full CSV regeneration with structural statistics plus
public-window scorer diagnostics. Public diagnostics are **DIAGNOSTICS ONLY**: the window
bootstrap σ ≈ 0.08, so every score delta below 0.08 in this table is noise and was not used
for selection. Selection is by simultaneous fit to the structural diagnostics: possessions
≈ 359, pooled mean duration ≈ 14.19 s (target band 12–16 s), D share 15.3 %, 0 bracketing
violations, small in-run X share. Of these, only the 14.19 s pooled mean is a published
value — a diagnostic from the public 5-minute window (17 possessions,
`mtah-2027/evaluation/gt/BAR-ATH_possession_gt_public_meta.json`). The count of 359 is our
own sweep-derived figure (the legacy N=40 row at 183/176 in
`tests/sections/sensitivity.md`), used here as a descriptive diagnostic: it is explicitly
NOT an official figure and NOT a tuning target.

Raw rows: `tests/_results/ensemble_grid.json`; variant CSVs: `tests/_cache/ensemble/*.csv`.
Runner: `python tests/run_ensemble_grid.py [stage1|combo|all]`.

## Grid table

| # | variant | knobs (vs default) | poss H1/H2 (tot) | pooled mean s | median s H1/H2 | H | A | D | X | X-in-runs | viol | macroF1* | spellF1* |
|---|---------|--------------------|------------------|---------------|----------------|---|---|---|---|-----------|------|----------|----------|
| 1 | base (default) | — | 179/182 (**361**) | **14.18** | 7.76/9.08 | .3381 | .3037 | .1532 | .2049 | 0.24 % | **0** | 0.6640 | 0.4000 |
| 2 | band_30_50 | band [30,50] | 180/178 (358) | 14.30 | 7.84/8.54 | .3402 | .3017 | .1532 | .2049 | 0.23 % | 0 | 0.6644 | 0.4105 |
| 3 | band_10_80 | band [10,80] | 170/187 (357) | 14.33 | 7.96/8.64 | .3434 | .2984 | .1532 | .2050 | 0.25 % | 0 | 0.6590 | 0.3895 |
| 4 | flat_40 | band [40,40] (control) | 181/174 (355) | 14.42 | 7.64/8.98 | .3394 | .3026 | .1532 | .2048 | 0.23 % | 0 | 0.6651 | 0.4105 |
| 5 | phase_off | priors off | 173/180 (353) | 14.50 | 7.76/9.14 | .3334 | .3084 | .1532 | .2050 | 0.25 % | 0 | 0.6632 | 0.4000 |
| 6 | x_1.0 | X margin 1.0 m | 179/182 (361) | 14.20 | 7.80/9.12 | .3387 | .3042 | .1532 | .2039 | 0.12 % | 0 | 0.6641 | 0.4000 |
| 7 | combo_30_50_phaseoff | band [30,50] + priors off | 178/176 (354) | 14.46 | 7.96/9.12 | .3379 | .3040 | .1532 | .2049 | 0.24 % | 0 | 0.6642 | 0.4105 |
| 8 | combo…_x1 | as 7 + X margin 1.0 m | 178/176 (354) | 14.48 | 7.96/9.14 | .3384 | .3045 | .1532 | .2039 | 0.11 % | 0 | 0.6643 | 0.4105 |

`pooled mean s` = mean duration over all alive spells in both halves (the statistic behind
the 14.19 s GT anchor). `viol` = bracketing violations from the audit predicate (every
sub-CHALLENGE_N spell bracketed by D/edge); `audit_direct_switches.py` independently
reports **total violations: 0** on the shipped file. *Diagnostics only.

## Selection: the current default (row 1)

All eight variants pass the hard criteria (0 violations, mean inside 12–16 s, D pinned at
15.3 % by Smart Tagging dead-ball, tiny in-run X). Ranking on the two soft anchors:

- **Possessions ≈ 359**: base 361 (Δ2) and x_1.0 361 (Δ2); band_30_50 358 (Δ1) is closest;
  every other variant sits at 353–357.
- **Pooled mean ≈ 14.19 s**: base 14.18 (Δ0.01) and x_1.0 14.20 (Δ0.01) are essentially
  exact; band_30_50 is 14.30 (Δ0.11); phase-off and flat-40 drift to 14.4–14.5.

No variant strictly dominates the default. band_30_50 gains one possession but moves the
mean 0.11 s off-anchor and widens the H1/H2 asymmetry. x_1.0 ties the default on both
primary anchors and halves the in-run X share (0.24 % → 0.12 %), but that margin is the
documented metric-aligned X policy (AMBIG_MARGIN, data_audit) and both values are two
orders of magnitude below the 10 % invariant — a wash on structural fit, so it is not worth
changing a policy default. Wider bands, flat-40 and prior-off all lose on possessions
(353–357) while buying nothing structurally; the flat-40 control confirms the adaptive band
is not what creates the anchor fit (control lands at 355/14.42). Every public-window score
delta is < 0.08 (bootstrap σ) and therefore noise.

**Outcome: current default wins; no change to the shipped pipeline defaults.**
The new knobs (`--challenge-band`, `--no-phase-prior`, `--x-margin`, and the matching
`build_full` keyword arguments) remain available for future sweeps and default to the
shipped behavior — verified byte-identical at the time of this grid (md5
`81a9a48c1b42132b68f09f1247fb8305`). The pipeline has since received the second-review
fixes; the current shipped file is md5 `96a8d91e50d7c0631bad520ac1fe927b` (see README).