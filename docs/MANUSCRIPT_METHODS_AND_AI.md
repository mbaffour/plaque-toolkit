# Manuscript snippets — brief Methods + AI-use statement

Copy-paste blocks for a paper that measures plaques with **Plaque Toolkit (Precise engine)**.
Numbers are the authors' own local validation (see [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md),
§2B/§2D, n = 100 independent Fiji traces). Fill only the `[bracketed]` parts. The longer,
fully-referenced version is in [PAPER_METHODS.md](PAPER_METHODS.md); the pipeline figure is
`docs/plaque_pipeline.svg`.

---

## 1. Brief Methods paragraph (measurement + validation)

> **Plaque size measurement.** Plaque size was measured with Plaque Toolkit (v1.0.2), a desktop
> application built on the adaptive‑local plaque‑detection algorithm of the peer‑reviewed Plaque
> Size Tool (Trofimova & Jaschke, 2021). Each image was calibrated to millimetres from the
> `[85‑mm Petri‑dish rim / an in‑frame ruler]`. Plaques were detected with the toolkit's **Precise
> engine** — an in‑house extension that fuses the Plaque Size Tool geometry with a PlaqSeg
> deep‑learning (YOLO‑segmentation) detector and an optional plaque‑versus‑texture classifier — and
> every plate was then visually inspected, with missed or merged plaques corrected manually and
> touching/overlapping plaques excluded from size analysis. For each plaque the software reports the
> area and the area‑equivalent diameter, *d* = 2·√(*A*/π).
>
> **Local validation of the Precise engine.** Because the Precise engine is an in‑house extension
> rather than an independently peer‑reviewed method, we validated it locally against manual
> measurement: `[N]` plates (100 plaques total) were traced independently in Fiji/ImageJ
> (Schindelin et al., 2012), blind to the software's boundaries, on the same calibrated images.
> Plaque Toolkit agreed closely with the manual traces (Pearson *r* = 0.98; intraclass correlation
> coefficient ICC(A,1) = 0.97; Bland–Altman mean bias −0.03 mm, ≈ 1.8%, 95% limits of agreement
> −0.15 to +0.09 mm) with no proportional bias (regression of the difference on the mean: slope
> = +0.006, *p* = 0.78).

## 2. Compact one‑sentence version (if space is tight)

> Plaques were measured with Plaque Toolkit (v1.0.2; built on the Plaque Size Tool of Trofimova &
> Jaschke, 2021) using its in‑house Precise engine (Plaque Size Tool geometry fused with a PlaqSeg
> YOLO‑segmentation detector), with manual verification of every plate and size reported as the
> area‑equivalent diameter *d* = 2·√(*A*/π); as an in‑house extension, Precise was validated locally
> against independent Fiji/ImageJ tracing of 100 plaques (ICC = 0.97, *r* = 0.98; mean bias −1.8%,
> 95% limits of agreement −0.15 to +0.09 mm; no proportional bias).

**Reporting notes:** state "100 plaques from `[N]` plates" (the plate is the experimental unit);
cite the **Published** engine as the peer‑reviewed method and describe **Precise** explicitly as an
in‑house extension validated by your own comparison above. If you also report **counts/titre**,
validate those separately and note the negative‑control false‑positive floor (Precise ≈ 3 per blank
plate on this imaging setup).

---

## 3. Use‑of‑AI statement (software development)

> **Software development and use of AI.** The Plaque Toolkit application was developed by the authors
> with the assistance of an AI coding assistant (Anthropic Claude, used through the Claude Code
> command‑line tool). AI assistance was used to write and document the application's code — the
> graphical user interface, the packaging, the accompanying statistical/plotting utilities, and the
> integration ("Precise") pipeline that combines the published Plaque Size Tool with the PlaqSeg
> segmentation model. The underlying validated detection algorithm is the peer‑reviewed Plaque Size
> Tool (Trofimova & Jaschke, 2021) and the deep‑learning detector is PlaqSeg; neither was generated
> by AI. The authors defined all requirements, made all scientific and methodological decisions, and
> reviewed, tested, and validated the software's outputs against independent manual measurements (see
> Validation). AI was not used to generate, analyse, or interpret the experimental data, and
> `[was not used / was used only for language editing]` in the preparation of this manuscript. No AI
> system is listed as an author; the authors take full responsibility for the software and for all
> results reported here.

### Shorter version (for an Acknowledgements or Code‑availability line)

> The Plaque Toolkit software was written by the authors with the help of an AI coding assistant
> (Anthropic Claude / Claude Code); the peer‑reviewed Plaque Size Tool algorithm (Trofimova &
> Jaschke, 2021) and the PlaqSeg detector were not AI‑generated. All requirements, scientific
> decisions, testing, and validation were performed by the authors, who take full responsibility for
> the software and results. `[AI was/was not used in preparing the manuscript text.]`

**Why this wording is safe:** it discloses the AI tool by name (what most journals/ICMJE now ask),
separates AI‑assisted *code* from the *validated algorithm* and *the data* (AI touched neither),
keeps a human author responsible, and does not list AI as an author — consistent with ICMJE and COPE
guidance. Check your target journal's specific "use of AI/AI‑assisted technologies" policy for the
exact section it wants this in (often Methods, Acknowledgements, or a dedicated declaration).

---

## References
- Trofimova E. & Jaschke P.R. (2021). *Plaque Size Tool.* Virology 561:1–5. doi:10.1016/j.virol.2021.05.011
- Schindelin J. et al. (2012). *Fiji.* Nat. Methods 9:676–682. doi:10.1038/nmeth.2019
- Bland J.M. & Altman D.G. (1986). *Statistical methods for assessing agreement…* Lancet 327:307–310.
- Koo T.K. & Li M.Y. (2016). *A guideline of selecting and reporting ICC…* J. Chiropr. Med. 15:155–163.
