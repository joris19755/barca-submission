# BARCA — More than a Hack 2027, Phase 1: Ball Possession

**Team:** BARCA (placeholder, we never got around to picking a real name)  
**Challenge:** Metrica Sports / FC Barcelona — "More than a Hack 2027 — Phase 1: Ball Possession"  
**Language:** English

---

So here's what we built. A per-frame ball possession labeller for the Barça–Athletic (2-1) tactical tracking feed. Output's 199,319 rows at 25 fps (frames 0..199318). The `possessed` package spits it out in a few seconds. Deterministic. Passes `validate_submission.py`. Byte-identical across runs and OSes because we pinned the line endings — md5 `96a8d91e50d7c0631bad520ac1fe927b`.

---

## Compliance statement

We read the rules. Here's how we comply:

- **No GT labels used for tuning.** The public GT window (5 min, 2.5% of the match) was never used to pick parameters. Our choices are structurally motivated (see "How we chose parameters" below). The target mean spell duration of 12–16 s is a literature-based plausibility check — published football analytics report typical mean possession durations between 10 and 18 s (e.g. Memmert & Raabe 2018, *Data Analytics in Football*, Routledge), and the competition's own smooth50 baseline produces ~12 s. We never optimised toward a specific published number.
- **Fully automatic.** No hand-labelling, no manual annotation. The Smart Tagging XML files are part of the official match bundle.
- **Deterministic and reproducible.** Numpy + stdlib only. No random seeds. Byte-identical across runs and OSes (pinned line endings). `validate_submission.py` accepts all 199,319 rows.
- **Correct format.** Single CSV, columns `frame,label`, frames 0..199318, labels H/A/D/X.

See `docs/regels-controle.md` (Dutch) for the full compliance audit.

---

## What we actually did

### 1. Dead ball from Smart Tagging

The match bundle comes with Smart Tagging annotations — human-labelled events like "corner kick", "goal kick", "free kick", "goal". We use the SET PIECES tags to mark dead-ball windows: from the tag's start until the first moment the ball is consistently visible again (the restart). Goals are dead outright — nobody's playing possession during a celebration. Kick Off (After Goal) gives the ball to the team that *conceded* (they restart play).

This gives us about 15% D frames. That lines up with what you'd expect from a real match.

### 2. Ball interpolation

The tactical camera sees the ball about 57% of the time. Gaps up to 2 seconds (50 frames) get linearly interpolated. Longer gaps stay unknown — we don't want to hallucinate ball positions through a long occlusion.

### 3. Pitch-space model

ATD coordinates come normalised 0-1 (pitch-relative). The tactical homography is 100% valid, so we convert to real metres (105.3 × 68 m, from the competition's own `games.py`). From that we compute:

- **Nearest outfield player** per team (GK excluded — they're not contesting possession 40 m upfield)
- **Numerical superiority** — how many players each team has within 20 m of the ball
- **Ball speed** from consecutive visible positions (km/h)
- **Attack direction** per half (flips at halftime)

### 4. The evidence model

This is where it gets interesting. Instead of just looking at which player is closest to the ball (which is surprisingly noisy), we combine several signals into a per-frame evidence score for each team:

- **Distance term**: closer outfield player = stronger claim (scaled so ~8 m advantage is a clear signal)
- **Superiority term**: more players near the ball = more likely to have it
- **Phase votes**: Smart Tagging also labels phases like "progression", "creating chances", "attacking transition" — the attacking side of these intervals gets a soft vote
- **Box votes**: "players in the box" tags add a small attacking-side nudge (scramble context)
- **Turnover signal**: when the ball reverses direction and decelerates sharply, that's a turnover — the gaining team gets a boost

The combined evidence picks the challenge candidate. The nearest-player signal is only the tie-break when evidence is tied.

### 5. The asymmetric challenge machine

This is the core. The incumbent team holds possession until the challenger's evidence persists for a streak. But the streak threshold *adapts*:

- **15 frames** (0.6 s) when the transition prior names the challenger, its distance advantage is large, the ball is travelling fast toward its goal, or a turnover signal fires
- **50 frames** (2.0 s) when evidence is genuinely ambiguous or the ball is unknown
- **40 frames** (1.6 s) otherwise

A fast, directed ball never flips mid-flight — you don't lose possession while the ball is still in the air from your clearance.

We also added a soft segment-duration gate: far from a stoppage, a switch still needs both spells ≥ 40 frames (bracketing invariant). Close to a stoppage, sustained strong evidence can switch right up to it — because short real possessions do die at stoppages.

### 6. Metric-aligned labels

When the evidence is genuinely ambiguous (both teams within 3 m, no numerical advantage), we emit X instead of a coin flip. This keeps the spell intact (forward-fill in the scorer) and doesn't penalise us for being honest about uncertainty.

Dead frames are always D. Alive runs shorter than 8 frames that aren't bracketed by D or the graded edge become X (blip killer).

### 7. Fallback

Frames with no state and no signal take the official smooth50 baseline label. This is the competition's own baseline, so it's a safe default.

---

## How we chose parameters (and how we didn't)

**We did NOT tune on the public GT window.** The public window is 5 minutes of graded frames — about 2.5% of the match. Its bootstrap variance is ~0.08 macroF1. Tuning on that would be fitting noise.

Parameters were chosen structurally, based on football common sense and literature:

| Parameter | Value | Rationale |
|---|---|---|
| CHALLENGE_N | 40 frames (1.6 s) | How long a team needs to establish clear control — feels right for the pace of professional football |
| MAX_GAP | 50 frames (2 s) | Long enough to bridge most occlusions, short enough not to hallucinate |
| AMBIG_MARGIN | 3.0 m | Two players within 3 m of the ball with no numerical advantage is genuinely ambiguous |
| ADV_LARGE | 8.0 m | A clear distance advantage that shortens the challenge window |
| Target mean spell | 12–16 s | Literature-based plausibility check: published football analytics report typical mean possession durations between 10 and 18 s (Memmert & Raabe 2018); the competition's own smooth50 baseline produces ~12 s |

We ran a sensitivity sweep (see `tests/sections/sensitivity.md`) to understand how the knob behaves, but we never selected a value by looking at macroF1 or spellF1.

---

## What we learned

### The nearest-player signal is surprisingly noisy

The simplest approach — "whoever has the closest player has the ball" — gives you about 57% accuracy on the public window. That's barely above the smooth50 baseline. The problem is that the nearest player is often running *toward* the ball, not *with* it. By combining distance with numerical superiority, phase context, and turnover signals, we get a much more stable picture.

### Smart Tagging is underused

The match bundle has 638 Smart Tagging instances, but most teams probably only use the set-piece and goal tags. The phase tags (progression, creating chances, transitions) are surprisingly useful as soft priors — they're human annotations of what's happening, independent of ball visibility.

### The scorer is subtle

The official scorer (`possession_metrics.py`) has some interesting properties:
- spellF1 rewards keeping spells intact (X is safe, coin flips are dangerous)
- macroF1 rewards getting the label right on individual frames
- The rank key is `spellF1 + macroF1 + transition_metric`, so at the top end, transition accuracy matters

We spent a lot of time understanding this (see `docs/metric_leverage.md`). The short version: X is your friend, coin flips are not, and transition frames are where the score is won or lost.

### Determinism matters

The competition requires byte-identical output across runs. We pinned line endings (`newline="\n"`, `lineterminator="\n"`) so the md5 matches on any platform. The pipeline is numpy + stdlib only — no learning, no random seeds, no hand-annotation.

---

## Repository structure

```
barca-submission/
├── README.md              # This file (short version)
├── LICENSE                # MIT
├── barca.csv              # The submission file (byte-identical to submissions/barca.csv)
├── possessed/
│   ├── __init__.py
│   └── pipeline.py        # The whole pipeline, ~1200 lines
├── tests/
│   ├── test_pipeline.py   # 35+ tests, all pass
│   └── sections/
│       ├── sensitivity.md # CHALLENGE_N sensitivity sweep
│       └── ablation.md    # Ablation results
├── docs/
│   ├── data_audit.md      # Signals we're not exploiting yet
│   ├── metric_leverage.md # How the official scorer works
│   ├── ensemble_selection.md # Why we picked the defaults we did
│   └── regels-controle.md # Compliance audit (Dutch)
└── submissions/
    └── barca.csv          # The submitted file
```

---

## How to run

```bash
# Set the data directory
export MTAH_DATA_DIR=/path/to/match-bundle

# Run the pipeline
python -m possessed.pipeline --out barca.csv
```

The match data is NOT included in this repo — it's covered by the competition's own terms. Enrol for MTAH 2027, get the bundle, point `MTAH_DATA_DIR` at it.

---

## What we'd do differently

If we had more time:

1. **Exploit more Smart Tagging signals.** The data audit (`docs/data_audit.md`) identified several usable signals we never got around to using — PLAYERS IN THE BOX timing, set-piece types, substitution windows.

2. **Better ball-occlusion handling.** The linear interpolation works, but a physics-aware model (even a simple Kalman) would handle long occlusions better.

3. **Cross-validation on the graded runs.** The two halves are independent — we could tune on one and validate on the other. We didn't because we wanted to keep the pipeline truly GT-blind, but in retrospect a held-out validation would have been useful for debugging.

4. **More aggressive X on transition frames.** The scorer rewards keeping spells intact, and transition frames are where most errors happen. We could emit X more aggressively around known transition points.

---

## Final notes

The code's in the repo, the CSV validates, and the md5 is pinned. Questions welcome.

— Team BARCA (still looking for a better name)