## CHALLENGE_N sensitivity sweep

CHALLENGE_N | window s | poss H1/H2 (total) | mean s | median s | D share | macroF1* | spellF1*
--- | --- | --- | --- | --- | --- | --- | ---
15 | 0.6s | 428/430 (858) | 6.0 | 2.7 | 0.1532 | 0.6454 | 0.209
25 | 1.0s | 262/265 (527) | 9.7 | 5.2 | 0.1532 | 0.6515 | 0.3583
40 | 1.6s | 184/179 (363) | 14.1 | 8.2 | 0.1532 | 0.6671 | 0.4211
60 | 2.4s | 134/131 (265) | 19.4 | 11.9 | 0.1532 | 0.6736 | 0.4933
75 | 3.0s | 100/107 (207) | 24.8 | 17.9 | 0.1532 | 0.6691 | 0.4533

* public-window diagnostics only; not a tuning signal.
Reading: possession count spans 207..858 across the grid; N=40 sits at 184/179 per half. Structural plausibility (roughly 40-60/half, mean 12-18 s) holds around the shipped N; the score columns move within a band and are reported without acting on them.
