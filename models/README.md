# models/

`boundaries_v2b.joblib`: N04 audio-learned-v2b Unknown-boundary detector
(scikit-learn 1.5.2 HistGradientBoostingClassifier: max_iter 300, learning rate
0.05, 15 leaves, l2 1.0). Trained 2026-11-19 on all 95 sets with known
boundaries: the 71 Nov 13 training sets and the Production sets holding stored
v2b entries (known boundaries from Production entries; features from
`boundaries_v2b.frame_features`). No secrets; features only.

Check against the 115 stored v2b Unknown entries (353 boundaries): 287 within
15 s, 323 within 30 s, estimated count equal on 100/115. Tornado Wallace at
Rainbow Serpent: all within 13 s. Fred Everything Vinyl Jam: first Unknown
split at 3:34 (approved 3:27). Exact reproduction is not possible: the original
fit used random early stopping. Retrain with `.github/n04-train-request.json`.
