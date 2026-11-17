# CoFi Labs: More than a Hack 2027, Phase 1 (Ball Possession)

**Team:** CoFi Labs
**Challenge:** Metrica Sports / FC Barcelona, "More than a Hack 2027, Phase 1: Ball Possession"
**Language:** English

---

## The short version

We wrote a program that looks at every frame of the Barça–Athletic tracking feed and says who has the ball: H (home), A (away), D (dead ball) or X (we don't know). That's 199,319 frames at 25 fps. It runs in a few seconds, and it gives the same file every time.

## How we stayed inside the rules

We stuck to the rules. A few things you'll notice:

- We didn't tune anything on the public ground-truth window. That window is only five minutes long, about 2.5% of the match, so picking settings to fit it would mostly mean fitting noise. Every setting came from how football works, not from the scores.
- Nothing was labelled by hand. The input is the official Smart Tagging and tracking files from the match bundle.
- No randomness anywhere. The code is numpy and the standard library, and we pinned the line endings so the output file is byte-identical on Linux, macOS and Windows.
- The file has one column pair, `frame,label`, covers frames 0 to 199318, and uses only H, A, D and X.

The full compliance check is in `docs/regels-controle.md` (in Dutch, sorry to the judges who don't read it).

## How it works

### 1. Dead ball comes from the tags

The match bundle has Smart Tagging events like corner kick, goal kick, free kick and goal. When a set piece starts, we mark the frames as dead until the ball is visible again and moving, which is the restart. Goals are dead straight away, because nobody has possession during a celebration. After a goal, the team that conceded gets the ball at the kick-off.

About 15% of frames end up as D, which looks about right for a real match.

### 2. Filling small gaps in the ball

The tactical camera sees the ball roughly 57% of the time. If the ball drops out for two seconds or less (50 frames), we draw a straight line between the last and next known positions. Anything longer stays unknown. We'd rather admit we don't know than invent a path through a long blind spot.

### 3. Turning pixels into metres

The coordinates come in as 0 to 1 across the pitch. The homography for this match is valid for every frame, so we convert to real metres on a 105.3 × 68 m pitch, using the numbers in the competition's `games.py`. From there we work out:

- the nearest outfield player for each team (goalkeepers are left out, since they don't contest the ball 40 metres upfield),
- how many players each team has within 20 m of the ball,
- the ball's speed in km/h, from consecutive visible positions,
- which way each team is attacking in each half.

### 4. Each team gets a score every frame

Plain "closest player has the ball" is noisy. The nearest player is often running toward the ball, not with it. So each frame, each team gets an evidence score built from a few things:

- **Distance:** a closer outfield player is a stronger claim. About 8 m of clear advantage counts as a strong signal.
- **Numbers:** more players near the ball means a better chance of having it.
- **Phase tags:** Smart Tagging labels phases like progression, creating chances and attacking transition. The attacking team in those phases gets a small nudge.
- **Box tags:** "players in the box" adds a little more weight to the attacking side in scrambles.
- **Turnovers:** if the ball reverses direction and slows down sharply, the team that won it gets a boost.

### 5. Switching possession takes time

The team that has the ball keeps it until the other team's evidence holds for long enough. How long depends on the situation:

- **0.6 s (15 frames)** when the transition tags point at the challenger, it has a big distance lead, the ball is flying toward its goal, or a turnover just happened.
- **2.0 s (50 frames)** when the evidence is close or the ball is unknown.
- **1.6 s (40 frames)** for everything else.

A ball that's flying fast in one direction shouldn't flip possession halfway through. That's the whole idea behind the longer wait.

There's also a soft rule about short spells. Far from a stoppage, a switch needs both the old and new spell to last at least 40 frames. Close to a stoppage, strong evidence can flip possession right up to the whistle, because real possessions do end there.

### 6. When in doubt, say X

If both teams are within 3 m of the ball and neither has a numbers advantage, we output X instead of guessing. The scorer carries an X forward, so the spell stays intact, and a coin flip never gets counted as a wrong answer that breaks a spell. Dead frames are always D. Alive runs shorter than 8 frames that aren't sandwiched by D or the edge of the graded window become X, because they're almost always noise.

### 7. Fallback

If a frame has no state and no usable signal, we copy the competition's own smooth50 baseline label. It's a safe default.

## How we set the numbers

We picked each setting by reasoning about the game. The main ones:

| Setting | Value | Why |
|---|---|---|
| CHALLENGE_N | 40 frames (1.6 s) | About how long a team needs to show it has control |
| MAX_GAP | 50 frames (2 s) | Bridges most occlusions without inventing too much |
| AMBIG_MARGIN | 3.0 m | Two players this close with no numbers edge is a real toss-up |
| ADV_LARGE | 8.0 m | A clear enough lead to speed up the switch |

We also looked at whether mean possession length came out in a sensible range. The competition's smooth50 baseline gives about 12 s, and we wanted to be in that neighbourhood. We used that as a sanity check, not as a target to hit. We ran a sensitivity sweep on CHALLENGE_N (see `tests/sections/sensitivity.md`) to see how the output moves, but we never picked a value by looking at macroF1 or spellF1.

## What we learned

**Closest player is a weak signal on its own.** Taken alone, it gets you roughly 57% on the public window, which is barely better than the baseline. Combining distance with numbers, phase context and turnovers is what made the output steady.

**The scorer rewards caution.** spellF1 likes intact spells, so an honest X beats a wrong guess. macroF1 scores each frame. The rank key adds transition accuracy on top, so the switch moments matter most at the top end. We wrote more about this in `docs/metric_leverage.md`.

**Smart Tagging is underused.** The bundle has 638 tagged instances. Most of us only looked at set pieces and goals. The phase tags turned out to be useful soft hints, and they don't depend on whether the ball is visible.

**Determinism took more care than we expected.** We pinned the line endings (`newline="\n"`, `lineterminator="\n"`), so the file comes out the same on every machine.

The emphasis on traceable data, contextual interpretation and clear reporting also informs our work on AthletIQ, an athlete intelligence platform.

## What we'd try next

1. Use more Smart Tagging signals. `docs/data_audit.md` lists a few we skipped, such as players-in-the-box timing and substitution windows.
2. Handle long blind spots better. Linear fill works, but even a simple Kalman filter would probably do better.
3. Hold out one half for validation. The two halves are independent, so tuning on one and checking on the other would have been a cleaner test. We kept the pipeline blind to the ground truth, so we didn't do it, but looking back it would have caught a few things.
4. Push X harder around transitions. Transition frames are where most of the errors live, and the scorer rewards keeping spells whole.

## Code and reproduction

The code is in `possessed/pipeline.py`, with tests in `tests/`. The match data isn't in the repo, because the competition's terms cover it. To reproduce the file, enrol for MTAH 2027, get the bundle, and point `MTAH_DATA_DIR` at it:

```bash
export MTAH_DATA_DIR=/path/to/match-bundle
python -m possessed.pipeline --out cofi-labs.csv
```

The code's in the repo, the CSV validates, and we pinned the output. Questions welcome.

— Team CoFi Labs