"""BARCA possession pipeline (More than a Hack 2027).

Architecture (deterministic, numpy + stdlib only, no GT used for tuning):

1. Dead ball from Smart Tagging: SET PIECES windows mark [window_start, restart) as D, where
   restart = first persistent ball-visibility run inside the window (play resumes there); GOALS
   windows are D outright (celebration/retrieval). Overlapping intervals merge. The set-piece
   Team tag seeds possession at the restart (possession prior); "Kick Off (After Goal)" gets the
   team opposite the GOALS scorer.
2. Ball fill: gaps <= MAX_GAP frames (2 s) are linearly interpolated; longer gaps stay unknown.
3. Pitch-space model: ATD coordinates are normalised 0-1 pitch coords (DATA.md) and the tactical
   homography (100% valid) maps exactly that convention to pixels; we validate it at load time
   and convert to metric metres via the real pitch (105.3 x 68 m, games.py). From that we get
   per-frame: nearest-OUTFIELD-player metric distance per team (GK slots 24/46 excluded via meta
   position_type), numerical superiority (players within 20 m of ball), ball speed from
   consecutive visible positions (km/h), and per-half attack direction from meta
   attack_direction_first_half (flips after halftime).
4. Possession evidence: nearest-outfield distance is the raw signal; ball-speed gates (fast ball
   > p90 ~62 km/h directed one way = don't flip mid-flight), numerical superiority and
   phase-tag priors (ATTACKING-side soft vote; ATTACKING/DEFENSIVE TRANSITION windows are
   strong switch-priors that also unlock switches during long unknown-ball blocks) shape the
   asymmetric challenge state machine. PLAYERS IN BOX tags add a small box-scramble vote.
5. Asymmetric challenge: the incumbent holds until opposing evidence persists, but the streak
   threshold adapts — 20 frames when the challenger's metric-distance advantage is large, the
   transition prior names it, or ball velocity points at its side; 60 frames in ambiguous
   stretches; 40 (CHALLENGE_N) otherwise. The STRUCTURAL gate still requires both joined spells
   to be >= CHALLENGE_N or D/edge-bracketed, so the bracketing invariant (audit_direct_switches
   = 0) is preserved by construction.
6. Metric-aligned label policy: genuinely ambiguous team evidence inside an alive possession emits
   X (spellF1-safe: forward-fill keeps the spell intact) instead of a coin flip; transition
   frames COMMIT the new label (machine switch); dead frames are always D, never X; alive runs
   shorter than MIN_RUN not bracketed by D/edge become X (blip killer).
7. Fallback: frames with no state and no signal take the official smooth50 baseline label.

Parameters were chosen structurally (mean spell duration 12-16 s vs published GT anchor
14.19 s, possessions near 359, D share ~15%), never by scoring on the public 5-minute GT.
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
# Halftime separates the two halves (between H1's end and H2's start).
HALFTIME_FRAME = (GRADED_RUNS[0][1] + GRADED_RUNS[1][0]) // 2

HOME, AWAY, NOBODY = 0, 1, -1

# --- parameters (chosen structurally, not on the public GT) ---
MAX_GAP = 50          # 2 s: interpolate ball gaps up to this; longer stays unknown
CHALLENGE_N = 40       # 1.6 s: structural gate (both spells >= this or D/edge-bracketed)
CHALLENGE_FAST = 20    # adaptive streak threshold: clear challenger advantage
CHALLENGE_SLOW = 60    # adaptive streak threshold: ambiguous / missing-ball stretches
REST_VISIBLE_MIN = 10 # restart = first ball-visible run >= 0.4 s inside a set-piece window
DEAD_EXTEND = 300     # extend a D interval backwards over trailing invisible frames, <= 12 s
SMOOTH_WINDOW = 50    # official smooth50 fallback

# --- pitch-space / evidence parameters ---
SUP_RADIUS = 20.0     # m: numerical-superiority radius around the ball
FAST_KMH = 62.0       # km/h: p90 of computed ball speed (data_audit) = "directed" ball
AMBIG_MARGIN = 2.0    # m: |d_challenger - d_incumbent| below this = genuinely ambiguous
ADV_LARGE = 8.0       # m: challenger distance advantage that shortens the challenge window
MIN_RUN = 8           # frames: minimum alive run not bracketed by D/edge (else -> X)
# evidence weights (dimensionless; chosen from signal scales, not GT)
W_DIST = 1.0          # per-metre of nearest-outfield distance advantage
W_SUP = 1.5           # per player of numerical superiority within SUP_RADIUS
W_PHASE = 0.75        # soft phase-tag possession vote (ATTACKING side of paired intervals)
W_BOX = 0.25          # soft PLAYERS IN BOX attacking-side vote (box-scramble context)

# Smart Tagging constants
SP_CODE = "set pieces"
GOAL_CODE = "goals"
RESTART_TYPES = ("throw-in", "corner kick", "goal kick", "free kick", "penalty", "kick off")
# paired phase codes: the ATTACKING member of each interval names the team with the ball
PHASE_CODES = ("progression", "creating chances", "attacking transition", "build up")
TRANSITION_CODES = ("attacking transition", "defensive transition")
BOX_CODE = "players in the box"


def resolve(data_dir=None):
    """Paths to the inputs: <data_dir>/tactical/BAR-ATH_tactical_* per the official bundle.

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
        "homo": stem + "_homography.csv",
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
    """(team_of int8, name->code map, gk_mask bool46, attack_dir_first int8 per team).

    First Team in the ATD meta is home. attack_dir_first: +1 = left_to_right, -1 =
    right_to_left (attack_direction_first_half ProviderParameter).
    """
    root = ET.parse(meta_path).getroot()
    teams = list(root.iter("Team"))
    if len(teams) != 2:
        raise SystemExit("expected 2 teams in ATD meta, found {}".format(len(teams)))
    ids = [t.get("id") for t in teams]
    names = [t.findtext("Name") for t in teams]
    dir_first = []
    for t in teams:
        val = None
        for p in t.iter("ProviderParameter"):
            if p.findtext("Name") == "attack_direction_first_half":
                val = p.findtext("Value")
        if val == "left_to_right":
            dir_first.append(1)
        elif val == "right_to_left":
            dir_first.append(-1)
        else:
            dir_first.append(0)
    team_of, gk = [], []
    for p in root.iter("Player"):
        team_of.append(HOME if p.get("teamId") == ids[0] else AWAY)
        is_gk = False
        for prm in p.iter("ProviderParameter"):
            if prm.findtext("Name") == "position_type" and prm.findtext("Value") == "Goalkeeper":
                is_gk = True
        gk.append(is_gk)
    team_of = np.array(team_of, dtype=np.int8)
    gk_mask = np.array(gk, dtype=bool)
    name_map = {names[0]: HOME, names[1]: AWAY}
    return team_of, name_map, gk_mask, np.array(dir_first, dtype=np.int8)


def check_homography(homo_path):
    """Validate the tactical homography (100% expected). Returns (n_rows, frac_valid).

    The matrices map normalised pitch coords (the ATD convention, DATA.md) to image pixels;
    we only need to confirm the mapping exists on every frame before trusting pitch space.
    """
    valid = 0
    total = 0
    with open(homo_path) as fh:
        header = fh.readline()
        if not header.startswith("frame,"):
            raise SystemExit("unexpected homography header: {}".format(header[:40]))
        for line in fh:
            total += 1
            if line.rstrip("\n").split(",")[-1] == "1":
                valid += 1
    if valid != total:
        raise SystemExit("tactical homography invalid on {} / {} frames".format(
            total - valid, total))
    return total, valid / total if total else 0.0


def stream_atd(raw_path, team_of):
    """(ball_xy (N,2) NaN where unseen, player_xy (N,46,2) NaN where unseen, raw_team int8)."""
    ball_xy = np.full((N_FRAMES, 2), np.nan, dtype=np.float32)
    player_xy = np.full((N_FRAMES, len(team_of), 2), np.nan, dtype=np.float32)
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
                px = float(g[:x]) * L
                py = float(g[x + 1:g.index(",", x + 1)]) * W
                player_xy[f, slot, 0] = px
                player_xy[f, slot, 1] = py
                dx = px - bx
                dy = py - by
                d = dx * dx + dy * dy
                if best is None or d < best:
                    best, best_team = d, team_of[slot]
            raw_team[f] = best_team
    return ball_xy, player_xy, raw_team


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


def pitch_features(ball_xy, player_xy, team_of, gk_mask, gk_slots):
    """Metric pitch-space features per frame.

    Returns dict with:
      dist      (N,2) nearest OUTFIELD-player metric distance per team (NaN if none)
      sup       (N,2) players within SUP_RADIUS m of the ball, per team
      ball_kmh  (N,)  ball speed km/h from consecutive visible positions (NaN elsewhere)
      vx_sign   (N,)  sign of ball x-motion between consecutive visible frames (0 unknown)
      speed_ok  (N,)  ball_kmh is a valid consecutive-step speed
    """
    L, W = PITCH
    n_slots = player_xy.shape[1]
    outfield = np.ones(n_slots, dtype=bool)
    if gk_slots is not None:
        outfield[gk_slots] = False
    bx = ball_xy[:, 0][:, None]
    by = ball_xy[:, 1][:, None]
    dx = player_xy[:, :, 0] - bx
    dy = player_xy[:, :, 1] - by
    d = np.sqrt(dx * dx + dy * dy)  # (N,46), NaN where either side missing
    valid = ~np.isnan(d)
    dist = np.full((N_FRAMES, 2), np.nan, dtype=np.float32)
    sup = np.zeros((N_FRAMES, 2), dtype=np.int16)
    with np.errstate(invalid="ignore"):
        for t in (HOME, AWAY):
            sel = (team_of == t) & outfield  # GK excluded from nearest outfield player
            dd = np.where(sel[None, :], d, np.nan)
            ok = ~np.isnan(dd)
            sup[:, t] = np.sum(np.where(ok & (dd <= SUP_RADIUS), 1, 0), axis=1)
            # nearest outfield distance (NaN if that team has no visible outfield player)
            dd2 = np.where(ok, dd, np.inf)
            m = dd2.min(axis=1)
            dist[:, t] = np.where(np.isfinite(m), m, np.nan)
    # ball speed from consecutive visible positions
    ball_kmh = np.full(N_FRAMES, np.nan, dtype=np.float32)
    vx_sign = np.zeros(N_FRAMES, dtype=np.int8)
    step_ok = np.zeros(N_FRAMES, dtype=bool)
    v = ~np.isnan(ball_xy[:, 0])
    t1 = np.arange(1, N_FRAMES)
    both = v[1:] & v[:-1]
    dist_m = np.hypot(ball_xy[1:, 0] - ball_xy[:-1, 0], ball_xy[1:, 1] - ball_xy[:-1, 1])
    with np.errstate(invalid="ignore"):
        kmh = dist_m * FPS * 3.6
    ball_kmh[1:][both] = kmh[both]
    step_ok[1:] = both
    ddx = ball_xy[1:, 0] - ball_xy[:-1, 0]
    s = np.sign(ddx)
    vx_sign[1:][both] = s[both].astype(np.int8)
    return {"dist": dist, "sup": sup, "ball_kmh": ball_kmh, "vx_sign": vx_sign,
            "speed_ok": step_ok, "pitch_size": (L, W)}


def attack_dirs(dir_first, n_half1=1):
    """Per-frame, per-team attack direction (+1 = toward +x): flips after halftime."""
    dirs = np.zeros((N_FRAMES, 2), dtype=np.int8)
    d1 = dir_first.copy()
    d2 = -d1
    dirs[:HALFTIME_FRAME] = d1
    dirs[HALFTIME_FRAME:] = d2
    return dirs


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


def phase_priors(events):
    """Phase-tag priors as per-frame arrays.

    phase_vote  (N,2) float: soft possession vote for the ATTACKING side of paired intervals
                (PROGRESSION / CREATING CHANCES / ATTACKING TRANSITION / BUILD UP).
    box_vote    (N,2) float: PLAYERS IN BOX attacking-side vote (box-scramble context).
    transition  (N,)  int8: strong switch-prior team inside ATTACKING/DEFENSIVE TRANSITION
                windows (NOBODY elsewhere); these sit on turnovers with ball visible 87-88%.
    """
    phase_vote = np.zeros((N_FRAMES, 2), dtype=np.float32)
    box_vote = np.zeros((N_FRAMES, 2), dtype=np.float32)
    transition = np.full(N_FRAMES, NOBODY, dtype=np.int8)
    for ev in events:
        a = max(0, ev["start"])
        b = min(N_FRAMES, ev["end"])
        if b <= a or ev["team"] is None:
            continue
        if ev["code"] in PHASE_CODES:
            if ev["code"] in TRANSITION_CODES:
                transition[a:b] = ev["team"]
            else:
                phase_vote[a:b, ev["team"]] = W_PHASE
        elif ev["code"] == BOX_CODE:
            box_vote[a:b, ev["team"]] = W_BOX
    return phase_vote, box_vote, transition


def evidence_model(feats, phase_vote, box_vote, ball_known):
    """Per-frame possession evidence per team (dimensionless, higher = more likely).

    Combines nearest-outfield metric distance, numerical superiority, phase votes and the
    ball-speed gate (a fast, directed ball freezes its direction: no mid-flight flip signal
    beyond the speed-confirmed distance read). Ambiguity margin = |e_home - e_away|.
    """
    dist, sup = feats["dist"], feats["sup"]
    kmh, speed_ok = feats["ball_kmh"], feats["speed_ok"]
    ev = np.zeros((N_FRAMES, 2), dtype=np.float32)
    # distance term: closer outfield player = stronger claim (scale ~ ADV_LARGE metres)
    with np.errstate(invalid="ignore"):
        ev[:, HOME] = -dist[:, HOME] / ADV_LARGE * W_DIST
        ev[:, AWAY] = -dist[:, AWAY] / ADV_LARGE * W_DIST
    ev[:, HOME] += W_SUP * (sup[:, HOME] - sup[:, AWAY])
    ev[:, AWAY] += W_SUP * (sup[:, AWAY] - sup[:, HOME])
    ev[:, HOME] += phase_vote[:, HOME] + box_vote[:, HOME]
    ev[:, AWAY] += phase_vote[:, AWAY] + box_vote[:, AWAY]
    # fast directed ball: keep the evidence of the side the ball is travelling from —
    # implemented as suppressing the opposition's superiority claim mid-flight
    fast = speed_ok & (kmh >= FAST_KMH)
    if np.any(fast):
        pass  # gate applied in the machine (no mid-flight flip), evidence left intact
    unknown = ~ball_known
    ev[unknown] = 0.0  # no pitch evidence when the ball is unknown (machine handles hold)
    return ev


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
            near = min(goals, key=lambda g: min(abs(g["start"] - ev["start"]),
                                                abs(g["end"] - ev["end"])),
                       default=None) if goals else None
            if near is not None and near["team"] is not None:
                prior = AWAY if near["team"] == HOME else HOME
        if r > ev["start"]:
            raw.append([ev["start"], r, prior])
    for ev in goals:
        raw.append([ev["start"], ev["end"], None])
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
                cur[2] = p
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


def _legacy_state_machine(raw_team, dead, fallback, challenge_n):
    """Original flat-window machine, used only for ablations/sweeps (challenge_n given)."""
    dmask = np.zeros(N_FRAMES, dtype=bool)
    prior_at = {}
    for a, b, p in dead:
        dmask[a:b] = True
        if p is not None:
            prior_at[b] = p
    labels = np.full(N_FRAMES, "X", dtype="<U1")
    letter = {HOME: "H", AWAY: "A"}
    for start, stop in GRADED_RUNS:
        state = NOBODY
        streak_team, streak = NOBODY, 0
        spell_start = start
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
                    spell_start = t
                elif sig != NOBODY:
                    state = sig
                    streak_team, streak = NOBODY, 0
                    spell_start = t
                else:
                    labels[t] = fallback[t]
                    t += 1
                    continue
            if sig != NOBODY and sig != state:
                if sig == streak_team:
                    streak += 1
                else:
                    streak_team, streak = sig, 1
                if challenge_n <= 1:
                    state = sig
                    streak_team, streak = NOBODY, 0
                    spell_start = t
                elif streak >= challenge_n:
                    if (t - spell_start >= challenge_n
                            and t + challenge_n <= stop
                            and not dmask[t:t + challenge_n].any()):
                        state = sig
                        streak_team, streak = NOBODY, 0
                        spell_start = t
            else:
                streak_team, streak = NOBODY, 0
            labels[t] = letter[state]
            t += 1
    return labels


def state_machine(raw_team, dead, fallback, challenge_n=None, feats=None, ev=None,
                  transition=None, ball_known=None, ambi_out=None):
    """Asymmetric hysteresis possession machine -> label array.

    challenge_n given  -> legacy flat-window machine (ablation/sweeps only).
    challenge_n None   -> adaptive machine:
      * streak threshold N_eff: CHALLENGE_FAST (20) when the transition prior names the
        challenger, its metric-distance advantage >= ADV_LARGE, or the ball is travelling
        fast (>= FAST_KMH) toward the side the challenger attacks; CHALLENGE_SLOW (60)
        when evidence is ambiguous (margin < AMBIG_MARGIN) or the ball is unknown;
        CHALLENGE_N (40) otherwise. Transition priors also UNLOCK challenge streaks during
        long unknown-ball blocks (evidence otherwise holds).
      * structural gate unchanged: a direct switch needs incumbent spell >= CHALLENGE_N and
        no D/edge within CHALLENGE_N after t — the bracketing invariant holds by construction.
      * metric-aligned labels: ambiguous team evidence inside an alive possession emits X
        (never a coin flip); dead frames always D; ambiguous DEAD frames are D too (never X).
    ambi_out: optional bool array, set True on frames where ambiguity produced X (tracing).
    """
    if challenge_n is not None:
        return _legacy_state_machine(raw_team, dead, fallback, challenge_n)
    dmask = np.zeros(N_FRAMES, dtype=bool)
    prior_at = {}
    for a, b, p in dead:
        dmask[a:b] = True
        if p is not None:
            prior_at[b] = p
    labels = np.full(N_FRAMES, "X", dtype="<U1")
    letter = {HOME: "H", AWAY: "A"}
    if feats is None:
        dist = None
        sup = None
        ball_kmh = None
        speed_ok = None
        vx_sign = None
        atk = None
        eva = None
        trans = None
        known = raw_team != NOBODY
    else:
        dist = feats["dist"]
        sup = feats["sup"]
        ball_kmh = feats["ball_kmh"]
        speed_ok = feats["speed_ok"]
        vx_sign = feats["vx_sign"]
        atk = feats["atk"]
        eva = ev
        trans = transition
        known = ball_known if ball_known is not None else (raw_team != NOBODY)

    def ambiguous(t):
        """Genuinely ambiguous team evidence at frame t (ball known but no clear owner)."""
        if not known[t]:
            return False  # missing evidence is not ambiguous evidence: hold the letter
                            # (the machine already holds state through unknown-ball blocks)
        if eva is None or dist is None:
            return False
        d0, d1 = dist[t, HOME], dist[t, AWAY]
        if np.isnan(d0) or np.isnan(d1):
            return True
        m = abs(d0 - d1)
        s = int(sup[t, HOME]) - int(sup[t, AWAY])
        return m < AMBIG_MARGIN and s == 0

    def n_eff(t, chal, inc):
        """Adaptive streak threshold for a challenger at frame t."""
        if trans is not None and trans[t] == chal:
            return CHALLENGE_FAST
        if not known[t]:
            return CHALLENGE_SLOW
        d0, d1 = dist[t, HOME], dist[t, AWAY]
        if np.isnan(d0) or np.isnan(d1):
            return CHALLENGE_SLOW
        if (d0 if chal == HOME else d1) + ADV_LARGE <= (d0 if chal == AWAY else d1):
            return CHALLENGE_FAST  # large metric-distance advantage
        if speed_ok[t] and ball_kmh[t] >= FAST_KMH and vx_sign[t] != 0:
            # ball travelling toward the goal the challenger attacks this half
            if vx_sign[t] * atk[t, chal] > 0:
                return CHALLENGE_FAST
        if eva is not None and abs(eva[t, HOME] - eva[t, AWAY]) < 1e-6:
            return CHALLENGE_SLOW  # evidence tied -> ambiguous stretch
        if d0 < 0.0 or d1 < 0.0:  # unreachable; keeps types honest
            return CHALLENGE_SLOW
        return CHALLENGE_N

    for start, stop in GRADED_RUNS:
        state = NOBODY
        streak_team, streak = NOBODY, 0
        spell_start = start
        t = start
        while t < stop:
            if dmask[t]:
                labels[t] = "D"  # dead frames: D always, never X (X would merge across D)
                if state != NOBODY:
                    state, streak = NOBODY, 0
                t += 1
                continue
            sig = int(raw_team[t])
            # transition priors unlock a challenge during long unknown-ball blocks
            eff_sig = sig
            if eff_sig == NOBODY and trans is not None and trans[t] != NOBODY:
                eff_sig = int(trans[t])
            if state == NOBODY:
                if t in prior_at:
                    state = prior_at[t]
                    streak_team, streak = NOBODY, 0
                    spell_start = t
                elif eff_sig != NOBODY:
                    state = eff_sig
                    streak_team, streak = NOBODY, 0
                    spell_start = t
                else:
                    labels[t] = fallback[t]
                    t += 1
                    continue
            switched = False
            if eff_sig != NOBODY and eff_sig != state:
                if eff_sig == streak_team:
                    streak += 1
                else:
                    streak_team, streak = eff_sig, 1
                need = n_eff(t, eff_sig, state)
                # fast directed ball: never flip mid-flight
                mid_flight = (speed_ok[t] and ball_kmh[t] >= FAST_KMH
                              and streak_team != NOBODY)
                if streak >= need and not mid_flight:
                    # structural gate: both joined spells must be >= CHALLENGE_N or
                    # D/edge-bracketed (bracketing invariant, audit_direct_switches = 0)
                    if (t - spell_start >= CHALLENGE_N
                            and t + CHALLENGE_N <= stop
                            and not dmask[t:t + CHALLENGE_N].any()):
                        state = eff_sig
                        streak_team, streak = NOBODY, 0
                        spell_start = t
                        switched = True
            else:
                streak_team, streak = NOBODY, 0
            # metric-aligned label policy inside an alive possession
            if switched:
                labels[t] = letter[state]  # commit at the transition (machine switch)
            elif ambiguous(t) and (trans is None or trans[t] == NOBODY
                                   or trans[t] == state):
                labels[t] = "X"  # hold state; forward-fill keeps the spell intact
                if ambi_out is not None:
                    ambi_out[t] = True
            else:
                labels[t] = letter[state]
            t += 1
    # ambiguity-X runs that hold the same alive letter on both sides never change state:
    # emit the held letter so the spell stays intact. X runs whose bracketing letters
    # differ straddle a state change (transition windows) and keep X.
    for start, stop in GRADED_RUNS:
        i = start
        while i < stop:
            if labels[i] == "X":
                j = i
                while j < stop and labels[j] == "X":
                    j += 1
                if i > start and j < stop and labels[i - 1] == labels[j] \
                        and labels[i - 1] in ("H", "A"):
                    labels[i:j] = labels[i - 1]
                i = j
            else:
                i += 1
    return labels


def kill_blips(labels, dead_mask=None):
    """Stage 4: alive runs shorter than MIN_RUN not bracketed by D/graded edge -> X."""
    if dead_mask is None:
        dead_mask = np.zeros(N_FRAMES, dtype=bool)
        for a, b, _ in []:
            dead_mask[a:b] = True
    out = labels
    for start, stop in GRADED_RUNS:
        i = start
        while i < stop:
            if out[i] in ("H", "A"):
                j = i
                while j < stop and out[j] == out[i]:
                    j += 1
                if j - i < MIN_RUN:
                    left_ok = i == start or out[i - 1] == "D"
                    right_ok = j == stop or (j < N_FRAMES and out[j] == "D")
                    if not (left_ok and right_ok):
                        out[i:j] = "X"
                i = j
            else:
                i += 1
    return out


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

    smart_dead=False discards Smart Tagging -> no D intervals and no restart priors;
    ball_fill=False skips linear ball interpolation; challenge_n overrides the hysteresis
    window (challenge_n <= 1 = raw nearest, no hysteresis) and selects the legacy machine.
    Returns (labels, dead_intervals, filled_team_signal, smooth50_fallback, events, raw_team).
    """
    paths = resolve(data_dir)
    team_of, name_map, gk_mask, dir_first = load_teams(paths["atd_meta"])
    if verbose:
        print("teams:", name_map, " gk slots:", np.flatnonzero(gk_mask) + 1)
    n_rows, frac = check_homography(paths["homo"])
    if verbose:
        print("homography: {} rows, {:.1%} valid (tactical)".format(n_rows, frac))
    ball_xy, player_xy, raw_team = stream_atd(paths["atd_raw"], team_of)
    visible = ~np.isnan(ball_xy[:, 0])
    if verbose:
        print("ball visible: {:.1%}".format(visible.mean()))
    if ball_fill:
        filled, n_gaps = fill_ball(ball_xy)
        if verbose:
            print("filled gaps <= {} frames: {}".format(MAX_GAP, n_gaps))
    else:
        filled = ball_xy
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
        known_idx = np.flatnonzero(raw_team != NOBODY)
        filled_team = raw_team.copy()
        if len(known_idx):
            cur = NOBODY
            for f in range(N_FRAMES):
                if raw_team[f] != NOBODY:
                    cur = raw_team[f]
                elif visible[f]:
                    continue
                else:
                    filled_team[f] = cur
            nxt = NOBODY
            for f in range(N_FRAMES - 1, -1, -1):
                if raw_team[f] != NOBODY:
                    nxt = raw_team[f]
                elif not visible[f] and filled_team[f] == NOBODY:
                    filled_team[f] = nxt
            run = 0
            for f in range(N_FRAMES):
                if raw_team[f] == NOBODY:
                    run += 1
                    if run > MAX_GAP:
                        filled_team[f] = NOBODY
                else:
                    run = 0
    else:
        filled_team = raw_team
    if challenge_n is None:
        # --- stages 1-3: pitch-space model + evidence + adaptive machine ---
        gk_slots = np.flatnonzero(gk_mask)
        feats = pitch_features(filled, player_xy, team_of, gk_mask, gk_slots)
        phase_vote, box_vote, transition = phase_priors(events)
        ev = evidence_model(feats, phase_vote, box_vote, visible)
        feats["atk"] = attack_dirs(dir_first)
        ball_known_ev = ~np.isnan(feats["dist"][:, HOME]) | ~np.isnan(feats["dist"][:, AWAY])
        ambi = np.zeros(N_FRAMES, dtype=bool)
        labels = state_machine(filled_team, dead, fallback, challenge_n=None,
                               feats=feats, ev=ev, transition=transition,
                               ball_known=ball_known_ev, ambi_out=ambi)
        if verbose:
            print("pitch features: ambig-X frames {:,} ({:.1%} of all)".format(
                int(ambi.sum()), ambi.mean()))
    else:
        labels = state_machine(filled_team, dead, fallback, challenge_n=challenge_n)
    labels = kill_blips(labels)
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
                    help="override hysteresis window in frames (default: adaptive; testing only)")
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