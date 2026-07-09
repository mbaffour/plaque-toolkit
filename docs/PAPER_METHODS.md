# Methods & Results text for your paper (ready to adapt)

Paste‑ready wording for measuring plaques with Plaque Toolkit and reporting its agreement with
Fiji/ImageJ. **Real validation numbers are already filled in** (from
[VALIDATION_RESULTS.md](VALIDATION_RESULTS.md)); replace only the `[bracketed]` parts with your own
specifics (camera, illumination, host/phage, engine used, number of plates).

---

## Methods

### Plaque imaging
> Plates were photographed square‑on with `[camera / phone model]` under `[transmitted / reflected]`
> illumination, one plate per image. A `[ruler / the Petri‑dish rim of known diameter (85 mm agar
> base)]` was included in the plane of the agar as a spatial reference for calibration.

### Plaque size measurement
> Plaque size was measured with **Plaque Toolkit** (v1.0.2; https://github.com/mbaffour/plaque-toolkit),
> a desktop application built on the adaptive‑local plaque‑detection algorithm of the peer‑reviewed
> Plaque Size Tool (Trofimova & Jaschke, 2021). Each image was spatially calibrated to millimetres
> `[from the dish diameter / from the in‑frame ruler]`. Plaques were detected `[with the Published
> engine / with the in‑house Precise engine]` and then visually inspected; missed or merged plaques
> were corrected manually (auto‑trace, freehand outline, or watershed splitting), and
> touching/overlapping plaques were flagged and excluded from size statistics. For each plaque the
> software reports its area and the **area‑equivalent diameter**, *d* = 2·√(*A*/π).

### Validation against manual measurement (Fiji/ImageJ)
> To validate the software's measurements, **100 plaques** `[spanning N plates and a range of sizes]`
> were additionally measured **independently** in Fiji/ImageJ (Schindelin et al., 2012) by manual
> tracing, blind to the software's boundaries, on the same calibrated images. Agreement between the two
> methods was quantified by Bland–Altman analysis (mean bias and 95% limits of agreement), the
> intraclass correlation coefficient (ICC; two‑way, absolute agreement), and Pearson's *r*, on both
> area and area‑equivalent diameter.

### Statistical analysis
> `[Software, e.g. R x.x / Python x.x / the Plaque Toolkit "Compare vs Fiji" utility]`. Agreement was
> assessed as described above; a linear regression of the two methods' diameters was used to check for
> proportional bias (slope = 1 indicating none).

---

## Results (validation paragraph)

> Plaque diameters measured with Plaque Toolkit agreed closely with independent manual measurements in
> Fiji/ImageJ (n = 100 plaques; **Fig. X**): Pearson *r* = 0.98, ICC = 0.97. Bland–Altman analysis
> showed a small mean bias of **−0.03 mm** (Plaque Toolkit − Fiji; ≈1.8%), with 95% limits of agreement
> of **−0.15 to +0.09 mm** and no proportional bias (regression slope = 1.01). `[If you report area:
> mean bias −0.07 mm², 95% limits of agreement −0.34 to +0.20 mm², ICC = 0.97.]` The software therefore
> reproduces manual plaque sizing to within a few percent, with a small, size‑independent tendency to
> read marginally smaller than hand tracing.

### Figure
Use `PlaqueToolkit_vs_Fiji_BlandAltman.png` (this folder / your Downloads).

> **Figure X.** Agreement between Plaque Toolkit and manual Fiji/ImageJ plaque diameter measurements
> (n = 100). **(A)** Method comparison against the line of identity (*r* = 0.98, ICC = 0.97).
> **(B)** Bland–Altman plot; solid line = mean bias (−0.03 mm), dashed lines = 95% limits of agreement.

---

## Reporting notes (so a reviewer can't object)

- **Cite the algorithm correctly.** The validated, peer‑reviewed detection method is the **Published**
  engine (Trofimova & Jaschke, 2021). If you used **Precise**, state that it is an in‑house extension
  (PST + a PlaqSeg deep‑learning detector) and **not** independently peer‑reviewed — the validation
  above is *your own local* size validation, which is exactly what this section provides.
- **Size vs count.** This validates plaque **size**. If you report plaque **counts / titre**, validate
  those separately (whole‑plate hand counts; and note the negative‑control false‑positive floor —
  Precise ≈ 3 per blank plate on this setup).
- **Report the bias, don't hide it.** State the −0.03 mm (≈1.8%) offset and the 95% limits of
  agreement; a stated, size‑independent bias is normal in method comparison and reads as rigour.

## References
- Trofimova E. & Jaschke P.R. (2021). *An improved and open-source method for plaque size and titer
  quantification.* Virology 561:1–5. doi:10.1016/j.virol.2021.05.011
- Schindelin J. et al. (2012). *Fiji: an open-source platform for biological-image analysis.*
  Nat. Methods 9:676–682. doi:10.1038/nmeth.2019
- Schneider C.A. et al. (2012). *NIH Image to ImageJ: 25 years of image analysis.* Nat. Methods
  9:671–675. doi:10.1038/nmeth.2089
