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

### Deep‑learning detection and classifier training (if the Precise engine was used)
> The **Precise** engine augments the Plaque Size Tool detector with a pre‑trained deep‑learning
> plaque detector — a YOLO segmentation model (**PlaqSeg**, from PlaqSegDesktop, Carbon16, release
> app‑v0.2.1, 2026; weights of OnePetri lineage, Shamash & Maurice, 2021), used for inference only —
> and an optional convolutional **plaque‑versus‑texture classifier** that
> we trained in‑house as a precision filter. The classifier (a ResNet‑18 fine‑tuned from ImageNet)
> was trained on 48 × 48‑pixel image patches: positive patches from hand‑labelled plaque centres on
> our own plates, augmented with external plaque imagery (**VACVPlaque**, *Scientific Data* 2025,
> doi:10.1038/s41597‑025‑05030‑8, CC‑BY‑4.0; and the **OnePetri** bacteriophage plaque set,
> CC‑BY‑NC‑SA), and negative patches (lawn texture, dish rim, bubbles, debris) mined from
> uninfected control plates. Training used a **leave‑one‑plate‑out** protocol with **iterative
> hard‑negative mining**, selecting the model by held‑out F1 (deployed model: leave‑one‑plate‑out
> F1 ≈ 0.95). Adding the external datasets changed held‑out F1 only marginally (VACVPlaque −0.003;
> OnePetri +0.0003), so performance was driven mainly by the in‑house ground truth and
> hard‑negative mining. A separate false‑positive‑reduction analysis on uninfected control plates
> found the residual false‑positive rate (≈ 3 per blank plate for Precise) was not further reducible
> by classifier or gate tuning. Full training details and code are in the software's
> `docs/TRAINING_AND_MODELS.md` and model card. *(Include this paragraph only if you used the
> Precise engine.)*

### Validation against manual measurement (Fiji/ImageJ)
> To validate the software's measurements, **100 plaques** `[spanning N plates and a range of sizes]`
> were additionally measured **independently** in Fiji/ImageJ (Schindelin et al., 2012) by manual
> tracing, blind to the software's boundaries, on the same calibrated images. Agreement between the two
> methods was quantified by Bland–Altman analysis (mean bias and 95% limits of agreement; Bland &
> Altman, 1986), the intraclass correlation coefficient (ICC; two‑way, absolute agreement, per Koo &
> Li, 2016), and Pearson's *r*, on both area and area‑equivalent diameter.

### Statistical analysis
> `[Software, e.g. R x.x / Python x.x / the Plaque Toolkit "Fiji agreement" utility]`. Agreement was
> assessed as described above; a linear regression of the two methods' diameters was used to check for
> proportional bias (slope = 1 indicating none). Bland–Altman analysis with limits of agreement is the
> standard technique for comparing two measurement methods (Bland & Altman, 1986) and is the same
> approach used to validate the original Plaque Size Tool against manual ImageJ (Trofimova & Jaschke,
> 2021).

---

## Results (validation paragraph)

> Plaque diameters measured with Plaque Toolkit agreed closely with independent manual measurements in
> Fiji/ImageJ (n = 100 plaques; **Fig. X**): Pearson *r* = 0.98, ICC = 0.97. Bland–Altman analysis
> showed a small mean bias of **−0.03 mm** (Plaque Toolkit − Fiji; ≈1.8%; paired *t*-test p < 0.001),
> with 95% limits of agreement of **−0.15 to +0.09 mm** and no proportional bias (the difference did not
> vary with plaque size: regression of difference on mean, slope = +0.006, p = 0.78; equivalently the
> Toolkit-on-Fiji slope was 0.98, not significantly different from 1). `[If you report area:
> mean bias −0.07 mm², 95% limits of agreement −0.34 to +0.20 mm², ICC = 0.97.]` The software therefore
> reproduces manual plaque sizing to within a few percent, with a small, size‑independent tendency to
> read marginally smaller than hand tracing.

### Figure
Use `PlaqueToolkit_vs_Fiji_BlandAltman.png` (this folder / your Downloads).

> **Figure X.** Agreement between Plaque Toolkit and manual Fiji/ImageJ plaque diameter measurements
> (n = 100). **(A)** Method comparison against the line of identity (*r* = 0.98, ICC = 0.97).
> **(B)** Bland–Altman plot; solid line = mean bias (−0.03 mm), dashed lines = 95% limits of agreement.
> In both panels, red points mark the 8 plaques whose Toolkit − Fiji difference fell outside the 95%
> limits of agreement (the largest disagreements); green/blue points fall within the limits.

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
- **Report plaques *and* plates; the plate is the experimental unit.** Write "n = 100 plaques from
  N plates," not just "n = 100." A size‑agreement claim is a *per‑plaque* measurement comparison, so
  100 plaques already gives tight limits of agreement — a strong sample for the size question. But
  plaques on one plate share a single calibration, focus and operator session, so they are not fully
  independent (a pseudoreplication caveat). **Two plates is an acceptable minimum for a local size
  validation; spanning ≥ 5 plates across your range of densities/sizes — and, ideally, a second
  independent tracer — makes the agreement setup‑robust and pre‑empts a reviewer's objection.** Plaque
  *count / titre* validation is separate and *requires* plate‑level replicates (one count per plate).

## References
- Bland J.M. & Altman D.G. (1986). *Statistical methods for assessing agreement between two methods of
  clinical measurement.* Lancet 327(8476):307–310. doi:10.1016/S0140-6736(86)90837-8
- Koo T.K. & Li M.Y. (2016). *A guideline of selecting and reporting intraclass correlation
  coefficients for reliability research.* J. Chiropr. Med. 15(2):155–163. doi:10.1016/j.jcm.2016.02.012
- Trofimova E. & Jaschke P.R. (2021). *Plaque Size Tool: an automated plaque analysis tool for
  simplifying and standardising bacteriophage plaque morphology measurements.* Virology 561:1–5.
  doi:10.1016/j.virol.2021.05.011
- Schindelin J. et al. (2012). *Fiji: an open-source platform for biological-image analysis.*
  Nat. Methods 9:676–682. doi:10.1038/nmeth.2019
- Schneider C.A. et al. (2012). *NIH Image to ImageJ: 25 years of image analysis.* Nat. Methods
  9:671–675. doi:10.1038/nmeth.2089
- Shamash M. & Maurice C.F. (2021). *OnePetri: accelerating common bacteriophage Petri dish assays
  with computer vision.* PHAGE 2(4):224–231. doi:10.1089/phage.2021.0012
- Carbon16 (2026). *PlaqSegDesktop* (release app‑v0.2.1) [software]. The PlaqSeg YOLO‑seg plaque
  detector, used as the Precise engine's primary detector. https://github.com/Carbon16/PlaqSegDesktop
- VACVPlaque dataset (2025). *A digital photography dataset for Vaccinia Virus plaque quantification
  using Deep Learning.* Scientific Data 12:719. doi:10.1038/s41597-025-05030-8 (CC-BY-4.0)
