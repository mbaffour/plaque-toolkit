# Method-comparison report - tiny area

_Generated 2026-07-28 17:58 | agreement.py v1.0.0_

**Plaque Toolkit vs Fiji / ImageJ**  (bias = Plaque Toolkit - Fiji / ImageJ)

| statistic | value |
|---|---|
| n pairs | 20 |
| Pearson r (p) | 0.004 (0.988) |
| R^2 | 0.000 |
| ICC(A,1) | 0.003 (95% CI -0.401-0.385; poor) |
| Lin's CCC | 0.003 |
| mean bias (mm2) | +0.011 (7.6%) |
| bias vs 0 (paired t) | t = 1.25, p = 0.227 |
| 95% limits of agreement | -0.066 to +0.087 mm2 |
| RMSE / MAE (mm2) | 0.040 / 0.031 |
| regression (tool on ref) | y = 0.005 x +0.149  (slope 1.0 = no proportional bias) |

## Paste-ready sentence

> Plaque tiny area measured with Plaque Toolkit closely agreed with Fiji / ImageJ (n = 20): highly correlated (Pearson r = 0.004, R² = 0.000, p 0.988), with an intraclass correlation coefficient ICC(A,1) = 0.003 (95% CI -0.401-0.385) (poor agreement) and Lin's concordance correlation CCC = 0.003. Bland-Altman analysis showed a mean bias of +0.011 mm2 (7.6%; not significantly different from zero, paired t-test p = 0.227) with 95% limits of agreement of -0.066 to +0.087 mm2, and a regression slope of 0.00 (1.0 = no proportional bias).

## How to read it

- **Pearson r / R^2** measure *association*, not agreement - two methods can correlate perfectly yet disagree systematically, so never report r alone.
- **ICC(A,1)** (Koo & Li 2016) is the agreement statistic (it penalises bias): <0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, >0.90 excellent.
- **Lin's CCC** captures accuracy *and* precision together (a common method-validation metric).
- **Bias** = the systematic offset (tool minus reference); state it, don't hide it. The paired t-test says whether it differs from zero.
- **95% limits of agreement** = the range within which ~95% of differences fall - the practical measure of how interchangeable the methods are.
- **Regression slope** near 1.0 (a flat Bland-Altman cloud) means the disagreement does not grow with size.
