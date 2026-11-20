"""FROZEN perturbations of the bundled plates (the round-2 tester's b_perturb.py, verbatim).

``perturb(name, img)`` returns (perturbed BGR image, forward map (x, y) -> (x', y') of a
centre in the original image). PERTURB_PLATES are the six plates the tester perturbed.
"""
import cv2
import numpy as np

PERTURB_PLATES = ["sample/sample", "large/Plate_6", "large/Plate_2", "large/Plate_8",
                  "large/Plate_3", "small/Plate_15"]
PERTS = ["rot90", "rot180", "flipH", "gain+10", "gain-10", "gain+1", "gain-1", "blur1", "jpeg85",
         "x0.5", "x2", "crop3", "border10"]


def perturb(name, img):
    H, W = img.shape[:2]
    ident = lambda x, y: (x, y)  # noqa: E731
    if name == "rot90":   # clockwise
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), lambda x, y: (H - 1 - y, x)
    if name == "rot180":
        return cv2.rotate(img, cv2.ROTATE_180), lambda x, y: (W - 1 - x, H - 1 - y)
    if name == "flipH":
        return cv2.flip(img, 1), lambda x, y: (W - 1 - x, y)
    if name.startswith("gain"):
        g = 1 + float(name[4:]) / 100
        return np.clip(img.astype(np.float32) * g + 0.5, 0, 255).astype(np.uint8), ident
    if name == "blur1":
        return cv2.GaussianBlur(img, (0, 0), 1.0), ident
    if name == "jpeg85":
        ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return cv2.imdecode(b, cv2.IMREAD_COLOR), ident
    if name.startswith("x"):
        f = float(name[1:])
        return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC), \
            lambda x, y: ((x + 0.5) * f - 0.5, (y + 0.5) * f - 0.5)
    if name == "crop3":
        dx, dy = int(0.03 * W), int(0.03 * H)
        return img[dy:H - dy, dx:W - dx].copy(), lambda x, y: (x - dx, y - dy)
    if name == "border10":
        dx, dy = int(0.10 * W), int(0.10 * H)
        return cv2.copyMakeBorder(img, dy, dy, dx, dx, cv2.BORDER_CONSTANT, value=(0, 0, 0)), lambda x, y: (x + dx, y + dy)
    raise ValueError(name)


def scale_factor(name):
    """The tester's matching-tolerance factor for a perturbation (resizing changes radii)."""
    return 0.5 if name == "x0.5" else 2.0 if name == "x2" else 1.0
