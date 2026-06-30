"""
Reusable physical scale-bar overlay for annotated plate images.

A single function, ``draw_scale_bar``, stamps a "5 mm"-style bar onto a BGR image
(in place / returned). It is pure cv2 + numpy so it adds no new dependencies and can
be reused by the GUI editor saves, the desktop app, ``measure_samples.py``, the
``precise`` pipeline, or a standalone CLI.

The calibration these tools pass around is millimetres-per-pixel. NOTE: in
``plaque_gui.py`` the variable is *named* ``pxl_per_mm`` but actually holds mm/px,
so it can be passed straight to ``mm_per_px`` here.

Design goals:
  * Pick a NICE round length in mm so the bar is roughly ``target_frac`` of the image
    width (e.g. 0.5, 1, 2, 5, 10, 20, 50, 100 mm).
  * Draw a filled bar with a thin dark outline so it reads on light AND dark plates.
  * Centred label ("5 mm") above the bar, font + thickness scaled to the image so it
    stays legible on ~3000-4000 px plate photos.
  * Never crash: if mm/px is missing, fall back to a pixel-length bar; if anything
    else goes wrong, return the image unchanged.
"""

import cv2
import numpy as np

# Nice round bar lengths (mm) to choose from.
NICE_MM = [0.5, 1, 2, 5, 10, 20, 50, 100]
# Nice round bar lengths (px) for the no-calibration fallback.
NICE_PX = [10, 20, 50, 100, 200, 500, 1000, 2000]


def _pick_nice(values, target):
    """Return the entry in ``values`` whose distance to ``target`` is smallest.

    Ties / out-of-range targets clamp to the nearest end of the list, so a tiny or
    huge dish never produces a degenerate bar.
    """
    if target <= 0:
        return values[0]
    return min(values, key=lambda v: abs(v - target))


def draw_scale_bar(img_bgr, mm_per_px, corner="br", target_frac=0.18,
                   color=(255, 255, 255), pad=None, anchor=None, length_mm=None):
    """Stamp a physical scale bar onto ``img_bgr`` (modified in place) and return it.

    Parameters
    ----------
    img_bgr : np.ndarray
        BGR image (H, W, 3) or grayscale (H, W). Modified in place.
    mm_per_px : float or None
        Millimetres per pixel (the calibration these tools compute). If falsy/None,
        a pixel-length bar (labelled in px) is drawn instead.
    corner : str
        One of "br", "bl", "tr", "tl" (bottom/top + right/left). Default bottom-right.
    target_frac : float
        Desired bar length as a fraction of image width. The nearest nice round
        length is chosen. Default 0.18.
    color : tuple
        BGR fill colour of the bar / text. A dark outline is always added so it is
        legible on either background.
    pad : int or None
        Margin (px) from the image edge. Defaults to ~3% of the image width.

    Returns
    -------
    np.ndarray
        The same image, with the scale bar drawn. On any error the image is returned
        unmodified so a save can never be broken by the overlay.
    """
    try:
        if img_bgr is None or not hasattr(img_bgr, "shape"):
            return img_bgr
        h, w = img_bgr.shape[:2]
        if h < 4 or w < 4:
            return img_bgr

        # Ensure we can draw colour even on a grayscale array.
        if img_bgr.ndim == 2:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)

        target_px = max(1.0, float(target_frac) * w)

        # ---- choose a nice bar length + build its label ----
        if mm_per_px and float(mm_per_px) > 0:
            mm_per_px = float(mm_per_px)
            if length_mm and float(length_mm) > 0:        # caller chose the bar length
                nice_mm = float(length_mm)
            else:                                          # auto: nearest nice round length
                target_mm = target_px * mm_per_px
                nice_mm = _pick_nice(NICE_MM, target_mm)
            bar_len_px = nice_mm / mm_per_px
            label = ("%g mm" % nice_mm)
        else:
            # No calibration: fall back to a pixel-length bar.
            nice_px = _pick_nice(NICE_PX, target_px)
            bar_len_px = float(nice_px)
            label = ("%d px" % int(nice_px))

        bar_len_px = int(round(bar_len_px))
        if bar_len_px < 1:
            return img_bgr
        # Never let the bar overrun the image.
        bar_len_px = min(bar_len_px, int(w * 0.9))

        # ---- size everything to the image so it reads on big photos ----
        if pad is None:
            pad = max(8, int(round(0.03 * w)))
        bar_thick = max(2, int(round(h / 220.0)))        # bar height
        outline = max(1, int(round(bar_thick / 3.0)))    # dark border width
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.5, w / 1600.0)                # readable on 3-4k px plates
        font_thick = max(1, int(round(font_scale * 2)))

        (tw, th), base = cv2.getTextSize(label, font, font_scale, font_thick)
        gap = max(4, int(round(0.4 * th)))               # space between label and bar

        # ---- placement: explicit anchor (e.g. INSIDE the dish) or an image corner ----
        if anchor is not None:
            # anchor = (x, y) of the bar's LEFT end; used to place the bar on the lawn
            # instead of an image corner (which falls in the dark surround for plate photos).
            x1 = int(round(anchor[0]))
            x1 = max(pad, min(x1, w - pad - bar_len_px))
            y_bar = int(round(anchor[1]))
            y_bar = max(th + base + gap + 2, min(y_bar, h - bar_thick - pad))
            bottom = True               # label sits ABOVE the bar
        else:
            c = (corner or "br").lower()
            right = "r" in c
            bottom = "b" in c if ("b" in c or "t" in c) else True
            x1 = (w - pad - bar_len_px) if right else pad
            if bottom:
                y_bar = h - pad - bar_thick     # bar near bottom edge; label above
            else:
                y_bar = pad + th + base + gap   # top corner; room for label above
        x2 = x1 + bar_len_px
        y_bar_top = y_bar
        y_bar_bot = y_bar + bar_thick

        # ---- draw the bar (dark outline first, then the coloured fill) ----
        dark = (0, 0, 0)
        cv2.rectangle(img_bgr,
                      (x1 - outline, y_bar_top - outline),
                      (x2 + outline, y_bar_bot + outline),
                      dark, -1, lineType=cv2.LINE_AA)
        cv2.rectangle(img_bgr,
                      (x1, y_bar_top), (x2, y_bar_bot),
                      tuple(int(v) for v in color), -1, lineType=cv2.LINE_AA)

        # ---- label, centred over the bar ----
        tx = int(round(x1 + (bar_len_px - tw) / 2.0))
        tx = max(2, min(tx, w - tw - 2))                 # keep it on-canvas
        ty = (y_bar_top - gap) if bottom else (y_bar_bot + gap + th)
        ty = max(th + 2, min(ty, h - 2))

        # outline pass (dark) for contrast, then the coloured text on top.
        cv2.putText(img_bgr, label, (tx, ty), font, font_scale, dark,
                    font_thick + 2, cv2.LINE_AA)
        cv2.putText(img_bgr, label, (tx, ty), font, font_scale,
                    tuple(int(v) for v in color), font_thick, cv2.LINE_AA)

        return img_bgr
    except Exception:
        # Overlay must never break a save.
        return img_bgr
