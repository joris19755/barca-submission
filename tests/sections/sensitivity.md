## CHALLENGE_N sensitivity sweep

CHALLENGE_N | window s | poss H1/H2 (total) | mean s | median s | D share | macroF1* | spellF1*
--- | --- | --- | --- | --- | --- | --- | ---
15 | 0.6s | 426/429 (855) | 6.0 | 2.7 | 0.1532 | 0.6454 | 0.2121
25 | 1.0s | 262/260 (522) | 9.8 | 5.3 | 0.1532 | 0.6515 | 0.3583
40 | 1.6s | 183/176 (359) | 14.3 | 8.4 | 0.1532 | 0.6671 | 0.4211
60 | 2.4s | 133/129 (262) | 19.6 | 12.4 | 0.1532 | 0.6736 | 0.4933
75 | 3.0s | 99/106 (205) | 25.0 | 18.3 | 0.1532 | 0.6691 | 0.4533

* public-window diagnostics only; not a tuning signal.
Reading: possession count spans 205..855 across the grid; the legacy N=40 row sits at 183/176 per half. The shipped default is the ADAPTIVE machine (mean spell ~12-16 s vs the 14.19 s structural anchor), so the legacy grid only shows the knob's direction; score columns move within a band and are reported without acting on them.
