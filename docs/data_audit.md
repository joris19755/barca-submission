# Data audit: signals the pipeline does not exploit yet

Before building anything I wanted to know what signals I was ignoring. Here's the full
inventory.

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
|---|---:|---:|---:|---:|
| PLAYERS IN THE BOX | — | 97 | 3,444.0 | 27.7 |
| SET PIECES | Throw-in | 42 | 1,058.4 | 20.9 |
| SET PIECES | Goal Kick | 11 | 478.0 | 38.0 |
| SET PIECES | Corner Kick | 10 | 429.2 | 40.5 |
| SET PIECES | Free Kick | 10 | 262.0 | 22.5 |
| SET PIECES | Kick Off | 2 | 33.6 | 16.8 |
| SET PIECES | Kick Off (After Goal) | 2 | 33.6 | 16.8 |
| SET PIECES | Penalty | 1 | 28.0 | 28.0 |
| GOALS | — | 2 | 88.0 | 44.0 |
| PROGRESSION | — | 86 | 1,699.6 | 14.0 |
| CREATING CHANCES | — | 86 | 1,699.6 | 14.0 |
| ATTACKING TRANSITION | — | 86 | 1,699.6 | 14.0 |
| DEFENSIVE TRANSITION | — | 86 | 1,699.6 | 14.0 |
| BUILD UP | — | 86 | 1,699.6 | 14.0 |
| PRESSING | — | 29 | 1,044.0 | 36.0 |

### 1.2 What we already use

- **SET PIECES** (all types): dead-ball intervals and restart priors ✓
- **GOALS**: dead-ball intervals ✓
- **PROGRESSION / CREATING CHANCES / ATTACKING TRANSITION / BUILD UP**: phase-tag soft votes ✓
- **ATTACKING TRANSITION / DEFENSIVE TRANSITION**: strong switch-priors ✓
- **PLAYERS IN THE BOX**: box-scramble soft vote ✓

### 1.3 What we don't use yet

**PRESSING** (29 instances, median 36 s). This is interesting — it marks periods where one team is pressing high. During pressing, the pressing team is *less* likely to have the ball (they're chasing it), but if they win it, they're in a dangerous position. Could be used as an inverse prior or a turnover-risk signal. **[USABLE NOW]**

**Set-piece type differentiation.** We treat all set pieces the same, but corner kicks and free kicks have different restart dynamics. A corner kick restart is more chaotic than a goal kick restart. Could tune the restart confidence or the dead-ball extension window by type. **[USABLE NOW]**

**Kick Off vs Kick Off (After Goal).** We handle the after-goal case (opposite team gets the prior), but we don't distinguish regular kick-offs (start of half) from after-goal kick-offs. Minor. **[USABLE NOW]**

---

## 2. Broadcast camera (not used at all)

The bundle also contains broadcast video data (164,488 frames, 50.53% ball visible). We don't use it because:

1. **Frame mapping.** Broadcast frames don't align with tactical frames — they're a different recording at a different framerate. Mapping them would require cross-recording alignment.
2. **Ball visibility is worse.** 50.53% vs 56.94% for tactical.
3. **No player tracking.** The broadcast feed has no ATD player positions, so we'd lose the distance and superiority signals.

**[NEEDS ALIGNMENT]** — if someone wanted to build the alignment, the broadcast feed has a wider field of view and might catch ball trajectories the tactical camera misses.

---

## 3. Ball speed metadata

The ATD raw file includes ball speed in the third field of each ball record. We compute our own speed from consecutive positions instead. The metadata speed might be more accurate (sensor-level), but:

1. It's only present when the ball is visible (same as our computed speed).
2. We'd need to verify the units and convention.
3. Our computed speed matches the metadata speed within ~5% on spot checks.

**[USABLE NOW]** but low priority — the computed speed is good enough for the p90 gate.

---

## 4. Player speed and acceleration

The ATD raw file has player positions only — no speed or acceleration metadata. We could compute these from consecutive frames, but:

1. Player speed is noisy at 25 fps (position jitter → large speed variance).
2. We'd need a smoothing filter (which introduces latency).
3. The utility is unclear — player speed toward the ball might indicate who's about to gain possession, but the nearest-player distance already captures this indirectly.

**[USABLE NOW]** with smoothing, but unclear benefit.

---

## 5. Substitution windows

The ATD meta file lists substitutions (player in/out with frame numbers). During substitutions, the game is effectively paused — the ball is dead. We don't mark these as D.

Impact: probably small (a few seconds per substitution, maybe 5-10 substitutions in the match). But it's a free signal. **[USABLE NOW]**

---

## 6. Injury time

The ATD meta might contain injury time information (added minutes per half). We don't parse this. If injury time is significant, the graded runs might extend beyond the regular 45-minute half, and our halftime frame calculation could be slightly off.

**[USABLE NOW]** if the meta contains it; **[NOT USABLE]** if it doesn't.

---

## 7. Homography quality per frame

We check that the homography is valid (100% of frames), but we don't use the homography quality score. If some frames have a lower-quality homography, the pitch-space coordinates would be less reliable. We could downweight the evidence on those frames.

**[USABLE NOW]** — the homography CSV has a quality column. Low priority given 100% validity.

---

## 8. What we're definitely not using

**Audio.** The bundle might contain audio tracks. Not parseable, not useful for possession.

**Video frames.** The broadcast video is a rendered MP4. We could run computer vision on it, but that's a completely different approach and outside the scope of this pipeline.

**External data.** No weather, no referee data, no historical match data. The competition only provides the match bundle.

---

## Summary

| Signal | Status | Effort | Impact |
|---|---|---|---|
| PRESSING tags | USABLE NOW | Low | Medium (inverse prior) |
| Set-piece type differentiation | USABLE NOW | Low | Low |
| Substitution windows | USABLE NOW | Low | Low |
| Ball speed metadata | USABLE NOW | Low | Negligible |
| Player speed/acceleration | USABLE NOW | Medium | Unknown |
| Broadcast camera | NEEDS ALIGNMENT | High | Medium |
| Homography quality | USABLE NOW | Low | Negligible |
| Injury time | USABLE NOW | Low | Negligible |

The biggest missed opportunity is probably PRESSING tags — 29 instances, median 36 s, and they directly indicate which team is *not* in possession. That's a clean inverse signal we could add in an afternoon.