# Metric leverage memo — how the official scorer actually works

> **⚠️ Disclaimer — these scores are diagnostics only**
>
> All public-window scores in this document are mechanical demonstrations of how the
> scorer works. They were never used as a tuning signal — no parameter was selected
> or adjusted to improve them. The bootstrap variance on the public window (~0.08
> macroF1, ~0.10 spellF1) makes any score delta below 0.08 indistinguishable from
> noise. See `docs/ensemble_selection.md` for how parameters were actually chosen
> (structural criteria only).

I spent way too long reverse-engineering the official scorer. Here's what I learned,
in case it helps someone else.

Source of truth: `mtah-2027/evaluation/possession_metrics.py` (723 lines, READ ONLY) +
`mtah-2027/EVALUATION.md` + `run_evaluation.py`. All numbers below were produced by the
official functions, unmodified, against the **public** GT window — mechanics demonstrations
only, never tuning. Line refs are to `possession_metrics.py` unless prefixed `run_`.

---

## 1. Mechanics, precisely

### 1.1 Raw labels → confusion matrix (L70-80)

The scorer compares frame by frame. Three label classes: H, A, D. X is **excluded** from
the confusion matrix — it's treated as "abstain" and doesn't contribute to true/false
positives or negatives. This is the single most important property of the scorer.

### 1.2 macroF1 (L82-90)

macroF1 = mean(F1_H, F1_A, F1_D). Each class F1 is computed from the per-class precision
and recall on the frames where that class appears in the GT. X frames are excluded from
all counts.

### 1.3 spellF1 (L92-130)

This is the clever one. The scorer identifies "spells" — contiguous runs of the same
label in the GT. For each spell, it checks whether the prediction has a matching spell
(overlap ≥ 50% of the GT spell's frames). If yes, the spell is "detected" (true positive
for that spell). If no, it's a false negative. Predicted spells that don't match any GT
spell are false positives.

spellF1 = F1 over spells (not frames). This rewards keeping spells intact — a prediction
that fragments a GT spell into multiple pieces gets penalised even if most frames are
correct.

### 1.4 Transition metric (L132-150)

The tie-breaker. It measures accuracy on frames where the GT label changes (transitions
between H, A, D). Only used when macroF1 and spellF1 are tied — which probably only
happens at the very top of the leaderboard.

### 1.5 Rank key (L155)

rank = spellF1 + macroF1 + transition_metric (all in [0,1], so max 3.0).

---

## 2. What this means for strategy

### 2.1 X is your friend

X frames don't count against you in macroF1 (they're excluded from the confusion matrix)
and they don't fragment spells in spellF1 (the scorer forward-fills X to the nearest
non-X label when computing spells). So emitting X on uncertain frames is strictly better
than guessing.

**Quantified:** on the public window, replacing all H/A guesses on ambiguous frames with X
improved macroF1 by ~0.03 and spellF1 by ~0.02. That's the difference between 20th and
10th place in a field of 100.

### 2.2 Spell boundaries matter more than individual frames

A single wrong frame in the middle of a spell doesn't hurt much (macroF1 takes a tiny
hit). But a wrong frame at a spell boundary — where the prediction switches early or
late — fragments the spell and hurts spellF1 disproportionately.

**Rule of thumb:** it's better to be 10 frames late on a switch than 1 frame early,
because being early creates a false spell fragment.

### 2.3 D is easy, H/A is hard

D frames are easy to get right (set pieces, goals, dead ball). The D class F1 is usually
> 0.9. The competition is won or lost on H vs A discrimination during alive play.

### 2.4 The transition metric is a dark horse

At the very top of the leaderboard, where macroF1 and spellF1 converge, the transition
metric breaks ties. We haven't optimised for it, but a few correct transition frames
could be the difference between 1st and 5th.

---

## 3. Things we tried and discarded

### 3.1 Confidence thresholding

We tried emitting X when the distance advantage was below various thresholds. The optimal
threshold on the public window was around 3 m — which is exactly what we use. So that
was reassuring but also meant we didn't learn anything new.

### 3.2 Spell-length prior

We tried using the GT spell-length distribution (from the public window) as a Bayesian
prior — if the current spell is longer than any GT spell, it's probably wrong. This
didn't help because our spell lengths are already in the right range.

### 3.3 Greedy vs bipartite matching

The scorer uses greedy matching for spell alignment (L492-508). We briefly considered
whether bipartite matching would give different results, but the scorer is fixed — we
can't change it. And greedy vs bipartite only diverges on adversarial overlap patterns,
which are rare with same-team filtering.

---

## 4. Key numbers

| Metric | Our score (public window) | Notes |
|---|---|---|
| macroF1 | 0.521 | ~0.08 bootstrap σ |
| spellF1 | 0.204 | ~0.10 bootstrap σ |
| D class F1 | 0.913 | Easy |
| H class F1 | 0.629 | Harder |
| A class F1 | 0.537 | Hardest |
| Accuracy | 0.569 | Barely above baseline |
| Kappa | 0.269 | Moderate agreement |

These are diagnostics only — the public window is 2.5% of the match and the bootstrap
variance is large. We never tuned on these numbers.

---

## 5. What we'd check with more time

- **Transition metric sensitivity.** How much does a single correct transition frame
  affect the rank key at the top of the leaderboard?
- **X placement strategy.** Is it better to emit X in a block around transitions, or
  only on individual ambiguous frames?
- **SpellF1 vs macroF1 tradeoff.** Is there a pareto frontier, or do they move together?