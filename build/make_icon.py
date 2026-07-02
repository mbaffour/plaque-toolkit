"""Generate the app icon + splash for "Plaque Toolkit" (nickname: Frankenstein's Plaque Lab).

Draws everything with Pillow (already a dependency) so the brand assets are reproducible and
need no external editor. Motif: a green agar petri dish with pale plaque clearings, crossed by a
bold "Frankenstein" suture (a stitched scar) — the tool is stitched together from several parts.

Run:  python build/make_icon.py
Writes: app/resources/icon.png (512), icon.ico (multi-res), splash.png
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "app", "resources")

# palette (matches app/style.py LIGHT)
SLATE = (31, 39, 51, 255)       # background
AGAR = (33, 158, 94, 255)       # dish green
AGAR_RIM = (22, 120, 70, 255)
LID = (203, 213, 225, 255)      # light lid ring
CLEAR = (233, 255, 242, 255)    # plaque clearing
CLEAR_RIM = (176, 224, 197, 255)
STITCH = (18, 26, 36, 255)      # suture (near-black)
ACCENT = (37, 99, 235, 255)     # indigo
MUTED = (107, 116, 132, 255)
INK = (31, 39, 51, 255)

SS = 2048   # supersample, then downscale for smooth edges


def _font(names, size):
    for n in names:
        for path in (n, os.path.join("C:/Windows/Fonts", n)):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_icon():
    img = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(SS * 0.055)
    d.rounded_rectangle([pad, pad, SS - pad, SS - pad], radius=int(SS * 0.185), fill=SLATE)

    cx = cy = SS // 2
    R_lid = int(SS * 0.405)
    d.ellipse([cx - R_lid, cy - R_lid, cx + R_lid, cy + R_lid],
              outline=LID, width=int(SS * 0.014))
    R = int(SS * 0.355)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=AGAR)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=AGAR_RIM, width=int(SS * 0.022))

    # plaque clearings scattered on the agar (fractions of R from centre)
    plaques = [(-0.46, -0.34, 0.11), (0.34, -0.40, 0.075), (0.44, 0.16, 0.095),
               (-0.32, 0.42, 0.085), (0.06, 0.34, 0.06), (-0.52, 0.08, 0.055),
               (0.24, 0.50, 0.05), (-0.06, -0.52, 0.05)]
    for fx, fy, fr in plaques:
        px, py, pr = cx + int(fx * R), cy + int(fy * R), int(fr * R)
        if math.hypot(px - cx, py - cy) + pr < R * 0.97:
            d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=CLEAR,
                      outline=CLEAR_RIM, width=max(2, int(SS * 0.004)))

    # Frankenstein suture: a slightly slanted line down the dish with perpendicular stitch ticks
    lx0, ly0 = cx - int(R * 0.16), cy - int(R * 0.74)
    lx1, ly1 = cx + int(R * 0.12), cy + int(R * 0.74)
    d.line([lx0, ly0, lx1, ly1], fill=STITCH, width=int(SS * 0.015))
    dx, dy = lx1 - lx0, ly1 - ly0
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    pxu, pyu = -uy, ux
    n = 6
    tick = int(R * 0.17)
    for k in range(n):
        t = (k + 0.5) / n
        mx, my = lx0 + dx * t, ly0 + dy * t
        d.line([mx - pxu * tick, my - pyu * tick, mx + pxu * tick, my + pyu * tick],
               fill=STITCH, width=int(SS * 0.011))

    return img.resize((512, 512), Image.LANCZOS)


def make_splash(icon512):
    W, H = 760, 420
    s = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(s)
    d.rectangle([0, 0, W, 8], fill=ACCENT)                     # top accent bar
    ic = icon512.resize((196, 196), Image.LANCZOS)
    s.alpha_composite(ic, (48, (H - 196) // 2))

    big = _font(["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"], 58)
    nick = _font(["segoeuii.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"], 27)
    small = _font(["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"], 21)

    tx = 288
    d.text((tx, 116), "Plaque Toolkit", font=big, fill=INK)
    d.text((tx, 190), "“Frankenstein’s Plaque Lab”", font=nick, fill=MUTED)
    d.text((tx, 238), "Measure plaque size & turbidity", font=small, fill=MUTED)
    d.text((tx, 268), "Built on the validated Plaque Size Tool", font=small, fill=MUTED)
    return s


def main():
    os.makedirs(RES, exist_ok=True)
    icon = make_icon()
    icon.save(os.path.join(RES, "icon.png"))
    icon.save(os.path.join(RES, "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    make_splash(icon).save(os.path.join(RES, "splash.png"))
    print("wrote icon.png (512), icon.ico (multi-res), splash.png ->", os.path.abspath(RES))


if __name__ == "__main__":
    main()
