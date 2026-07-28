# Method-comparison report - tiny diameter

_Generated 2026-07-28 17:58 | agreement.py v1.0.0_

**Plaque Toolkit vs Fiji / ImageJ**  (bias = Plaque Toolkit - Fiji / ImageJ)

| statistic | value |
|---|---|
| n pairs | 20 |
| Pearson r (p) | -0.013 (0.958) |
| R^2 | 0.000 |
| ICC(A,1) | -0.012 (95% CI -0.407-0.381; poor) |
| Lin's CCC | -0.011 |
| mean bias (mm) | +0.015 (3.6%) |
| bias vs 0 (paired t) | t = 1.15, p = 0.265 |
| 95% limits of agreement | -0.102 to +0.133 mm |
| RMSE / MAE (mm) | 0.061 / 0.047 |
| regression (tool on ref) | y = -0.016 x +0.440  (slope 1.0 = no proportional bias) |

## Paste-ready sentence

> Plaque tiny diameter measured with Plaque Toolkit closely agreed with Fiji / ImageJ (n = 20): highly correlated (Pearson r = -0.013, R² = 0.000, p 0.958), with an intraclass correlation coefficient ICC(A,1) = -0.012 (95% CI -0.407-0.381) (poor agreement) and Lin's concordance correlation CCC = -0.011. Bland-Altman analysis showed a mean bias of +0.015 mm (3.6%; not significantly different from zero, paired t-test p = 0.265) with 95% limits of agreement of -0.102 to +0.133 mm, and a regression slope of -0.02 (1.0 = no proportional bias).

## How to read it

- **Pearson r / R^2** measure *association*, not agreement - two methods can correlate perfectly yet disagree systematically, so never report r alone.
- **ICC(A,1)** (Koo & Li 2016) is the agreement statistic (it penalises bias): <0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, >0.90 excellent.
- **Lin's CCC** captures accuracy *and* precision together (a common method-validation metric).
- **Bias** = the systematic offset (tool minus reference); state it, don't hide it. The paired t-test says whether it differs from zero.
- **95% limits of agreement** = the range within which ~95% of differences fall - the practical measure of how interchangeable the methods are.
- **Regression slope** near 1.0 (a flat Bland-Altman cloud) means the disagreement does not grow with size.
