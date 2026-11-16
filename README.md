# BARCA — possession labelling for More than a Hack 2027

I built this for the MTAH 2027 possession challenge. Feed it the official match-data
bundle (FC Barcelona vs Athletic Club, 199,319 tactical-video frames at 25 fps) and it
writes `<team_name>.csv` — currently `barca.csv`, trivial to rename.

The pipeline is deterministic: numpy + stdlib, no learning, no hand-annotation. Dead-ball
periods come from Smart Tagging annotations — set-piece windows are marked `D` up to the
first persistent ball-visibility run inside the window (the restart moment), goal windows
are `D` outright, and the set-piece "Team" tag seeds possession at the restart. During play
the raw signal is the nearest tracked player to the linearly-filled ball track, run through
a hysteresis state machine: the current possessor holds until the opposing team's signal
persists for 1.6 s, which kills the churn of a naive nearest-neighbour baseline while
staying structurally plausible (222 possessions in H1, 225 in H2 on the graded runs of this
match — measured from the regenerated file, not a target range). Frames with no signal fall
back to the official `smooth50` baseline label.

All parameters were chosen for structural plausibility: no frame labels and no scorer score
(macroF1, spellF1, IoU) ever served as a selection criterion. The one public-window
quantity that did inform structure was the published mean possession duration of 14.19 s,
used purely as a structural plausibility anchor.

I tried shaving off the transition latency but none of the variants beat the current
default — that grid sits in `tests/_results/transition_latency_grid.json` as a record of
what didn't work.

## Install

```bash
pip install -r requirements.txt
```

Python 3.12, deps pinned to verified versions (`numpy==2.5.4`, `pandas==3.1.0`).

## Regenerate

```bash
MTAH_DATA_DIR=/path/to/match-bundle python -m possessed --out barca.csv
```

- **Output:** `barca.csv` — header + 199,319 data rows (`frame,label`) ≈1.9 MB,
  md5 `96a8d91e50d7c0631bad520ac1fe927b` (byte-identical across platforms with pinned deps).
- The data root comes from `--data-dir /path/to/match-bundle` or `$MTAH_DATA_DIR`; both
  follow the official bundle layout (`<data_dir>/tactical/BAR-ATH_tactical_*`, a flat
  `<data_dir>/BAR-ATH_tactical_*` also works).
- Optional knobs (defaults = shipped run, testing-only):
  `--challenge-band FAST,SLOW` (default `20,60`), `--no-phase-prior` (default: on),
  `--x-margin M` (default `2.0`), `--challenge-n N` (default: adaptive).

### Tests and audit

```bash
MTAH_DATA_DIR=/path/to/match-bundle python -m pytest tests -q   # 16 tests
MTAH_DATA_DIR=/path/to/match-bundle python tests/audit_direct_switches.py   # → tests/_results/
```

### Documentation

`docs/` — `metric_leverage.md` (how the official scorer works and what a single frame can
move), `data_audit.md` (signals in the bundle I'm not using), `ensemble_selection.md` (the
8-run grid over the new knobs and why the shipped defaults won).

A note for readers of `tests/_results/`: the transition-latency grid in there was measured
on GT metrics but fully reverted — no parameter from that round was adopted.

Before submitting, validate with the official checker:

```bash
python /path/to/mtah-2027/evaluation/validate_submission.py barca.csv
```

## Match data is NOT included

The match assets aren't redistributable and aren't in this repo. Enrol for MTAH 2027,
get the bundle as described in the competition repo (`DATA.md` in `mtah-2027`), unpack it,
point `MTAH_DATA_DIR` at it. Only source code and docs live here.

## License

MIT (see `LICENSE`). The match data bundle is covered by the competition's own terms.