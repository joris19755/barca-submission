## Bootstrap uncertainty on spellF1 (public window, 17 GT possessions, 2000 draws, seed 20261023)

submission | point spellF1 | mean | std | 5-95% band
--- | --- | --- | --- | ---
ours (barca) | 0.4211 | 0.4214 | 0.0833 | 0.2842 .. 0.5579
baseline_smooth125 | 0.4242 | 0.4231 | 0.1005 | 0.2667 .. 0.5939

gap (smooth125 - ours) = +0.0032; independent-sample SE = 0.1306; z = +0.02; bands overlap: True

Interpretation: the two bands sit almost entirely on top of each other (overlap) and the gap is ~0.0 standard errors — well inside noise. On the public 5-minute window the 0.4211-vs-0.4242 difference is NOT distinguishable from sampling variation; it cannot support any decision.
