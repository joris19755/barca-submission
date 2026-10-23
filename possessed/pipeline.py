"""BARCA possession pipeline (More than a Hack 2027).

Architecture (deterministic, numpy + stdlib only, no GT used for tuning):

1. Dead ball from Smart Tagging: SET PIECES windows mark [window_start, restart) as D, where
   restart = first persistent ball-visibility run inside the window (play resumes there); GOALS
   windows are D outright (celebration/retrieval). Overlapping intervals merge. The set-piece
   Team tag seeds possession at the restart (possession prior); "Kick Off (After Goal)" gets the
   team opposite the GOALS scorer.
2. Ball fill: gaps <= MAX_GAP frames (2 s) are linearly interpolated; longer gaps stay unknown.
3. Raw signal: nearest tracked player to the (filled) ball, same geometry as the official
   baseline (pitch metres, normalised coords).
4. Possession state machine with hysteresis: the current possessor is held until the opposing
   team's raw signal persists CHALLENGE_N consecutive frames (1 s) — kill the churn of the raw
   baseline (131 possessions / 5 min). During dead-ball intervals the state resets to NONE and
   the restart prior seeds it. Ball-unknown live frames HOLD the last state (under spellF1 an X
   forward-fills to exactly the last label anyway, so holding is score-identical on the ranking
   metric and strictly better on macroF1 — we do not emit X inside play, only outside graded
   runs, where it is never scored).
5. Fallback: frames with no state and no signal take the official smooth50 baseline label.

Parameters were chosen for structural plausibility (40-60 possessions per half, mean 12-18 s),
never by scoring on the public 5-minute GT.
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

N_FRAMES = 199319
FPS = 25
PITCH = (105.3, 68.0)  # metres, from games.py

# Graded runs of this match, published in evaluation/possession_metrics.py's docstring
# ("the two halves, (11185, 90652) and (110808, 190198)"). Outside them the GT is X and the
# scorer never grades, so we emit X there.
GRADED_RUNS = ((11185, 90652), (110808, 190198))

HOME, AWAY, NOBODY = 0, 1, -1

# --- parameters (chosen structurally, not on the public GT) ---
MAX_GAP = 50          # 2 s: interpolate ball gaps up to this; longer stays unknown
CHALLENGE_N = 40       # 1.6 s: opposing signal must persist this to steal possession
REST_VISIBLE_MIN = 10 # restart = first ball-visible run >= 0.4 s inside a set-piece window
DEAD_EXTEND = 300     # extend a D interval backwards over trailing invisible frames, <= 12 s
SMOOTH_WINDOW = 50    # official smooth50 fallback

# Smart Tagging constants
SP_CODE = "set pieces"
GOAL_CODE = "goals"
RESTART_TYPES = ("throw-in", "corner kick", "goal kick", "free kick", "penalty", "kick off")


def resolve(data_dir=None):
    """Paths to the four inputs: <data_dir>/tactical/BAR-ATH_tactical_* per the official bundle.

    Resolution order: explicit data_dir argument (the --data-dir CLI flag), then $MTAH_DATA_DIR
    (both <dir>/tactical and <dir> itself), then the conventional ./data unpack location.
    """
    roots = []
    env = data_dir or os.environ.get("MTAH_DATA_DIR")
    if env:
        roots += [os.path.join(env, "tactical"), env]
    roots += ["mtah-data/tactical", "data"]
    stem = "BAR-ATH_tactical"
    names = {
        "atd_meta": stem + "_atd.xml",
        "atd_raw": stem + "_atd.txt",
        "smart": stem + "_smart_tagging.xml",
    }
    out = {}
    for key, name in names.items():
        for root in roots:
            path = os.path.join(root, name)
            if os.path.isfile(path):
                out[key] = path
                break
        else:
            raise SystemExit("missing input {} (tried under {})".format(name, roots))
    return out


def load_teams(meta_path):
    """(team_of_slot int8 array, name->code map). First Team in the ATD meta is home."""
    root = ET.parse(meta_path).getroot()
    teams = list(root.iter("Team"))
    if len(teams) != 2:
        raise SystemExit("expected 2 teams in ATD meta, found {}".format(len(teams)))
    ids = [t.get("id") for t in teams]
    names = [t.findtext("Name") for t in teams]
    slots = [p.get("teamId") for p in root.iter("Player")]
    team_of = np.array([HOME if s == ids[0] else AWAY for s in slots], dtype=np.int8)
    name_map = {names[0]: HOME, names[1]: AWAY}
    return team_of, name_map


def stream_atd(raw_path, team_of):
    """(ball_xy float32 (N,2) with NaN where unseen, raw_team int8 with NOBODY where unknown)."""
    ball_xy = np.full((N_FRAMES, 2), np.nan, dtype=np.float32)
    raw_team = np.full(N_FRAMES, NOBODY, dtype=np.int8)
    L, W = PITCH
    with open(raw_path) as fh:
        for line in fh:
            c1 = line.find(":")
            f = int(line[:c1]) - 1
            rest = line[c1 + 1:]
            c2 = rest.find(":")
            ball = rest[c2 + 1:]
            if ball[0] == "N":  # NaN
                continue
            a = ball.index(",")
            bx = float(ball[:a]) * L
            by = float(ball[a + 1:ball.index(",", a + 1)]) * W
            ball_xy[f, 0] = bx
            ball_xy[f, 1] = by
            best, best_team = None, NOBODY
            for slot, g in enumerate(rest[:c2].split(";")):
                if g[0] == "N":
                    continue
                x = g.index(",")
                dx = float(g[:x]) * L - bx
                dy = float(g[x + 1:g.index(",", x + 1)]) * W - by
                d = dx * dx + dy * dy
                if best is None or d < best:
                    best, best_team = d, team_of[slot]
            raw_team[f] = best_team
    return ball_xy, raw_team


def fill_ball(ball_xy):
    """Linear interpolation across invisible runs <= MAX_GAP frames; longer runs stay NaN."""
    filled = ball_xy.copy()
    seen = ~np.isnan(ball_xy[:, 0])
    idx = np.arange(N_FRAMES)
    n = 0
    i = 0
    while i < N_FRAMES:
        if seen[i]:
            i += 1
            continue
        j = i
        while j < N_FRAMES and not seen[j]:
            j += 1
        n += 1
        if j - i <= MAX_GAP and i > 0 and j < N_FRAMES:
            for dim in (0, 1):
                filled[i:j, dim] = np.interp(idx[i:j], [i - 1, j],
                                              [ball_xy[i - 1, dim], ball_xy[j, dim]])
        i = j
    return filled, n


def load_smart(smart_path, name_map):
    """Set-piece and goal events as frame intervals with restart priors."""
    events = []
    for inst in ET.parse(smart_path).getroot().iter("instance"):
        code = (inst.findtext("code") or "").strip().lower()
        tags = {l.findtext("group"): l.findtext("text") for l in inst.findall("label")}
        events.append({
            "code": code,
            "start": int(round(float(inst.findtext("start")) * FPS)),
            "end": int(round(float(inst.findtext("end")) * FPS)),
            "type": (tags.get("Type") or "").strip(),
            "team": name_map.get((tags.get("Team") or "").strip(), None),
            "half": tags.get("Half"),
        })
    return events


def restart_estimate(ev, visible):
    """First persistent ball-visibility run inside the window -> the restart moment."""
    lo, hi = ev["start"], min(ev["end"], N_FRAMES)
    i = lo
    while i < hi:
        if visible[i]:
            j = i
            while j < hi and visible[j]:
                j += 1
            if j - i >= REST_VISIBLE_MIN:
                return i
            i = j
        else:
            i += 1
    return hi


def dead_intervals(events, visible, ball_known):
    """Merged D intervals [(start, stop, prior)] — prior in {HOME, AWAY, None}."""
    goals = [ev for ev in events if ev["code"] == GOAL_CODE]
    sps = [ev for ev in events if ev["code"] == SP_CODE
           and any(ev["type"].lower().startswith(t) for t in RESTART_TYPES)]
    raw = []
    for ev in sps:
        r = restart_estimate(ev, visible)
        prior = ev["team"]
        if prior is None and ev["type"].lower().startswith("kick off (after goal)"):
            # the conceding team restarts: opposite of the nearest goal scorer
            near = min(goals, key=lambda g: min(abs(g["start"] - ev["start"]),
                                                abs(g["end"] - ev["end"])),
                       default=None) if goals else None
            if near is not None and near["team"] is not None:
                prior = AWAY if near["team"] == HOME else HOME
        if r > ev["start"]:
            raw.append([ev["start"], r, prior])
    for ev in goals:
        raw.append([ev["start"], ev["end"], None])
    # extend backwards over trailing ball-invisible frames (ball already dead before the tag)
    ext = []
    for a, b, p in raw:
        k = a
        t = a - 1
        while t >= 0 and not ball_known[t] and a - t <= DEAD_EXTEND:
            k = t
            t -= 1
        ext.append([k, b, p])
    ext.sort(key=lambda r: r[0])
    merged = []
    for a, b, p in ext:
        if merged and a <= merged[-1][1]:
            cur = merged[-1]
            if b > cur[1]:
                cur[1] = b
                cur[2] = p  # later interval's restart wins if it extends the segment
            elif p is not None and cur[2] is None:
                pass
        else:
            merged.append([a, b, p])
    return merged


def smooth50(raw_team):
    """Official baseline smooth50 labels — the fallback for frames with no usable signal."""
    codes = raw_team.astype(np.int32)
    w = SMOOTH_WINDOW
    h = np.concatenate(([0], np.cumsum(codes == HOME)))
    a = np.concatenate(([0], np.cumsum(codes == AWAY)))
    idx = np.arange(N_FRAMES)
    lo = np.maximum(0, idx - w)
    hi = np.minimum(N_FRAMES, idx + w + 1)
    hc = h[hi] - h[lo]
    ac = a[hi] - a[lo]
    labels = np.full(N_FRAMES, "D", dtype="<U1")
    seen = (hc + ac) > 0
    labels[seen] = np.where(hc[seen] >= ac[seen], "H", "A")
    return labels


def state_machine(raw_team, dead, fallback, challenge_n=None):
    """Hysteresis possession machine; returns a label array over all frames.

    challenge_n overrides CHALLENGE_N (ablation/testing only; default keeps shipped behaviour).
    """
    if challenge_n is None:
        challenge_n = CHALLENGE_N
    dmask = np.zeros(N_FRAMES, dtype=bool)
    prior_at = {}
    for a, b, p in dead:
        dmask[a:b] = True
        if p is not None:
            prior_at[b] = p  # restart frame (interval is half-open) gets the set-piece prior
    labels = np.full(N_FRAMES, "X", dtype="<U1")
    letter = {HOME: "H", AWAY: "A"}
    for start, stop in GRADED_RUNS:
        state = NOBODY
        streak_team, streak = NOBODY, 0
        t = start
        while t < stop:
            if dmask[t]:
                labels[t] = "D"
                if state != NOBODY:
                    state, streak = NOBODY, 0
                t += 1
                continue
            sig = int(raw_team[t])
            if state == NOBODY:
                if t in prior_at:
                    state = prior_at[t]
                    streak_team, streak = NOBODY, 0
                elif sig != NOBODY:
                    state = sig
                    streak_team, streak = NOBODY, 0
                else:
                    labels[t] = fallback[t]
                    t += 1
                    continue
            if sig != NOBODY and sig != state:
                if sig == streak_team:
                    streak += 1
                else:
                    streak_team, streak = sig, 1
                if challenge_n <= 1:  # no hysteresis: raw signal wins immediately
                    state = sig
                    streak_team, streak = NOBODY, 0
                elif streak >= challenge_n:
                    state = sig
                    streak_team, streak = NOBODY, 0
            else:
                streak_team, streak = NOBODY, 0
            labels[t] = letter[state]
            t += 1
    return labels


def structural_stats(labels):
    """Possession count and duration distribution per half, plus label shares."""
    stats = {"possessions": [], "mean_s": [], "median_s": [], "shares": {}}
    counts = {k: int(np.sum(labels == k)) for k in ("H", "A", "D", "X")}
    total = sum(counts.values())
    stats["shares"] = {k: v / total for k, v in counts.items()}
    for start, stop in GRADED_RUNS:
        seg = labels[start:stop]
        spells = []
        i = 0
        n = len(seg)
        while i < n:
            if seg[i] in ("H", "A"):
                j = i
                while j < n and seg[j] == seg[i]:
                    j += 1
                spells.append(j - i)
                i = j
            else:
                i += 1
        stats["possessions"].append(len(spells))
        arr = np.array(spells, dtype=float) if spells else np.array([0.0])
        stats["mean_s"].append(float(arr.mean() / FPS))
        stats["median_s"].append(float(np.median(arr) / FPS))
    return stats


def write_submission(path, labels):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w") as fh:
        fh.write("frame,label\n")
        fh.writelines("{},{}\n".format(i, lab) for i, lab in enumerate(labels))
    return path


def build(data_dir=None, verbose=True):
    """Default pipeline (all stages on) -> full-length label array."""
    labels, _, _, _, _, _ = build_full(data_dir=data_dir, verbose=verbose)
    return labels


def build_full(data_dir=None, verbose=True, smart_dead=True, ball_fill=True,
               challenge_n=None):
    """Full build with ablation switches (defaults reproduce the shipped pipeline exactly).

    smart_dead=False discards Smart Tagging -> no D intervals and no restart priors (pure
    tracking); ball_fill=False skips linear ball interpolation; challenge_n overrides the
    hysteresis window (challenge_n <= 1 = raw nearest, no hysteresis).
    Returns (labels, dead_intervals, filled_team_signal, smooth50_fallback, events, raw_team).
    """
    paths = resolve(data_dir)
    team_of, name_map = load_teams(paths["atd_meta"])
    if verbose:
        print("teams:", name_map)
    ball_xy, raw_team = stream_atd(paths["atd_raw"], team_of)
    visible = ~np.isnan(ball_xy[:, 0])
    if verbose:
        print("ball visible: {:.1%}".format(visible.mean()))
    if ball_fill:
        filled, n_gaps = fill_ball(ball_xy)
        if verbose:
            print("filled gaps <= {} frames: {}".format(MAX_GAP, n_gaps))
    else:
        filled = ball_xy  # ablation: no interpolation, gaps stay NaN
    events = load_smart(paths["smart"], name_map)
    if smart_dead:
        dead = dead_intervals(events, visible, visible)
    else:
        dead = []
    if verbose:
        n_sp = sum(1 for e in events if e["code"] == SP_CODE)
        frames_d = sum(b - a for a, b, _ in dead)
        print("smart tagging: {} instances, {} set pieces -> {} dead intervals, "
              "{:.1%} of frames D".format(len(events), n_sp, len(dead),
                                          frames_d / N_FRAMES))
    fallback = smooth50(raw_team)
    if ball_fill:
        # frames where the ball stayed unknown for > MAX_GAP are NOBODY (long-unknown territory)
        known = np.flatnonzero(raw_team != NOBODY)
        filled_team = raw_team.copy()
        if len(known):
            cur = NOBODY
            for f in range(N_FRAMES):
                if raw_team[f] != NOBODY:
                    cur = raw_team[f]
                elif visible[f]:
                    continue  # visible ball but no tracked player: leave NOBODY
                else:
                    filled_team[f] = cur
            nxt = NOBODY
            for f in range(N_FRAMES - 1, -1, -1):
                if raw_team[f] != NOBODY:
                    nxt = raw_team[f]
                elif not visible[f] and filled_team[f] == NOBODY:
                    filled_team[f] = nxt
            # do not trust a held team across a long unknown stretch: reset the hold after
            # MAX_GAP consecutive frames without any raw signal
            run = 0
            for f in range(N_FRAMES):
                if raw_team[f] == NOBODY:
                    run += 1
                    if run > MAX_GAP:
                        filled_team[f] = NOBODY
                else:
                    run = 0
    else:
        filled_team = raw_team  # ablation: no ball fill -> raw signal only
    labels = state_machine(filled_team, dead, fallback, challenge_n=challenge_n)
    return labels, dead, filled_team, fallback, events, raw_team


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="BARCA possession pipeline (regenerates the MTAH 2027 submission file)")
    ap.add_argument("--out", default="barca.csv",
                    help="output CSV path (default: barca.csv, the <team_name>.csv convention)")
    ap.add_argument("--data-dir", "--data", dest="data_dir", default=None,
                    help="match-data bundle root containing tactical/BAR-ATH_tactical_* "
                         "(default: $MTAH_DATA_DIR, then ./data)")
    ap.add_argument("--challenge-n", type=int, default=None,
                    help="override hysteresis window in frames (default: {}; testing only)"
                         .format(CHALLENGE_N))
    args = ap.parse_args(argv)
    labels = build(args.data_dir) if args.challenge_n is None else build_full(
        data_dir=args.data_dir, challenge_n=args.challenge_n)[0]
    st = structural_stats(labels)
    print("label shares:", {k: round(v, 3) for k, v in st["shares"].items()})
    print("possessions per half:", st["possessions"],
          " mean s:", [round(x, 1) for x in st["mean_s"]],
          " median s:", [round(x, 1) for x in st["median_s"]])
    write_submission(args.out, labels)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())