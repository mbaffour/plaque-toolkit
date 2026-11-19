"""
Reusable physical scale-bar overlay for annotated plate images.

``draw_scale_bar`` stamps a "5 mm"-style bar onto a BGR image (in place / returned). It is
pure cv2 + numpy so it adds no new dependencies and can be reused by the GUI editor saves,
the desktop app, ``measure_samples.py``, the ``precise`` pipeline, or a standalone CLI.
``bar_geometry`` is the one function that decides where the bar goes and what it says; the
desktop app's on-screen canvas calls it too, so the bar on screen is the bar in the file.

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


def bar_geometry(image_shape, mm_per_px, corner="br", target_frac=0.18, pad=None,
                 anchor=None, length_mm=None, plate=None):
    """Where the scale bar goes and what it says -- the ONE place that decides it.

    ``draw_scale_bar`` (every exported image) and the desktop app's on-screen canvas both
    call this, so the bar a user sees while editing is the bar that lands in the file: same
    length, same label, same clamped position (CT-R1 F19: the canvas used to let a 100 mm
    bar run off the image while the export shortened and moved it).

    Returns ``None`` for an image too small to carry a bar, else a dict:

    ``x0, y0``       left end / top edge of the bar (image px), already clamped inside the image
    ``length_px``    bar length actually drawn
    ``thickness``    bar height; ``outline`` the dark border width
    ``label``        e.g. ``"5 mm"`` (or ``"200 px"`` when there is no calibration)
    ``value, unit``  the number and unit in the label
    ``requested``    the length the caller asked for (``length_mm``) or ``None`` for auto
    ``shortened``    True when the bar did not fit and a shorter nice length is drawn
    ``label_cx``     x of the label's centre (the label is centred over the bar)
    ``label_above``  True when the label sits above the bar (always, except a top corner)
    ``label_w, label_h, label_base, gap``  the room reserved for the label (cv2 Hershey
                     metrics at ``font_scale`` / ``font_thick``)
    ``pad``          the margin kept from the image edge
    """
    h, w = int(image_shape[0]), int(image_shape[1])
    if h < 4 or w < 4:
        return None
    target_px = max(1.0, float(target_frac) * w)
    calibrated = bool(mm_per_px) and float(mm_per_px) > 0
    requested = float(length_mm) if (calibrated and length_mm and float(length_mm) > 0) else None

    # ---- choose a nice bar length + build its label ----
    if calibrated:
        mm_per_px = float(mm_per_px)
        # caller chose the bar length, or auto: nearest nice round length
        value = requested if requested else _pick_nice(NICE_MM, target_px * mm_per_px)
        bar_len_px = value / mm_per_px
        unit = "mm"
    else:
        # No calibration: fall back to a pixel-length bar.
        value = _pick_nice(NICE_PX, target_px)
        bar_len_px = float(value)
        unit = "px"

    bar_len_px = int(round(bar_len_px))
    if bar_len_px < 1:
        return None
    # Never let the bar overrun the image -- and if it had to be shortened, re-derive
    # the label from the length actually drawn. The clamp used to keep the caller's
    # label, so a 500 px image could carry a 451 px bar labelled "50 mm" (AUDIT-2026-10.md).
    shortened = False
    max_px = int(w * 0.9)
    if bar_len_px > max_px:
        shortened = True
        if calibrated:
            fits = [m for m in NICE_MM if m / mm_per_px <= max_px]
            value = max(fits) if fits else round(max_px * mm_per_px, 2)
            bar_len_px = int(round(value / mm_per_px))
        else:
            fits = [p for p in NICE_PX if p <= max_px]
            value = max(fits) if fits else max_px
            bar_len_px = int(value)
    label = ("%g mm" % value) if calibrated else ("%d px" % int(value))

    # ---- size everything to the image so it reads on big photos ----
    if pad is None:
        pad = max(8, int(round(0.03 * w)))
    bar_thick = max(2, int(round(h / 220.0)))        # bar height
    outline = max(1, int(round(bar_thick / 3.0)))    # dark border width
    font_scale = max(0.5, w / 1600.0)                # readable on 3-4k px plates
    font_thick = max(1, int(round(font_scale * 2)))
    (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thick)
    gap = max(4, int(round(0.4 * th)))               # space between label and bar

    # ---- placement: explicit anchor, the dish (lower centre of the lawn), or a corner ----
    if anchor is None and plate and plate.get("center") is not None and plate.get("radius"):
        # INSIDE the dish: an image corner falls in the dark surround of a plate photo.
        pcx, pcy = plate["center"]
        anchor = (float(pcx) - bar_len_px / 2.0, float(pcy) + 0.80 * float(plate["radius"]))
    if anchor is not None:
        # anchor = (x, y) of the bar's LEFT end
        x1 = int(round(anchor[0]))
        x1 = max(pad, min(x1, w - pad - bar_len_px))
        y_bar = int(round(anchor[1]))
        y_bar = max(th + base + gap + 2, min(y_bar, h - bar_thick - pad))
        above = True                # label sits ABOVE the bar
    else:
        c = (corner or "br").lower()
        right = "r" in c
        above = "b" in c if ("b" in c or "t" in c) else True
        x1 = (w - pad - bar_len_px) if right else pad
        if above:
            y_bar = h - pad - bar_thick     # bar near bottom edge; label above
        else:
            y_bar = pad + th + base + gap   # top corner; room for label above
    return {"x0": int(x1), "y0": int(y_bar), "length_px": int(bar_len_px),
            "thickness": int(bar_thick), "outline": int(outline), "label": label,
            "value": value, "unit": unit, "requested": requested, "shortened": shortened,
            "label_cx": x1 + bar_len_px / 2.0, "label_above": bool(above),
            "label_w": int(tw), "label_h": int(th), "label_base": int(base), "gap": int(gap),
            "font_scale": float(font_scale), "font_thick": int(font_thick), "pad": int(pad)}


def draw_scale_bar(img_bgr, mm_per_px, corner="br", target_frac=0.18,
                   color=(255, 255, 255), pad=None, anchor=None, length_mm=None, plate=None,
                   draw_label=True):
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
    anchor, length_mm, plate :
        Explicit left end of the bar / forced length / the detected dish (the bar then
        goes on the lawn, lower centre). :func:`bar_geometry` decides all of it.
    draw_label : bool
        False draws the bar only (the caller writes the label in its own font).

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

        g = bar_geometry((h, w), mm_per_px, corner=corner, target_frac=target_frac, pad=pad,
                         anchor=anchor, length_mm=length_mm, plate=plate)
        if g is None:
            return img_bgr
        x1, y_bar_top = g["x0"], g["y0"]
        x2 = x1 + g["length_px"]
        y_bar_bot = y_bar_top + g["thickness"]
        outline = g["outline"]

        # ---- draw the bar (dark outline first, then the coloured fill) ----
        dark = (0, 0, 0)
        cv2.rectangle(img_bgr,
                      (x1 - outline, y_bar_top - outline),
                      (x2 + outline, y_bar_bot + outline),
                      dark, -1, lineType=cv2.LINE_AA)
        cv2.rectangle(img_bgr,
                      (x1, y_bar_top), (x2, y_bar_bot),
                      tuple(int(v) for v in color), -1, lineType=cv2.LINE_AA)
        if not draw_label:
            return img_bgr

        # ---- label, centred over the bar ----
        font = cv2.FONT_HERSHEY_SIMPLEX
        tw, th, gap = g["label_w"], g["label_h"], g["gap"]
        tx = int(round(x1 + (g["length_px"] - tw) / 2.0))
        tx = max(2, min(tx, w - tw - 2))                 # keep it on-canvas
        ty = (y_bar_top - gap) if g["label_above"] else (y_bar_bot + gap + th)
        ty = max(th + 2, min(ty, h - 2))

        # outline pass (dark) for contrast, then the coloured text on top.
        cv2.putText(img_bgr, g["label"], (tx, ty), font, g["font_scale"], dark,
                    g["font_thick"] + 2, cv2.LINE_AA)
        cv2.putText(img_bgr, g["label"], (tx, ty), font, g["font_scale"],
                    tuple(int(v) for v in color), g["font_thick"], cv2.LINE_AA)

        return img_bgr
    except Exception:
        # Overlay must never break a save.
        return img_bgr
