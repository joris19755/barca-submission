"""Regression tests for the four code-review fixes — fictional inputs, no match data.

Each test encodes exactly one fix and fails against the pre-fix pipeline:
  1. stream_atd parses player positions even when the ball is missing (NaN ball),
  2. the combined evidence (distance + superiority + phase votes) decides the switch
     candidate; the nearest-player raw signal is only the tie-break,
  3. DEFENSIVE TRANSITION events fire their own prior with INVERTED team semantics
     (the tagged team lost the ball -> the prior names the opponent),
  4. the 40-frame structural gate is a SOFT preference: sustained evidence may switch
     right up to a stoppage.
All arrays are synthetic; nothing here reads the match bundle or any ground truth.
"""
import numpy as np

from possessed import pipeline as pl


def _inputs():
    """Synthetic machine inputs: raw signal = HOME everywhere, no dead ball, all known."""
    n = pl.N_FRAMES
    feats = {
        "dist": np.full((n, 2), 5.0),
        "sup": np.zeros((n, 2), dtype=np.int64),
        "ball_kmh": np.zeros(n),
        "speed_ok": np.zeros(n, dtype=bool),
        "vx_sign": np.zeros(n, dtype=np.int8),
        "atk": np.zeros((n, 2), dtype=np.int8),
    }
    raw = np.full(n, pl.HOME, dtype=np.int8)
    fallback = np.full(n, "X", dtype="<U1")
    known = np.ones(n, dtype=bool)
    eva = np.zeros((n, 2))
    return feats, raw, fallback, known, eva


def test_regression1_players_survive_missing_ball(tmp_path):
    """Fix 1: a NaN ball must not skip the player positions on that atd line."""
    path = tmp_path / "atd_raw.txt"
    # frame 1: ball occluded ("NaN,..." starts with N) but two players visible;
    # frame 2: ball present, slot 0 exactly under it.
    path.write_text(
        "1:0.50,0.50,1.0;0.60,0.60,1.0:NaN,NaN,NaN\n"
        "2:0.50,0.50,1.0;0.90,0.90,1.0:0.50,0.50,1.0\n")
    team_of = [pl.HOME, pl.AWAY]
    ball_xy, player_xy, raw_team = pl.stream_atd(str(path), team_of)
    # players parsed on the ball-missing line (pre-fix: whole line was skipped)
    assert np.isfinite(player_xy[0, 0]).all() and np.isfinite(player_xy[0, 1]).all()
    assert np.isnan(ball_xy[0]).all()
    assert raw_team[0] == pl.NOBODY          # no ball -> no nearest-player signal
    # ball-present line still yields the signal from the nearest player
    assert np.isfinite(ball_xy[1]).all()
    assert raw_team[1] == team_of[0]


def test_regression2_combined_evidence_decides_candidate():
    """Fix 2: evidence favouring AWAY must switch the label even when raw says HOME."""
    feats, raw, fallback, known, eva = _inputs()
    start, stop = pl.GRADED_RUNS[0]
    feats["dist"][:] = (10.0, 2.0)              # AWAY clearly nearer (8 m advantage)
    eva[start + 30:stop, pl.AWAY] = 3.0         # combined evidence flips to AWAY
    labels = pl.state_machine(raw, [], fallback, feats=feats, ev=eva, ball_known=known)
    assert labels[start + 10] == "H"            # before the flip: incumbent holds
    assert labels[start + 60] == "A"            # after: evidence wins over raw HOME
    # (pre-fix the raw HOME signal == state, so no streak ever formed: all H)


def test_regression3_defensive_transition_prior_inverted():
    """Fix 3: defensive transition fires its own prior and names the GAINING team."""
    events = [
        {"code": "defensive transition", "team": pl.HOME, "start": 1000, "end": 2000},
        {"code": "attacking transition", "team": pl.HOME, "start": 3000, "end": 4000},
        {"code": "progression", "team": pl.AWAY, "start": 5000, "end": 6000},
    ]
    phase_vote, box_vote, transition = pl.phase_priors(events)
    # defensive: tagged HOME went backwards -> the prior names AWAY (the gainer)
    assert np.all(transition[1000:2000] == pl.AWAY)
    assert transition[999] == pl.NOBODY and transition[2000] == pl.NOBODY
    # attacking: tagged HOME won it forward -> prior stays HOME
    assert np.all(transition[3000:4000] == pl.HOME)
    # neither transition code is a phase/box vote; progression still is
    assert not phase_vote[1000:2000].any() and not phase_vote[3000:4000].any()
    assert phase_vote[5000:6000, pl.AWAY].any()
    assert not box_vote.any()


def test_regression4_structural_gate_soft_near_run_edge():
    """Fix 4: sustained evidence may switch in the last CHALLENGE_N frames of a run.

    The soft branch measures `room` to the graded-run edge: with < CHALLENGE_N frames
    left, conf >= CONF_STRONG (or the fast band) may switch right up to the edge.
    Pre-fix the absolute gate required `t + CHALLENGE_N <= stop`, so this challenge
    (starting stop-20) never switched.
    """
    feats, raw, fallback, known, eva = _inputs()
    _, stop = pl.GRADED_RUNS[0]
    flip = stop - 20                           # 20 frames of room left
    dead = []
    feats["dist"][:] = (20.0, 2.0)             # 18 m advantage -> n_eff = CHALLENGE_FAST
    eva[flip:stop, pl.AWAY] = 3.0              # confidence 3.0 >= CONF_STRONG
    labels = pl.state_machine(raw, dead, fallback, feats=feats, ev=eva,
                              ball_known=known)
    assert labels[flip - 1] == "H"             # incumbent holds before the challenge
    assert labels[stop - 1] == "A"             # switched on the final frame of the run
    # (pre-fix the absolute gate refused any switch with t+CHALLENGE_N > stop -> H)