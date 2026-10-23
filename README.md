# BARCA — possession labelling for More than a Hack 2027

This repository regenerates our submission file for the MTAH 2027 possession challenge
(FC Barcelona vs Athletic Club, 199,319 tactical-video frames at 25 fps) from the official
match-data bundle. Given the data directory it writes `<team_name>.csv` — currently
`barca.csv`, a placeholder team name that is trivial to rename.

**Approach, in short.** The pipeline is fully deterministic (numpy + stdlib, no learning, no
hand-annotation). Dead-ball periods come from the Smart Tagging annotations: set-piece windows
are marked `D` up to the first persistent ball-visibility run inside the window (the restart
moment), goal windows are `D` outright, and the set-piece "Team" tag seeds possession at the
restart. During play, the raw signal is the nearest tracked player to the linearly-filled ball
track, run through a hysteresis state machine: the current possessor is held until the
opposing team's signal persists for 1.6 s, which kills the churn of a naive nearest-neighbour
baseline while staying structurally plausible (40–60 possessions per half). Frames with no
signal fall back to the official `smooth50` baseline label. All parameters were chosen for
structural plausibility — never by tuning on the public ground truth.

## Install

```bash
pip install -r requirements.txt
```

Python 3.12 was used for the verified run; dependencies are pinned to the exact verified
versions (`numpy==2.5.4`, `pandas==3.1.0`).

## Regenerate the submission

One line, from the repository root:

```bash
MTAH_DATA_DIR=/path/to/match-bundle python -m possessed --out barca.csv
```

- The data root is taken from `--data-dir /path/to/match-bundle` if you prefer the flag over
  the environment variable; both follow the official bundle layout, i.e. the inputs live at
  `<data_dir>/tactical/BAR-ATH_tactical_*` (a flat `<data_dir>/BAR-ATH_tactical_*` also
  works).
- **Expected output:** `barca.csv` — header plus exactly **199,319 data rows**
  (`frame,label`), ≈1.9 MB.
- The run is deterministic: regenerating on another machine with the same pinned versions
  produces a byte-identical file.

Before submitting, check it with the official validator from the competition repo:

```bash
python /path/to/mtah-2027/evaluation/validate_submission.py barca.csv
```

## Match data is NOT included

The match assets are not redistributable and are deliberately absent from this repository.
Enrol for MTAH 2027 and obtain the bundle as described in the competition repository
(`DATA.md` in `mtah-2027`), unpack it, and point `MTAH_DATA_DIR` at it. Only source code and
documentation live here.

## License

Source and documentation in this repository are released under the MIT License (see
`LICENSE`). The match data bundle is covered by the competition's own terms of use and is
not part of this repository.