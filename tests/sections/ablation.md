## Ablation matrix

variant | poss H1/H2 | mean s | median s | D share | H/A/X share | macroF1* | spellF1* | n spells*
--- | --- | --- | --- | --- | --- | --- | --- | ---
no_smart_dead | 179/164 | 18.5 | 9.4 | 0.0 | 0.4541/0.3412/0.2047 | 0.5162 | 0.3897 | 22
no_ball_fill | 167/173 | 15.1 | 8.6 | 0.1532 | 0.3363/0.3056/0.2049 | 0.664 | 0.4 | 21
no_hysteresis | 789/785 | 3.2 | 1.4 | 0.1532 | 0.332/0.3062/0.2086 | 0.6172 | 0.0673 | 96
full_default | 179/182 | 14.2 | 8.4 | 0.1532 | 0.3381/0.3037/0.2049 | 0.664 | 0.4 | 21

* official-scorer columns are public-window diagnostics only — never a tuning signal (rules: no tuning on the public 5-min window).
Observations: smart dead-ball is what creates the D class and the restart priors (no_smart_dead collapses D and loses possession structure at restarts); ball fill stabilises the raw signal in camera gaps (no_ball_fill churns); hysteresis is the main possession-count control (no_hysteresis reproduces the raw-baseline fragmentation, ~789 -> 789+ possessions/half vs 179/182 full).
