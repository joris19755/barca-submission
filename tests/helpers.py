"""Shared paths, loaders, scoring and structural statistics for the test harness.

Everything here is read-only against ./mtah-2027 (official scorer imported, never modified)
and writes any scorer output into tests/_results/ inside this repository.
"""
import hashlib
import importlib.util
import json
import os
import sys

import numpy as np
import pandas as pd

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)          # barca-submission/
WORKSPACE = os.path.dirname(REPO_ROOT)          # chat workspace root
RESULTS_DIR = os.path.join(TESTS_DIR, "_results")
SECTIONS_DIR = os.path.join(TESTS_DIR, "sections")
CACHE_DIR = os.path.join(TESTS_DIR, "_cache")
MTAH = os.path.join(WORKSPACE, "mtah-2027")
SUBMISSION = os.path.join(WORKSPACE, "submissions", "barca.csv")
REPO_SUBMISSION = os.path.join(REPO_ROOT, "barca.csv")
PUBLIC_GT = os.path.join(MTAH, "evaluation", "gt", "BAR-ATH_possession_gt_public.csv")
BASELINE_SMOOTH125 = os.path.join(MTAH, "evaluation", "results", "baseline_smooth125.csv")
# H1 and H2 graded spans, from possession_metrics.valid_runs docstring (whole match);
# the public GT only covers the first 7500 frames of H1.
GRADED_RUNS = ((11185, 90652), (110808, 190198))
PUBLIC_WINDOW = (11185, 18685)   # half-open, the 7500-frame public slice
N_FRAMES = 199319
SHIPPED_MD5 = "911d935da9e8abc7acaf8aa6e1aa098b"
FPS = 25

sys.path.insert(0, REPO_ROOT)                   # so `import possessed` works from tests
sys.path.insert(0, os.path.join(MTAH, "evaluation"))


def load_pm():
    """Official possession_metrics module, imported read-only from mtah-2027."""
    spec = importlib.util.spec_from_file_location(
        "pm_under_test", os.path.join(MTAH, "evaluation", "possession_metrics.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_labels(path):
    """Label column of a frame,label CSV as a numpy object array of length N_FRAMES."""
    frame = pd.read_csv(path, dtype={"label": "object"})
    labels = frame["label"].values
    assert len(labels) == N_FRAMES, "{} has {} rows".format(path, len(labels))
    return np.array([str(v).strip().upper() for v in labels], dtype=object)


def md5_file(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_labels_csv(labels, path):
    """Byte-format identical to pipeline.write_submission (header + i,label lines)."""
    with open(path, "w") as handle:
        handle.write("frame,label\n")
        handle.writelines("{},{}\n".format(i, lab) for i, lab in enumerate(labels))
    return path


def score(labels, gt_codes=None, pm=None):
    """Official evaluate() of `labels` on the public GT window (diagnostic only)."""
    if pm is None:
        pm = load_pm()
    if gt_codes is None:
        gt_codes = pm.label_codes(pm.read_label_csv(PUBLIC_GT))
    return pm.evaluate(gt_codes, pm.label_codes(labels))


def spells_in(labels, start, stop):
    """Maximal runs of H or A inside [start, stop): [(start, stop, letter), ...]."""
    seg = labels[start:stop]
    out, i, n = [], 0, len(seg)
    while i < n:
        if seg[i] in ("H", "A"):
            j = i
            while j < n and seg[j] == seg[i]:
                j += 1
            out.append((start + i, start + j, str(seg[i])))
            i = j
        else:
            i += 1
    return out


def structural_stats(labels):
    """Per-half possessions / mean / median duration (s) + label shares of the full array."""
    stats = {"possessions": [], "mean_s": [], "median_s": [], "shares": {}}
    for key in ("H", "A", "D", "X"):
        stats["shares"][key] = float(np.mean(labels == key))
    for start, stop in GRADED_RUNS:
        lengths = [en - st for st, en, _ in spells_in(labels, start, stop)]
        arr = np.array(lengths, dtype=float) if lengths else np.array([0.0])
        stats["possessions"].append(len(lengths))
        stats["mean_s"].append(float(arr.mean() / FPS))
        stats["median_s"].append(float(np.median(arr) / FPS))
    return stats


def section_paths():
    """Cached report sections written by the heavy modules (ablation/sensitivity/bootstrap)."""
    return {name: os.path.join(SECTIONS_DIR, name + ".md")
            for name in ("ablation", "sensitivity", "bootstrap")}


def load_section(name, builder):
    """Return a cached report section, building it (once) if absent."""
    path = section_paths()[name]
    if not os.path.isfile(path):
        os.makedirs(SECTIONS_DIR, exist_ok=True)
        text = builder()
        with open(path, "w") as handle:
            handle.write(text)
    with open(path) as handle:
        return handle.read()


def json_dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(obj, handle, indent=2, sort_keys=True)
    return path