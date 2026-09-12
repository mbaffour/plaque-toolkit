# Published vs `--upstream-exact`: exactly how they differ

**Short version.** The **Published** engine reproduces the Trofimova & Jaschke (2021)
*measurement* algorithm exactly. It does **not** reproduce upstream's *image-reading* code.
On neutral-grey TIFF/PNG plates — which is every plate bundled with this toolkit, and every
plate the Fiji validation used — the two are byte-identical. On **colour-cast** plates (warm
agar under tungsten light; a top-lit iPhone photo of amber agar) and on **JPEG** input they
are not, and individual diameters can differ by up to **0.5 mm**.

If you need to reproduce a number that the *original upstream tool itself* produced, use the
new opt-in flag:

```
python plaque_size_tool.py -i plate.tif -p 90 --upstream-exact
```

`--upstream-exact` implies `--published`. It is CLI-only (the desktop app and
`plaque_turbidity.py` do not expose it).

---

## The three deviations

Upstream's read block is:

```python
image_brightness = get_brightness(image_path)   # PIL ImageStat.Stat(im).mean[0]
im = Image.open(image_path)
image = cv2.imread(image_path)                  # no EXIF transpose
if image_brightness > 70:
    im_output = ImageEnhance.Brightness(im).enhance(0.5)
    im_output.save(image_path + '.tmp' + ext)   # re-encode through a temp file
    image = cv2.imread(image_path + '.tmp' + ext)
```

The toolkit's default read path deliberately changes three things:

| # | Upstream | Toolkit default (Published & Current) | When it matters |
|---|---|---|---|
| 1 | **Brightness = mean of the RED channel.** `get_brightness()` calls `im.convert('L')` but discards the result, so `ImageStat.Stat(im).mean[0]` is the red-channel mean, not luma. This is an upstream bug. | **Brightness = BT.601 luma** (`cv2.cvtColor(..., BGR2GRAY).mean()`). | Only on **colour-cast** images. On a neutral plate the two are equal; on a warm amber plate we measured **58.03 (luma) vs 83.62 (red)** — which straddles the `> 70` dimming threshold, so one run dims the image and the other does not. |
| 2 | **Lossy temp-file round trip** when dimming: the 0.5× image is written next to the input and re-read. | **Dimming applied in memory**, no temp file. | Only for **lossy formats (JPEG/HEIC)**, where the re-encode changes pixel values before the adaptive threshold. Also means upstream needs a writable input folder and can leave `.tmp` files behind. |
| 3 | **No EXIF transpose.** | **EXIF orientation honoured** for `.jpg/.jpeg/.heic/.heif`. | Phone photos. Upstream analyses a sideways image; the toolkit rotates it upright first. Upstream also cannot open HEIC at all. |

`--upstream-exact` restores all three. Its only concession to not crashing is `_ensure_bgr()`
(grayscale / BGRA inputs are converted to 3-channel BGR instead of raising an OpenCV
"bad number of channels" error); for the 3-channel colour images upstream could actually
handle, that is a no-op. HEIC input raises a clear error rather than silently taking a
fallback path upstream never had.

---

## Measured divergence

Reproduced on this repository (`-p 90`, plaques matched by centre within 5 px). The read path
of `--upstream-exact` was verified byte-identical to upstream's on all three inputs.

| Case | brightness: default (luma) / upstream (red) | count Published / upstream-exact | matched | mean \|Δdiameter\| | max \|Δdiameter\| |
|---|---|---|---|---|---|
| `Test_plates/large/Plate_2.tif` — bundled, neutral-grey RGB TIFF | 48.99 / 48.99 | 19 / 19 | 19 | **0.000 mm** | **0.000 mm** |
| Same plate with a warm amber cast (PNG) | 58.03 / **83.62** | 19 / 19 | 17 of 19 | 0.212 mm | **0.500 mm** |
| Bright JPEG (both above the 70 gate) | 76.91 / 76.91 | 20 / 20 | 18 of 20 | 0.008 mm | 0.030 mm |

Two points worth stating plainly:

- The 0.5 mm figure is an order of magnitude larger than the "≤ ~0.04 mm" the README quotes
  for **Current vs Published**. That ≤0.04 mm figure is a *different* comparison and remains
  correct on the bundled neutral plates.
- The colour-cast case is the toolkit's own advertised use case (a top-lit phone photo of
  amber agar). If your plates look warm or you shoot JPEG, Published and the original upstream
  tool will not give you the same millimetres.

Regression-tested in `tests/test_upstream_exact.py`: the two modes must stay identical on a
synthetic neutral-grey TIFF, and the brightness statistics must diverge on a colour-cast image.

---

## Which should I use?

| You want | Use |
|---|---|
| A number for a paper, measured with the peer-reviewed *algorithm* | `--published` (the citable mode; say so in Methods) |
| To reproduce a number the **original upstream tool** produced, on a colour or JPEG plate | `--upstream-exact` |
| Routine measuring | the default (Current) |

Whichever you use, the engine, its settings and the toolkit version are now written into a
`run_metadata.json` beside every CSV, so a result can always be traced back to the code that
produced it.

## Open decision for the maintainer

Whether `--published` should *become* `--upstream-exact` by default is deliberately **not**
decided here, because flipping it would change every previously published number on a colour
or JPEG plate. See `AUDIT-2026-09.md` → "Owner decisions".
