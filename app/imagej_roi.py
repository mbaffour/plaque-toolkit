"""app/imagej_roi.py — write ImageJ / Fiji ``.roi`` files and a ``RoiSet.zip`` (dependency-free).

Encodes the small subset of the (undocumented) ImageJ ROI binary format we need — oval and
polygon regions — so the app's detected plaques can be opened directly in Fiji's **ROI Manager**
in the SAME order and numbering as the app (ROI #k == plaque #k). Big-endian, mirroring
``ij.io.RoiEncoder``. Validated against the ``roifile`` reference decoder in the test-suite.

Only the writer is implemented; reading ROIs is not needed here.
"""
import struct
import zipfile

_MAGIC = b"Iout"
_VERSION = 227
_TYPE_POLYGON = 0
_TYPE_OVAL = 2
_HEADER = 64


def _header(roi_type, top, left, bottom, right, n_coords):
    b = bytearray(_HEADER)
    b[0:4] = _MAGIC
    struct.pack_into(">h", b, 4, _VERSION)
    b[6] = roi_type & 0xFF
    b[7] = 0
    struct.pack_into(">h", b, 8, int(round(top)))
    struct.pack_into(">h", b, 10, int(round(left)))
    struct.pack_into(">h", b, 12, int(round(bottom)))
    struct.pack_into(">h", b, 14, int(round(right)))
    struct.pack_into(">H", b, 16, int(n_coords))
    # bytes 18..63 (x1..y2 floats, stroke/fill colours, subtype, options, header2 offset)
    # stay zero — that is a plain, integer-resolution ROI with no styling.
    return b


def oval_roi(left, top, width, height):
    """An oval ROI from its bounding box (pixels, in the target image's frame)."""
    left = int(round(left)); top = int(round(top))
    right = left + int(round(width)); bottom = top + int(round(height))
    return bytes(_header(_TYPE_OVAL, top, left, bottom, right, 0))


def polygon_roi(xs, ys):
    """A polygon ROI from absolute integer pixel coordinates (in the target image's frame)."""
    xi = [int(round(x)) for x in xs]
    yi = [int(round(y)) for y in ys]
    if len(xi) < 2 or len(xi) != len(yi):
        raise ValueError("polygon_roi needs matching x/y lists of length >= 2")
    left, top, right, bottom = min(xi), min(yi), max(xi), max(yi)
    b = _header(_TYPE_POLYGON, top, left, bottom, right, len(xi))
    coords = bytearray()
    for x in xi:                       # ImageJ stores coords relative to the bounding rect
        coords += struct.pack(">h", x - left)
    for y in yi:
        coords += struct.pack(">h", y - top)
    return bytes(b) + bytes(coords)


def write_roiset(rois, zip_path):
    """Write ``rois`` (a list of ``(name, roi_bytes)``) to a ROI-Manager-readable ``RoiSet.zip``.

    Entries are stored in the given order; use zero-padded names (``0001`` …) so the ROI
    Manager lists them in the same order as the app's plaque numbering."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in rois:
            fn = name if name.endswith(".roi") else name + ".roi"
            z.writestr(fn, data)
    return zip_path
