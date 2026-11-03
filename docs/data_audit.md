# Data audit: signals the pipeline does not exploit yet

Analysis only — no pipeline changes. Scope: everything in the match bundle
(`./data/` flat files; `./mtah-data/` symlink bundle) compared against what
`possessed/pipeline.py` actually consumes (tactical ATD ball + player positions with
team mapping, ATD-meta team names, Smart Tagging `SET PIECES` + `GOALS` only, linear
ball fill ≤ 2 s, smooth50 fallback, published graded blocks).

Method: raw ATD files parsed streaming (frame_id → ball x,y,speed + 46 slot
positions), Smart Tagging parsed with ElementTree, homography CSVs with pandas.
All figures measured on the bundle files present in this workspace (visibility numbers
reproduce DATA.md exactly: tactical ball 113,488/199,319 = 56.94%,
broadcast 164,488 frames, 50.53% visible).

Tag legend: **[USABLE NOW]** = parseable today, no cross-recording work;
**[NEEDS ALIGNMENT]** = requires broadcast↔tactical frame mapping; **[NOT USABLE]** =
cannot be exploited, with reason.

---

## 1. Smart tagging inventory (638 instances)

### 1.1 Full breakdown, code × Type

| code | Type | n | total s | median s |
|---|---|---:|---:|---:|
| PLAYERS IN THE BOX | — | 97 | 3,444.0 | 27.7 |
| BALL IN FINAL THIRD | — | 93 | 2,800.5 | 27.0 |
| BALL IN THE BOX | — | 72 | 1,303.3 | 17.4 |
| PROGRESSION | — | 66 | 1,244.7 | 17.6 |
| DEFENDING IN MIDDLE THIRD | — | 66 | 1,244.7 | 17.6 |
| SET PIECES | Throw-in | 26 | 910.0 | 35.0 |
| SET PIECES | Corner Kick | 12 | 420.0 | 35.0 |
| SET PIECES | Goal Kick | 10 | 350.0 | 35.0 |
| SET PIECES | Free Kick | 5 | 175.0 | 35.0 |
| SET PIECES | Kick Off (After Goal) | 4 | 20.0 | 5.0 |
| SET PIECES | Kick Off (Start) | 2 | 10.0 | 5.0 |
| CREATING CHANCES | — | 30 | 900.0 | 30.0 |
| DEFENDING IN DEFENSIVE THIRD | — | 30 | 900.0 | 30.0 |
| LONG BALL | — | 29 | 381.3 | 12.4 |
| ATTACKING TRANSITION | — | 24 | 371.6 | 15.4 |
| DEFENSIVE TRANSITION | — | 24 | 371.6 | 15.4 |
| BUILD UP | — | 22 | 440.4 | 20.5 |
| DEFENDING IN ATTACKING THIRD | — | 22 | 440.4 | 20.5 |
| GOALS | — | 4 | 660.1 | 169.3 |

Totals: 638 instances, 16,387.8 s of tagged intervals (they overlap, 205% of match
length — the codes are concurrent phases, not a partition).

### 1.2 What the pipeline uses vs ignores

Used: `SET PIECES` (59, all six Types) and `GOALS` (4). That is **63/638 = 9.9% of
instances and 15.5% of tagged time**. The other **575 instances / 14,502 s (84.5%) of
tagged time are untouched.**

### 1.3 What the unused codes mean and carry

- **Paired mirror codes (142 shared intervals, 4 pairs, 284 instances).** Every
  `PROGRESSION` interval is *the exact same interval* as a `DEFENDING IN MIDDLE THIRD`
  (66/66), `CREATING CHANCES` == `DEFENDING IN DEFENSIVE THIRD` (30/30),
  `ATTACKING TRANSITION` == `DEFENSIVE TRANSITION` (24/24), `BUILD UP` ==
  `DEFENDING IN ATTACKING THIRD` (22/22). In 140/142 shared pairs the two instances
  carry **opposite Team tags** (e.g. `PROGRESSION/Barcelona` paired with
  `DEFENDING IN ATTACKING THIRD… DEFENDING IN MIDDLE THIRD/Atletic Club`). Net effect:
  **every phase interval already names both the team with the ball and the team without
  it** — a free per-frame possession-side prior that collapses to nothing only where
  Team is N/A (4 CREATING CHANCES intervals).
- **Phase-code union covers 68.1% of graded frames**; the attacking half of the pairs
  (PROGRESSION/CREATING CHANCES/ATTACKING TRANSITION/BUILD UP) alone covers **40.6%**.
  SET PIECES covers 27.6% and GOALS 10.4% of graded frames today.
- **`BALL IN FINAL THIRD` (93) carries `Side` = Central/Left/Right** on all 93 — the
  flank the ball entered on, covering 36.9% of graded frames. **`BALL IN THE BOX` (72)
  carries `Direction of ball entry`** (Horizontal 34 / Vertical 25 / Diagonal 13).
  **`PLAYERS IN THE BOX` (97, 45.7% of graded frames) carries `Max Players in the box`
  1…7+** — a signed-box-density/overload read. All three encode who is attacking where,
  with possession implications the current pipeline never sees.
- **Transitions (48 instances, 5.7% of graded frames):** ball visibility 1 s before
  AT-ATKING/DEFENSIVE TRANSITION start = 87%, after = 88% (vs 62–64% around BUILD UP),
  i.e. transitions mostly start with the ball already visible — directly usable as
  turnover/switch moments.
- **Team tags:** Barcelona 314, Atletic Club 288, N/A 36. The 36 N/A are exactly the
  26 Throw-ins + 6 Kick Offs (all SET PIECES with N/A: 32) + 4 CREATING CHANCES. Non-SP
  codes almost always carry a side.

### 1.4 Dead-ball precision/recall gain from unused subtypes

Current restart detection (first visible run ≥ 0.4 s inside a SET PIECES window) was
measured per Type:

| Type | n | D frames before restart | ball visible inside those D frames |
|---|---:|---:|---:|
| Throw-in | 26 | 2,966 | 0.0% |
| Corner Kick | 12 | 2,073 | 0.0% |
| Goal Kick | 10 | 316 | 0.0% |
| Free Kick | 5 | 879 | 0.0% |
| Kick Off (After Goal) | 4 | 365 | 0.0% |
| Kick Off (Start) | 2 | 90 | 0.0% |

The guess **never mislabels a visible frame as D** (0.0% false-D across all Types) and
finds a persistent run in 59/59 windows — but ball *invisibility inside the window*
is only 25–41% for Throw-in/Corner/Free Kick (windows are 35 s, mostly live play after
the restart). **No unused subtype marks ball-out moments**: only SET PIECES windows
have dead-ball semantics; the paired phase codes and the box/entry codes are live-play
phases. So dead-ball precision/recall gain from unused subtypes ≈ **0 on the restart
the restart itself** — the gain is elsewhere (§4.3, possession priors). Two residual GOALS/SP
facts still belong in the picture: 1 of 4 `Kick Off (After Goal)` windows has no ≥0.4 s
visible run
(fallback to window end), and GOALS windows are 3–169 s long with ball visibility
3–16% — already handled as D-outright.

**[USABLE NOW]** for findings 1.3 (both-team prior, flank/direction/overload tags,
transition moments); **[USABLE NOW]** with the caveat that unused subtypes do *not*
improve restart timing.

---

## 2. Broadcast vs tactical alignment

Facts: tactical 199,319 frames, broadcast 164,488, both 25 fps, no mapping file
(DATA.md: "not synchronised… your problem"). Empirical tests on 1-second bins:

- Identity mapping over the overlapping index (2,143 s where both have ball):
  corr(ball x) = **−0.071**, corr(ball-visibility count) = **0.012** → not aligned at 0.
- Time-shift scan ±600 s on ball x: best corr **0.533 at s = −160 s** (also −159…−162,
  0.47–0.53). A plateau at one lag, not a sharp peak, and corr 0.53 over thousands of
  seconds is what you get when both cameras follow the same ball dynamics but the
  mapping is not a constant offset (broadcast has cuts, replays, zooms — 123 invalid
  homography stretches, median 279 frames, max 2,719 ≈ 109 s).
- Visibility-onset matching (141 tactical onsets vs 131 broadcast): best ≈ 50/141
  onsets matched within ±5 s at shift 157–158 s — consistent with the −160 s plateau
  but only 35% recall, far below what a true constant mapping would give.

**Conclusion: not alignable within a simple mapping (constant offset or affine
frame map).** Why precisely: the broadcast timeline is piecewise — full-speed play,
replays (which repeat trajectory segments, destroying one-to-one monotone maps), and
camera cuts that drop whole stretches (34.2% of broadcast frames have no homography
in 123 stretches). Any single-offset fit leaves 47%+ residual error; a piecewise map
would need content-based matching (e.g. per-restart anchoring on smart-tagging events)
which is a project, not a fit. **[NEEDS ALIGNMENT — no simple mapping exists; a
piecewise/event-anchored map is a sprint-sized sub-project.]**

Coverage arithmetic *if* aligned (naive, unaligned shares only): broadcast ball is
visible on 50.5% of its own frames vs tactical 56.9% — broadcast would *not* be a
strict superset; it could at best add frames where its 50.5% overlaps tactical's 43.1%
missingness, upper-bounded by roughly the product under independence (~21% of tactical
frames), but this cannot be quantified without the piecewise map.

---

## 3. Ball missingness profile (tactical)

Overall: 85,831/199,319 frames missing (43.06%); graded: 40.69% missing (matches
DATA.md's 41%).

Gap-length distribution (runs of consecutive missing frames):

| range | gaps (all) | missing frames | % of all missing | graded gaps | graded frames | % graded missing |
|---|---:|---:|---:|---:|---:|---:|
| ≤ 0.25 s (≤6 fr) | 34 | 75 | 0.09% | 14 | 31 | 0.08% |
| ≤ 0.5 s (≤13 fr) | 40 | 133 | 0.15% | 16 | 53 | 0.13% |
| ≤ 1 s (≤25 fr) | 43 | 185 | 0.22% | 17 | 75 | 0.19% |
| ≤ 2 s (≤50 fr) | 44 | 211 | 0.25% | 17 | 75 | 0.19% |
| > 2 s | 142 | 85,620 | **99.75%** | 133 | 64,568 | **99.81%** |

186 gaps total; median 230.5 frames (9.2 s), p90 840 fr (33.6 s), max 8,689 fr
(347 s — halftime-adjacent). **Missingness is overwhelmingly block-structured, not
flicker:** the pipeline's ≤2 s interpolation covers only 0.25% of missing frames;
99.75% sits in long blocks. Per block: pre-match 98.4% missing, halftime 5.9%,
post-whistle 98.5%, H1 40.7%, H2 40.7%.

Where (interpolated ball position at missing frames, x-terciles):
- All: left 39.7% / middle 38.6% / right 21.7% (control all-frames 32.2/43.5/24.4) —
  skewed toward the wings and away from the right.
- H1 missing 36.9/24.5/38.6 vs all-frames 33.4/34.9/31.7 → missing concentrated in
  both wings; H2 missing 50.4/31.0/18.6 vs 38.4/38.8/22.9 → heavily skewed left.
  (Per-half attack direction flips, so "left" is one team's attacking wing per half —
  missingness tracks the ball's actual territory, i.e. it follows play, not a fixed zone.)

Correlation with conditions (graded, halftime excluded):
- Homography reprojection quartiles: missing 43.8 / 38.7 / 42.0 / 38.3% (corr = −0.019)
  → **camera-fit quality does not predict ball loss.**
- Tracked-object count: 95.0% missing when n≤10, 81.5% at 11–18, **34.2% at 19–22**,
  60.7% at ≥23 (corr = −0.336) → missingness is driven by **tracker-wide dropout /
  occlusion events**, not a specific camera mode; minute-level rates range 0–100%
  (mean 40.7%, sd 29.0% over 106 graded minutes), with the worst minutes at 94–100%
  (goal/crowd sequences) and best at 0%.

**[USABLE NOW]** — this profile is computed from the tactical file alone and already
informs the pipeline: the ≤2 s fill almost never fires (0.25% of gaps); the real
decision surface is the 142 long gaps, whose boundaries (visibility onsets, mean 141)
coincide with restarts the tagging already marks.

---

## 4. Player/ball fields available

Per-frame ATD line: `frame_id : 46×(x, y, speed_m/s) : ball(x, y, speed_m/s)` —
**positions, speeds, team membership (via meta), and nothing else.**

- **x, y:** present for every slot each frame (40.0% non-NaN across all slot×frame =
  ~20.5 visible objects per graded frame; p5 14, p95 22; 0 graded frames with no
  tracked objects). Normalised 0–1.
- **speed (3rd field):** present but almost always NaN for players (≈0 useful);
  ball speed non-NaN on only 5.0% of tactical frames (3.4% broadcast) → compute ball
  speed yourself from consecutive visible positions: median 19.9 km/h, p90 62, p99 181
  (n = 113,303 valid steps).
- **Jersey/team:** no identities; team via meta (`Barcelona` first team, 24 slots;
  `Atletic Club`, 22 slots) — pipeline already uses this. **Keeper detection: yes,
  meta `position_type` = `Goalkeeper` on Track 24 (Bar) and Track 46 (Ath) only —
  unused today, enables “nearest outfield player” and keeper-zone features.**
- **Homography validity:** tactical **100.00% (199,319/199,319)**; broadcast 65.81%
  (108,248/164,488) in **123 invalid stretches, median 279 fr, max 2,719 fr**.
- **Pitch-space features now computable [USABLE NOW]:** metric distances (pitch
  105.3×68 m), ball speed km/h, per-team control polygons, ball-territory thirds with
  real metres, **numerical superiority**: sampling graded frames, players within 20 m
  of the ball show unequal team counts on **69.7% of sampled frames** (|diff| = 1: 41%,
  2: 17%, ≥3: 9.6%) — overload detection is feasible and discriminative. Attack
  direction per half (`attack_direction_first_half` in meta) is also unused.

---

## 5. Other unused bundle content

- **ATD-meta `ProviderParameter`s:** `first_half_start/end`, `position_type`,
  `position_index/x/y`, `attack_direction_first_half` — only team names + slot→team
  are read today. **[USABLE NOW]**
- **Broadcast homography + broadcast ATD:** whole recording ignored (see §2 for the
  alignment blocker). **[NEEDS ALIGNMENT]**
- **Smart Tagging ROWS section:** only RGB colors of codes — no signal. **[NOT USABLE]**
- **`Max Players in the box` string values, `Side`, `Direction of ball entry`:**
  present on 97/93/72 instances — parsed by the loader but never read. **[USABLE NOW]**
- **ATD `ShirtNumber` = slot index** (not a person) — nothing recoverable. **[NOT USABLE]**
- **Broadcast `FileName`** ("Barça - Athletic Club 2-1") — external fact (confirms
  2-1 scoreline consistent with 4 GOALS tags) but per RULES it must not be used to
  hand-label anything. **[NOT USABLE for labels]**

---

## Top 3 untapped signals (by expected possession-labeling impact)

1. **Dual-team phase intervals (142 paired codes → possession-side prior over 68.1% of
   graded frames).** Every phase interval names ball-side *and* opponent-side; using
   the attacking member as a soft possession vote at transitions (ATTACKING/DEFENSIVE
   TRANSITION pairs sit exactly on turnovers, ball visible 87–88%) attacks spellF1
   directly — transition timing is where spellF1 lives. **[USABLE NOW]**
2. **Pitch-space dynamics from fields we already parse: ball speed, metric geometry,
   numerical superiority (unequal on 69.7% of frames), GK exclusion, attack direction.**
   Turns the raw nearest-player guess into a state with hysteresis informed by who
   actually has the better ball-side structure; directly reduces possession churn that
   splits spells. **[USABLE NOW]**
3. **Spatial/density tags: `Max Players in the box` (45.7% of graded), `Side` flank
   entry (36.9%), `Direction of ball entry`** — free location+pressure context for the
   ambiguous frames (box scrambles, occlusions) where nearest-player flips. **[USABLE
   NOW]** Broadcast coverage (§2) would be ranked second if a piecewise alignment were
   cheap — it is not: **[NEEDS ALIGNMENT, sprint-sized sub-project]**

*Known gaps in this audit:* cross-correlation used 1-s ball-x/visibility bins, not full
player-trajectory correlation (player-level cross-corr skipped for budget); broadcast
“added coverage where tactical ball missing” left as an independence upper-bound
because no simple alignment exists (§2); no evaluation of phase-interval overlap with
the public 5-minute GT beyond coverage shares.