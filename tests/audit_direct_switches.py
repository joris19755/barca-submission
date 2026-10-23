"""Audit: enumerate every sub-CHALLENGE_N alive spell whose entry switch is direct
(no D / graded-run edge before it) and group them by root-cause signature.

Re-runs the pipeline's state machine with tracing (byte-identical labels asserted against
the pipeline's own output), classifies each violating spell's entry cause and context, and
writes tests/_results/audit_direct_switches.json. Read-only analysis; changes no pipeline code.
"""
import json
import os
import sys

import numpy as np

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.dirname(TESTS_DIR))

import helpers as H  # noqa: E402
from possessed import pipeline as pl  # noqa: E402

CHALLENGE_N = pl.CHALLENGE_N


def traced_state_machine(raw_team, dead, fallback):
    """Exact copy of pipeline.state_machine (default challenge_n) plus a per-frame cause log.

    cause[t] records why labels[t] took the value it did when the STATE changed:
      streak40        - opposing signal persisted CHALLENGE_N (the sanctioned switch)
      seed_prior      - restart prior adopted at a dead-interval end (post-D, bracketed)
      adopt_signal    - state NOBODY adopted the first known signal (post-D/edge or fallback)
      fallback_hold   - state NOBODY emitted the smooth50 fallback letter (alive) -> INCUMBENT
      dead            - D frame (state reset to NOBODY)
      same/none       - no state change
    """
    dmask = np.zeros(pl.N_FRAMES, dtype=bool)
    prior_at = {}
    for a, b, p in dead:
        dmask[a:b] = True
        if p is not None:
            prior_at[b] = p
    labels = np.full(pl.N_FRAMES, "X", dtype="<U1")
    cause = np.full(pl.N_FRAMES, "", dtype=object)
    letter = {pl.HOME: "H", pl.AWAY: "A"}
    for start, stop in pl.GRADED_RUNS:
        state = pl.NOBODY
        streak_team, streak = pl.NOBODY, 0
        spell_start = start
        t = start
        while t < stop:
            if dmask[t]:
                labels[t] = "D"
                cause[t] = "dead"
                if state != pl.NOBODY:
                    state, streak = pl.NOBODY, 0
                t += 1
                continue
            sig = int(raw_team[t])
            if state == pl.NOBODY:
                if t in prior_at:
                    state = prior_at[t]
                    streak_team, streak = pl.NOBODY, 0
                    spell_start = t
                    cause[t] = "seed_prior"
                elif sig != pl.NOBODY:
                    state = sig
                    streak_team, streak = pl.NOBODY, 0
                    spell_start = t
                    cause[t] = "adopt_signal"
                else:
                    labels[t] = fallback[t]
                    cause[t] = ("fallback_hold" if fallback[t] in ("H", "A")
                                else "fallback_d")
                    t += 1
                    continue
            if sig != pl.NOBODY and sig != state:
                if sig == streak_team:
                    streak += 1
                else:
                    streak_team, streak = sig, 1
                if streak >= CHALLENGE_N:
                    # same dual-bracket gate as pipeline.state_machine
                    if (t - spell_start >= CHALLENGE_N
                            and t + CHALLENGE_N <= stop
                            and not dmask[t:t + CHALLENGE_N].any()):
                        state = sig
                        streak_team, streak = pl.NOBODY, 0
                        spell_start = t
                        cause[t] = "streak40"
            else:
                streak_team, streak = pl.NOBODY, 0
                if not cause[t]:
                    cause[t] = "hold"
            labels[t] = letter[state]
            t += 1
    return labels, cause


def main():
    labels = H.read_labels(H.SUBMISSION)
    built, dead, filled, fallback, events, raw = pl.build_full(verbose=False)
    # ball visibility (raw track) for context
    paths = pl.resolve(None)
    team_of, _ = pl.load_teams(paths["atd_meta"])
    ball_xy, raw_team = pl.stream_atd(paths["atd_raw"], team_of)
    visible = ~np.isnan(ball_xy[:, 0])

    traced, cause = traced_state_machine(filled, dead, fallback)
    assert "".join(traced) == "".join(labels), "trace diverges from shipped labels"

    sp_windows = [(e["start"], e["end"]) for e in events if e["code"] == pl.SP_CODE]
    goal_windows = [(e["start"], e["end"]) for e in events if e["code"] == pl.GOAL_CODE]
    dead_bounds = sorted({x for a, b, _ in dead for x in (a, b)})

    def nearest_dead(t):
        return min((abs(t - x) for x in dead_bounds), default=None)

    def in_windows(t, wins):
        return any(a <= t < b for a, b in wins)

    violations = []
    for start, stop in H.GRADED_RUNS:
        for st, en, team in H.spells_in(labels, start, stop):
            if en - st >= CHALLENGE_N:
                continue
            left = st == start
            right = en == stop
            if (labels[st - 1] == "D") if st > start else left:
                left_ok = True
            else:
                left_ok = False
            if not right and labels[en] != "D":
                right_ok = False
            elif right or labels[en] == "D":
                right_ok = True
            if (left_ok or st == start) and right_ok:
                continue  # bracketed: passes the invariant test
            entry_direct = not left_ok       # alive predecessor: no D/edge before the spell
            exit_direct = not right_ok       # alive successor: no D/edge after the spell
            if not (entry_direct or exit_direct):
                continue  # bracketed both sides: passes the invariant test
            entry_cause = cause[st]
            exit_type = ("run_edge" if en == stop else
                         ("D" if labels[en] == "D" else "direct"))
            sig_f = filled[st]
            sig_r = raw[st]
            violations.append({
                "st": int(st), "en": int(en), "len": int(en - st),
                "half": 1 if st < H.GRADED_RUNS[0][1] else 2,
                "team": team, "prev": str(labels[st - 1]),
                "entry_direct": entry_direct, "exit_direct": exit_direct,
                "entry_cause": str(entry_cause),
                "exit_type": exit_type,
                "exit_cause": str(cause[en]) if en < pl.N_FRAMES else "eof",
                "sig_at_entry": (str(sig_f) if sig_f != pl.NOBODY else "unknown"),
                "raw_at_entry": (str(sig_r) if sig_r != pl.NOBODY else "unknown"),
                "ball_visible_entry": bool(visible[st]),
                "ball_known_3_before": bool(all(visible[max(0, st - k)] for k in (1, 2, 3))),
                "in_set_piece_window": bool(in_windows(st, sp_windows)),
                "in_goal_window": bool(in_windows(st, goal_windows)),
                "nearest_dead_boundary_frames": int(nearest_dead(st)),
            })

    # signature grouping
    sig_groups = {}
    for v in violations:
        sig = v["entry_cause"]
        sig_groups.setdefault(sig, []).append(v)

    lens = [v["len"] for v in violations]
    length_hist = {}
    for L in lens:
        length_hist[L] = length_hist.get(L, 0) + 1
    halves = {h: sum(1 for v in violations if v["half"] == h) for h in (1, 2)}
    ctx = {
        "ball_unknown_at_entry": sum(1 for v in violations if v["sig_at_entry"] == "unknown"),
        "ball_known_at_entry": sum(1 for v in violations if v["sig_at_entry"] != "unknown"),
        "ball_invisible_3_before": sum(1 for v in violations if not v["ball_known_3_before"]),
        "in_set_piece_window": sum(1 for v in violations if v["in_set_piece_window"]),
        "in_goal_window": sum(1 for v in violations if v["in_goal_window"]),
        "exit_is_D": sum(1 for v in violations if v["exit_type"] == "D"),
        "exit_is_run_edge": sum(1 for v in violations if v["exit_type"] == "run_edge"),
        "exit_is_direct": sum(1 for v in violations if v["exit_type"] == "direct"),
        "entry_after_seed_prior": sum(1 for v in violations
                                      if v["entry_cause"] == "seed_prior"),
    }
    known = [v for v in violations if v["st"] == 65253]
    report = {
        "total_violations": len(violations),
        "length_min": min(lens) if lens else None,
        "length_max": max(lens) if lens else None,
        "length_mean": round(sum(lens) / len(lens), 2) if lens else None,
        "length_hist": {str(k): length_hist[k] for k in sorted(length_hist)},
        "half_dist": halves,
        "context_counts": ctx,
        "signature_groups": {k: {"count": len(g),
                                 "exit_D": sum(1 for x in g if x["exit_type"] == "D"),
                                 "exit_edge": sum(1 for x in g
                                                  if x["exit_type"] == "run_edge"),
                                 "exit_direct": sum(1 for x in g
                                                    if x["exit_type"] == "direct"),
                                 "ball_known_at_entry": sum(
                                     1 for x in g if x["sig_at_entry"] != "unknown"),
                                 "spell_starts": [x["st"] for x in g[:20]]}
                            for k, g in sorted(sig_groups.items())},
        "known_example_65253": known,
        "violations": violations,
    }
    out = os.path.join(H.RESULTS_DIR, "audit_direct_switches.json")
    H.json_dump(report, out)
    print("total violations:", len(violations))
    print("half dist:", halves)
    print("length hist (len:count):", {k: length_hist[k] for k in sorted(length_hist)})
    print("context:", ctx)
    for k, g in sorted(sig_groups.items()):
        print("signature {!r}: {} spells".format(k, len(g)))
    print("known example @65253:", known)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())