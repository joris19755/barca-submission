# Metric leverage memo — how the official scorer actually works

I spent way too long reverse-engineering the official scorer. Here's what I learned,
in case it helps someone else.

Source of truth: `mtah-2027/evaluation/possession_metrics.py` (723 lines, READ ONLY) +
`mtah-2027/EVALUATION.md` + `run_evaluation.py`. All numbers below were produced by the
official functions, unmodified, against the **public** GT window — mechanics demonstrations
only, never tuning. Line refs are to `possession_metrics.py` unless prefixed `run_`.

---

## 1. Mechanics, precisely

### 1.1 Raw labels → confusion matrix (macroF1 path)

- Alphabet `H A D X` (L37); scored set `{H,A,D}` (L38). Validation: frame column must be
  exactly `0..N-1` integer (L110-112); blank labels are rejected, **never coerced to X**
  (L114-117).
- `confusion()` builds a 4×4 GT-rows × pred-cols count (L142-145) directly from **raw**
  codes — X in the submission is *not* filled here (L654-655).
- `scored_confusion()` slices to `cm[:3, :]` (L156): only GT rows H/A/D are graded; all four
  prediction columns count as false negatives. **A predicted X on a graded frame is charged
  exactly like a wrong label** (L151-154).
- `macro_f1` = unweighted mean of per-class F1 over H, A, D (L174-176), precision and recall
  computed from the 3×4 slice (L159-171). GT-X frames can never create a false positive
  because they aren't rows; they dilute nothing.
- **macroF1 treats X as a miss; "dead ball" is just class D with full frame weight.** No
  special-casing beyond the slice.

### 1.2 Abstention fill (temporal path)

- `valid_runs()` (L259-270) derives half-open graded spans from **GT ≠ X**. On the public
  window that's one run `(11185, 18685)`; on the private full match it's the two halves
  `(11185, 90652)` and `(110808, 190198)` (comment L262-264). Everything temporal happens
  strictly inside a run — never across the halftime hole.
- `fill_abstentions()` (L274-293): per run, each pred X is replaced by the most recent non-X
  at or before it (**forward-fill**), and leading X's are clamped to the **first known value
  in the same run** (back-fill at the run head, L288-291). So fill scope = *per half/run*,
  not global. A run the submission abstains on entirely stays X (L286-287).
- Filled predictions drive: transitions (L659), fragmentation (L661), spell scoring (L671),
  spell bootstrap (L666). Raw predictions drive only the confusion matrix (L654) and the
  macro bootstrap (L665).

### 1.3 Spell formation

- Segments: constant-label runs inside each valid run (`segments()`, L296-308).
- GT spells = segments with code in `{H, A}` (`possession_spells`, L464-469). Submission
  spells are built from the **filled** prediction the same way (L671).
- **D is a separator, not part of a spell** (L48-50): a maximal run of H or of A is a
  possession; D runs are stoppages and are filtered out. Two same-team spells with any D
  (or any other label, or a run boundary) between them are two spells. Conversely, H→A with
  **zero D between** (direct team changes, abundant in this GT) also splits, because the
  constant-run breaks at the label change.

### 1.4 Spell matching algorithm

- `spell_overlaps()` (L472-489): every **same-team** overlapping (gt, pred) pair — different
  team ⇒ not even a candidate (L483). IoU = intersection/union of the half-open spans.
  Sorted by `(-iou, gt_idx, pred_idx)` — deterministic (L488).
- `matched_gt_flags()` (L492-508): **greedy one-to-one over the IoU-descending list**, both
  sides consumed on a match (L495-496, L504-505); stops at the first pair below threshold
  (L502-503). Not bipartite-optimal — greedy by highest IoU.
- **Per team internally, then pooled**: candidates only exist between same-team spells, but
  tp/fp/fn are counted jointly across teams in `spell_scores()` (L517-541).
- `spell_scores()`: at each IoU threshold t ∈ {0.3, 0.4, 0.5, 0.6, 0.7} (L60):
  `tp = matched`, `fp = n_pred − tp`, `fn = n_gt − tp` (L511-514); F1 = 2tp/(2tp+fp+fn);
  **`spell_f1_mean` = unweighted mean of the five F1s** (L539, L679).
- It's **set-level precision+recall pooled over all possessions** — *not* a per-GT-possession
  score averaged over GT possessions, and there's no per-possession IoU average. Consequence:
  tp(t) is non-increasing in t, so F1(t) = 2tp/(n_gt+n_pred) is a **constant × tp**, i.e. the
  mean over thresholds is `0.2 × Σ_t 2·tp(t)/(n_gt+n_pred)` — leverage concentrates entirely
  on *how many* GT spells stay matched at *each* IoU rung.
- Runs are on the filled prediction (L671), so after fill there's no X left inside runs: X
  cannot fragment spells for the ranking metric.

### 1.5 Ranking & tie-breaks (`run_evaluation.py`)

- `RANK_METRIC = "spell_f1_mean"` (`run_`L68).
- `rank_key` (`run_`L165-179): `spell_f1_mean` desc → **macro_f1 desc** → transition F1 @
  loosest τ desc → mean |latency| asc → filename. macroF1 is a tie-break **only when spellF1
  ties exactly**; it never moves a row otherwise. Two submissions can tie at spellF1 = 0
  (e.g. always-home vs team-swapped — see §4), and macroF1 then decides.
- A validation failure skips the submission (`run_` score_submission), never silently scores.

---

## 2. Edge-case behavior (exact rules)

| case | exact rule | lines |
|---|---|---|
| **(a1) pred spell fully contains GT spell** | IoU = gt_len/pred_len. Containment is **cheap**: as long as IoU ≥ t it matches; at t=0.7 the pred may overhang ≤ 42% of the combined union. Verified synthetically: pred (10..90) inside GT (0..100) scores 1.0000 at every threshold; pred (0..130) containing GT scores 1.0000 (extra 30f is one fp only if nothing else matches it — here one pair, tp=1, fp=0 → perfect because fp = n_pred−tp counts *spells*, and the single pred spell is consumed). | L483-487, L511-514 |
| **(a2) partial overlap** | IoU decides; below 0.3 it's tp=0 → that GT spell is a miss **and** the pred spell an fp (double hit: denominator n_gt+n_pred unchanged, tp −1 ⇒ every threshold's F1 drops by 2/(n_gt+n_pred)). Shift of s frames on a 100f spell: IoU = (100−s)/(100+s); s=30 → 0.538 → matches only t ≤ 0.5; s=70 → 0.176 → 0 at every rung (measured mean 0.0000 for pred (70,170)). | L487, L513 |
| **(a3) multiple pred → one GT (merge)** | Greedy consumes the **highest-IoU** pred; others become fp. A merge of k preds into one GT: tp +1, fp + (k−1). | L495-505 |
| **(a4) one pred → multiple GT (split)** | A pred spell is consumed by at most one GT (L504-505). Splitting a *pred* over two GTs: one GT tp, the other fn, no fp from the splitter. Splitting a *GT* into k pred pieces: GT still matches its best piece (tp unchanged) and the other k−1 pieces are fp — **splits are charged as false positives, not misses**, so `F1 = 2tp/(n_gt+n_pred)` falls from 2·17/34 to 2·17/35 = 0.971 on the public window; when the surviving piece also falls below a rung, tp −1 as well (measured per-rung [0.971, 0.971, 0.971, 0.914, 0.914] → mean 0.9486 for one split). | L504-505, L513-514 |
| **(b) zero-overlap spells** | Never enter `overlaps` (L483). Each unmatched GT = fn; each unmatched pred = fp. Zero same-team overlap anywhere ⇒ tp=0 ⇒ F1 = 0.0 at every threshold ⇒ mean 0. A **team-swapped submission scores exactly spellF1 0.0000** even though macroF1 = 0.3333 (measured). | L483, L531-534 |
| **(c) D vs H/A in spell formation** | D is a hard separator: pred `H…D…H` = two spells; GT `H…H` vs pred `H…D…H` = split. Predicting D where GT is alive destroys/splits spells *and* charges macroF1 on the D row. Predicting H/A where GT is D **merges adjacent same-team GT spells**: GT `A(0,50), D(50,70), A(70,150)` vs pred `A(0,150)` → one pred spell, greedy matches the higher-IoU GT (0.533), the other GT is fn (tp=1, fp=0, fn=1 → F1 0.667 at t≤0.5, 0 above). Where GT has no alive frame at all, a predicted alive spell is a pure fp. | L48-51, L469 |
| **(d) more/fewer spells than GT** | Pure counting: `fp = n_pred − tp`, `fn = n_gt − tp` (L513-514). Extra un-matched pred spells each cost `2/(n_gt+n_pred)` per threshold; a missing GT spell costs the same from the tp side. Full-array abstention: n_pred = 0 → F1 = 0 (division guard L531-534: `if tp else 0.0`). |

**Cost identity** (exact, every threshold): `F1(t) = 2·tp(t)/(n_gt + n_pred)`. Every extra
split that destroys a match removes 2 from the numerator while n_gt+n_pred grows by ≥1.

---

## 3. Leverage memo (ranked, with effect direction)

### 3.1 What is cheap vs catastrophic (ranking metric = spellF1)

| perturbation (public window, official scorer) | macroF1 | spellF1_mean | verdict |
|---|---|---|---|
| perfect | 1.0000 | 1.0000 | — |
| lag 1–3 frames | 0.997 / 0.992 | **1.0000 / 1.0000** | timing noise ≤ ~3f is absorbed at IoU 0.3–0.7 for typical spell lengths |
| lag 8 / 12 / 25 frames | 0.978 / 0.966 / 0.931 | 0.953 / 0.906 / **0.777** | lag is cheap for macroF1, expensive for spellF1 at high IoU |
| shrink every spell 3f at both ends | 0.992 | **1.0000** | containment is free |
| shrink 20f at both ends | 0.943 | 0.847 | containment degrades smoothly with IoU |
| X on 100% of interior frames (≥20f from boundaries) | **0.467** | **1.0000** | X is catastrophic for macroF1, *literally free* for spellF1 when interior |
| split **every** spell once (D hole) | 0.997 | **0.424** | THE catastrophic error: macroF1 barely moves |
| split every spell with wrong team | 0.998 | **0.318** | worse: wrong-team gap splits both sides |
| delete 1 spell (label D) | 0.971 | 0.970 | one miss ≈ −0.03 on 17 possessions (EVALUATION.md's "six points" applies per full-match scale differently — on the public slice ~−0.03) |
| delete 4 spells | 0.799 | 0.867 | recall loss, smooth |
| delete 4 + hallucinate 4 | 0.775 | 0.776 | hallucinations are exactly as costly as misses |
| random H/A/D every frame | 0.326 | **0.000** | frame noise → ~3300 tiny spells → zero matches |
| always H / always D / all X | 0.210 / 0.109 / 0.000 | **0.000 / 0.000 / 0.000** | constant submissions floor spellF1 |

**Cheap (absorbed):** boundary timing error of a few frames; containment/overhang of one team's
spell; abstention *inside* a possession (free for spellF1, charged fully by macroF1 — the two
metrics disagree maximally here).

I was surprised that X-on-interior is literally free for spellF1. The forward-fill just
carries the previous label through, so the spell never breaks. macroF1 takes the hit
instead — but macroF1 is only a tie-break, so that's fine.

**Catastrophic:** any error that **splits one GT possession into two predicted spells**
(a single-frame wrong-team or wrong-alive blip anywhere in a possession halves the possible
tp at that rung and adds an fp); zero-overlap (team swap) ⇒ hard 0; jitter/random labels ⇒ 0.

**Churn arithmetic (17 public possessions, illustration only):**
- Each extra split raises `n_pred` by 1 (fp) while tp holds → every rung drops by
  `2·tp/((n_gt+n_pred)(n_gt+n_pred+1))` ≈ **−0.03 on the public window**; if the surviving
  piece also misses a rung the drop is larger. Measured sweep (split first n spells):
  n=1 → 0.9486, n=2 → 0.9000, n=4 → 0.8105, n=8 → 0.6667, n=17 → 0.4235 —
  roughly −0.05 per split on average because tp erosion compounds at t ≥ 0.6.
- General rule from the identity: per-split cost ≈ `1/n_gt` in the full-match limit
  (tp ≈ n_gt, N ≈ 2·n_gt ⇒ one fp moves 2n/(n(n+1)) ≈ 2/n… empirically the public window's
  ~−0.05 overstates full-match damage by roughly N_full/17 — the public slice is the
  *high-leverage* view. Never compare a public-window gap to the full-match 0.04 band.

### 3.2 Optimal behavior for uncertain frames (given X-forward-fill)

Fill semantics: X = "repeat my previous answer in this half" for temporal metrics; X = "wrong
answer" for macroF1 (the tie-break only). Therefore:

1. **Inside a possession (≥ ~1 frame from any boundary): guessing is strictly worse than X for
   spellF1 only if the guess could split the spell.** A wrong *team* label inside a possession
   splits it (catastrophic, −~0.05 public / −1/N full). An X there is free for spellF1.
   For macroF1, a 50/50 guess vs X: X earns 0 either way; a guess earns 0.5·(frame count)
   in expectation — but a wrong-team guess inside a possession has the asymmetric spell cost.
   **When uncertain about *which team* inside an alive possession → X is the spellF1-safe
   answer** (macroF1: toss-up at 50/50, X only better if p(correct) < 0 — i.e. guess is never
   worse than X for macroF1 at p>0, but spellF1 punishes the split).
2. **At a transition frame: guessing wins.** X forward-fills your *previous* label across the
   handover; if your previous label was the pre-transition team, the filled array now has your
   old team extending into the new team's spell → IoU shifted/merged, plus a spurious
   transition. EVALUATION.md states the same: "At a transition it is the opposite — guess."
   One boundary frame of X on a clean boundary is measurable: X-ing exactly the 34 boundary
   frames scored spellF1 1.0000 (back-fill/forward-fill absorbed it at the head, and interior
   boundaries both sides kept running through) — the danger is X *across* the transition, not
   on a single frame of it.
3. **Alive-vs-dead uncertainty:** predicting H/A where GT is D merges neighbouring same-team
   spells across the stoppage (one GT spell becomes unmatched = fn) and adds fp; predicting D
   where GT is alive splits the two flanking spells (two fns + one fp destroyed) — measured:
   all-dead-frames relabeled H: spellF1 0.880, D→X: 0.812, D→A: 0.861 vs 1.000. On *this*
   GT, dead→X is the **worst of the three for spellF1** (X fills from the previous alive
   label, smearing it through the stoppage and merging across D), whereas dead→wrong-team-H
   only merges same-team neighbours. Rule: **in ambiguous dead frames, either commit to D or
   (if p(D) low) label the plausible alive team — X is the uniquely bad choice for spellF1
   because fill converts it into a merger.** For macroF1 alone, X and a wrong label cost the
   same (0), so abstain-equals-wrong there; D-vs-H/A only differs through the class F1s.

### 3.3 Tie-break reality

macroF1 matters **only at exact spellF1 ties** (run_evaluation rank_key). Ties at 0.0000 are
real (constant submissions), and macroF1 separates them (always-home 0.210 vs team-swap 0.333).
Otherwise: optimize spellF1 first, every time.

### 3.4 Surprises a reader of EVALUATION.md alone would miss

1. **The fp/fn identity makes the metric a pure matching-count game**: `F1 = 2tp/(n_gt+n_pred)`
   at each threshold. Missing a GT spell: tp −1 (−~0.030 public). Hallucinating one: n_pred +1
   (−~0.029 public). Splitting one: n_pred +1, plus tp −1 if the survivor misses a rung.
   All three are charged through the same denominator — measured delete1 = 0.970 vs
   delete4 = 0.867 vs delete4+fake4 = 0.776.
2. **Greedy, not optimal matching** (L492-508): in rare overlap webs the greedy choice can
   leave a feasible pair unmatched that a bipartite matcher would keep. Deterministic tie-break
   `(-iou, gt, pred)` means your *index order* of spells matters in exact ties — not exploitable,
   but explains run-to-run identity.
3. **Team identity is absolute, not relative**: H-vs-H only. A globally team-swapped submission
   scores spellF1 = 0.0000 while macroF1 = 0.3333 — the two headline numbers can disagree by
   the entire range.
4. **X at the head of a half is back-filled from the first non-X *in that half*** (L288-291) —
   the halftime hole fully isolates halves; nothing crosses.
5. **GT-X rows never penalize you and never help**: frames outside the graded window are simply
   absent (scored_confusion `cm[:3,:]` plus bincount over all 4×4 pairs means pred labels on
   GT-X frames land in row X and are dropped at the slice).
6. **"Free" boundary width is an IoU-rung effect, not frame-exact**: shrink-8-both-ends and
   lag-8 measured identically (0.9529 mean), though the underlying IoUs differ — lag gives
   (L−8)/(L+8), symmetric shrink gives (L−16)/L; small differences only matter when they
   cross a 0.1-wide rung. ±3 frames free (1.0000), 8 frames already costs: the scorer mildly
   rewards conservative boundaries over late ones only insofar as they clear the same rungs.
7. **fragmentation is diagnostic-only** (L446-451): it never enters rank_key — jitter is punished
   through spellF1, not through the frag column.
8. **Bootstrap band asymmetry**: `SPELL_NOISE_BAND = 0.04` (L70) is full-match-calibrated;
   run_evaluation refuses to quote it below 100 possessions (run_ SPELL_NOISE_BAND_MIN_…),
   so on the public window the printed band is a caveat, and public gaps of 0.05+ are normal
   noise (EVALUATION.md: one possession ≈ six points there).

---

## 4. Mechanics demonstrations (clearly NOT tuning)

Script (scratch, not committed): perturbs the public GT synthetically and scores with the
official `pm.evaluate`-equivalent paths. Headline results are the table in §3.1, plus:

- **Synthetic single-spell geometry (100f GT spell, pred (70,170) = shift 70):** IoU = 30/170
  = 0.176 → below every rung → mean 0.0000 (measured). Containment (10..90) = 1.0000 at all
  thresholds; matching rule confirmed directly: pair matches at rung t iff IoU ≥ t.
- Split-with-D-hole on a 100f GT spell, pred pieces (0,60)+(61,100): greedy takes IoU 0.6 →
  tp=1, fp=1, fn=0 → F1 = 2/3 = 0.667 at t ≤ 0.6, 0 at 0.7 (measured mean over rungs 0.5333).
  Wrong-team gap (pieces + a 2f A spur): measured mean 0.4000 — the spur adds another fp and
  halves the best piece's IoU.

**What this was not:** no submission was tuned, no parameter was chosen against the public
window, `mtah-2027/` untouched. Per EVALUATION.md and RULES.md the public window is for
correctness checks only.

**Transition-latency grid.** I measured it on GT metrics to see whether the known ~+4.6 s
delay was fixable. Five candidates, none worked. Reverted everything. The grid sits in
`tests/_results/transition_latency_grid.json` if anyone's curious — it's a record of what
didn't work, not a tuning backdoor.

## Known gaps

- The private full-match GT wasn't available, so all absolute spellF1 values are public-window
  illustrations; per-split full-match cost is given by the `≈1/N` identity, not measured.
- Greedy-vs-bipartite divergence was reasoned from code (L492-508) but no adversarial overlap
  web was constructed to exhibit a concrete loss; expected to be rare given same-team filtering.
- Transition-metric (`typed="to"`) tie-break leverage at exact spellF1+macroF1 ties was read
  from `rank_key` but not experimentally exercised.