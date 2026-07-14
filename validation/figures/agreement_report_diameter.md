# Method-comparison report - diameter

_Generated 2026-07-14 11:34 | agreement.py v1.0.0_

**Plaque Toolkit vs Fiji / ImageJ**  (bias = Plaque Toolkit - Fiji / ImageJ)

| statistic | value |
|---|---|
| n pairs | 100 |
| Pearson r (p) | 0.979 (< 0.001) |
| R^2 | 0.958 |
| ICC(A,1) | 0.974 (95% CI 0.963-0.982; excellent) |
| Lin's CCC | 0.974 |
| mean bias (mm) | -0.028 (-1.8%) |
| bias vs 0 (paired t) | t = -4.76, p < 0.001 |
| 95% limits of agreement | -0.146 to +0.089 mm |
| RMSE / MAE (mm) | 0.066 / 0.049 |
| regression (tool on ref) | y = 0.985 x -0.004  (slope 1.0 = no proportional bias) |

## Paste-ready sentence

> Plaque diameter measured with Plaque Toolkit closely agreed with Fiji / ImageJ (n = 100): highly correlated (Pearson r = 0.979, R² = 0.958, p < 0.001), with an intraclass correlation coefficient ICC(A,1) = 0.974 (95% CI 0.963-0.982) (excellent agreement) and Lin's concordance correlation CCC = 0.974. Bland-Altman analysis showed a mean bias of -0.028 mm (-1.8%; significantly different from zero, paired t-test p < 0.001) with 95% limits of agreement of -0.146 to +0.089 mm, and a regression slope of 0.98 (1.0 = no proportional bias).

## How to read it

- **Pearson r / R^2** measure *association*, not agreement - two methods can correlate perfectly yet disagree systematically, so never report r alone.
- **ICC(A,1)** (Koo & Li 2016) is the agreement statistic (it penalises bias): <0.5 poor, 0.5-0.75 moderate, 0.75-0.90 good, >0.90 excellent.
- **Lin's CCC** captures accuracy *and* precision together (a common method-validation metric).
- **Bias** = the systematic offset (tool minus reference); state it, don't hide it. The paired t-test says whether it differs from zero.
- **95% limits of agreement** = the range within which ~95% of differences fall - the practical measure of how interchangeable the methods are.
- **Regression slope** near 1.0 (a flat Bland-Altman cloud) means the disagreement does not grow with size.
