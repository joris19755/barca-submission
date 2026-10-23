## Ablation matrix

variant | poss H1/H2 | mean s | median s | D share | H/A/X share | macroF1* | spellF1* | n spells*
--- | --- | --- | --- | --- | --- | --- | --- | ---
no_smart_dead | 181/162 | 18.6 | 10.2 | 0.0 | 0.446/0.351/0.203 | 0.5196 | 0.4103 | 22
no_ball_fill | 165/165 | 15.6 | 8.9 | 0.1532 | 0.3351/0.3087/0.203 | 0.6671 | 0.4211 | 21
no_hysteresis | 918/919 | 2.8 | 1.0 | 0.1532 | 0.3342/0.3095/0.203 | 0.6159 | 0.0441 | 128
full_default | 183/176 | 14.3 | 8.4 | 0.1532 | 0.3393/0.3045/0.203 | 0.6671 | 0.4211 | 21

* official-scorer columns are public-window diagnostics only — never a tuning signal (rules: no tuning on the public 5-min window).
Observations: smart dead-ball is what creates the D class and the restart priors (no_smart_dead collapses D and loses possession structure at restarts); ball fill stabilises the raw signal in camera gaps (no_ball_fill churns); hysteresis is the main possession-count control (no_hysteresis reproduces the raw-baseline fragmentation, ~918 -> 918+ possessions/half vs 183/176 full).
