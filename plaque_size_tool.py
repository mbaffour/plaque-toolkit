import argparse
import imutils
import cv2
import numpy as np
import datetime
import os
import pandas as pd
from PIL import Image, ImageStat, ImageEnhance, ImageOps

# allow reading iPhone HEIC/HEIF images directly
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass


def _ensure_bgr(img):
    """Guarantee a 3-channel 8-bit BGR image. A no-op for an already-BGR uint8 image
    (so the validated pipeline is byte-identical for normal colour plates); it only
    rescues grayscale (1-ch) or BGRA (4-ch) inputs that would otherwise crash the
    downstream BGR->GRAY conversions with an OpenCV 'bad number of channels' error."""
    if img is None:
        return None
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 1:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def read_image_bgr(path):
    """Read any supported image (incl. iPhone HEIC), honouring EXIF orientation.
    Always returns a 3-channel 8-bit BGR array (see _ensure_bgr)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.heic', '.heif', '.jpg', '.jpeg'):
        im = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    img = cv2.imread(path)
    if img is not None:
        return _ensure_bgr(img)
    im = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


try:                                    # one source of truth: repo-root _version.py
    from _version import __version__
except Exception:                       # pragma: no cover - standalone/partial installs
    __version__ = "0.0.0+unknown"
try:                                    # run_metadata.json writer (PT-9); optional
    import provenance
except Exception:                       # pragma: no cover - standalone installs
    provenance = None
out_dir_path = './out'
# Output stems: normally the image's basename. When a -d batch contains two images with
# the same basename in different sub-folders, both used to be written to the same
# data-green-<stem>.csv and the first was silently lost (AUDIT-2026-10.md, PT-23). Such
# collisions are now disambiguated with the sub-folder path; see assign_output_stems().
_output_stems = {}
# One id per invocation so run_metadata.json can tell its own flushes from a previous run.
_run_id = None
small_plaques = False
debug_mode = False
# When True, reproduce the EXACT published Plaque Size Tool behaviour (for citation /
# comparison). Default False uses two small corrections: numeric (un-truncated) sizes,
# and concentric-duplicate de-dup that keeps the FIRST member of each concentric pair
# (upstream's loop drops the first-visited member and keeps the second; see
# _check_duplicate_plaques_published and AUDIT-2026-10.md, PT-24).
use_published = False
# Opt-in (--watershed): split touching/merged plaques. Never runs in published mode.
watershed_enabled = False
# Opt-in (--sensitive): lower the size gates to catch very small (<~0.4 mm) plaques.
# Detects many more on dense small-plaque plates, at the cost of more false positives.
sensitive = False
# Opt-in (--upstream-exact): reproduce the ORIGINAL upstream image-read path as well as the
# published measurement maths. --published alone keeps the toolkit's (better) read path --
# EXIF transpose, BT.601 luma brightness, in-memory dimming with no lossy temp file -- which
# is byte-identical to upstream on neutral-grey input but NOT on colour-cast or JPEG plates.
# See docs/UPSTREAM_EXACT.md and AUDIT-2026-09.md (PT-1). Implies use_published.
upstream_exact = False


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--image", required=False,
                    help="path to the input image")
    ap.add_argument("-d", "--directory", required=False,
                    help="path to the directory with input images")
    ap.add_argument("-p", "--plate_size", required=False,
                    help="plate size (mm)")
    ap.add_argument("-small", "--small_plaque", required=False,
                    help="for processing small plaques", action = "store_true")
    ap.add_argument("-published", "--published", required=False, action="store_true",
                    help="published Plaque Size Tool MEASUREMENT behaviour (2-dp string sizes, "
                         "concentric-pair de-dup that drops the first-visited member of each pair and "
                         "keeps the second, largest-contour dish). "
                         "The image is still read the modern way (EXIF-aware, HEIC-capable, "
                         "in-memory dimming); add --upstream-exact for the original read path too")
    ap.add_argument("-watershed", "--watershed", required=False, action="store_true",
                    help="opt-in: split touching/merged plaques via watershed and recover them "
                         "(adds a SOURCE column; ignored in --published mode)")
    ap.add_argument("-sensitive", "--sensitive", required=False, action="store_true",
                    help="opt-in: lower the size gates to catch very small (<~0.4 mm) plaques "
                         "(detects many more on dense plates, but more false positives; ignored in --published)")
    ap.add_argument("--upstream-exact", dest="upstream_exact", required=False, action="store_true",
                    help="bit-for-bit reproduction of the ORIGINAL upstream Plaque Size Tool, "
                         "including its image-read path: red-channel ImageStat brightness gate, "
                         "lossy temp-file re-encode when dimming, and NO EXIF transpose. Implies "
                         "--published. Use this to reproduce a number produced by the upstream "
                         "tool itself; see docs/UPSTREAM_EXACT.md. Cannot read HEIC.")
    ap.add_argument("--qc", dest="qc", required=False, action="store_true",
                    help="add QC_FLAG / QC_REASON columns (EDGE, MERGED?, TINY, OVERLAP) to every CSV; "
                         "purely additive -- no measurement changes (see plaque_qc.py)")
    ap.add_argument("-o", "--out", required=False, default=None,
                    help="output folder for the CSVs, annotated images and run_metadata.json "
                         "(default: ./out inside the current working directory)")
    ap.add_argument("--version", action="version", version="plaque-toolkit %s" % __version__)
    ap.add_argument("-debug", "--debug", required=False, action = "store_true")
    args = vars(ap.parse_args())
    if args['image'] ==  None and args['directory'] == None:
        raise Exception('Either -i or -d flags must be provided!')
    if args['plate_size'] is not None:         # '0' and '90mm' used to pass straight through
        try:
            _ps = float(args['plate_size'])
        except ValueError:
            ap.error("-p/--plate_size must be a number in millimetres, got %r" % args['plate_size'])
        if _ps <= 0:
            ap.error("-p/--plate_size must be > 0 mm (got %s); every mm column would be 0"
                     % args['plate_size'])
    return args


def debug_info(file_path, img):
    if debug_mode:
        cv2.imwrite(file_path, img)


def adjust_gamma(image, gamma=1.0):
    # build a lookup table mapping the pixel values [0, 255] to
    # their adjusted gamma values
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")

    return cv2.LUT(image, table)


def process_image(image, contrast):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    debug_info("./test_pic_grey.jpg", gray)

    # different values for different plaque sizes
    h = 6
    if small_plaques:
        h = 3
    gray = cv2.fastNlMeansDenoising(gray, h=h)
    debug_info("./test_pic_grey_thresh_denoise.jpg", gray)

    # gray = unsharp_mask(gray)
    # cv2.imwrite("./test_pic_grey_unsharp.jpg", gray)

    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    # blurred = cv2.medianBlur(gray, 9)
    debug_info("./test_pic_blur.jpg", blurred)

    # ET point where it depends on a pic
    high_contrast = cv2.convertScaleAbs(blurred, alpha=contrast, beta=0)
    debug_info("./test_pic_high.jpg", high_contrast)

    gamma_test = adjust_gamma(high_contrast, 7.1)
    debug_info("./test_pic_green_gamma_0.jpg", gamma_test)

    high_contrast = adjust_gamma(high_contrast, 1.0)
    debug_info("./test_pic_green_gamma.jpg", high_contrast)

    # binary = cv2.adaptiveThreshold(high_contrast, 500, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 55, 2)
    # binary = cv2.adaptiveThreshold(high_contrast, 500, cv2.ADAPTIVE_THRESH_GAUSSIAN_C , cv2.THRESH_BINARY, 55, 2)

    plate_only = cv2.adaptiveThreshold(high_contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 9, 1)
    # plate_only = cv2.threshold(high_contrast, 65, 255, cv2.THRESH_BINARY_INV)
    debug_info("./test_pic_plate_only.jpg", plate_only)

    # ret, thresh = cv2.threshold(high_contrast, 162, 255, cv2.THRESH_BINARY_INV)

    # ET added
    # blockSize affects large/small plaques (circles in circles)
    # change blockSize based on the AREA
    #block_size = 265
    block_size = 231
    if small_plaques:
        block_size = 49

    thresh = cv2.adaptiveThreshold(high_contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
                                   block_size, 2)
    # thresh = cv2.adaptiveThreshold(high_contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 49, 2)
    debug_info("./test_pic_grey_adapt_thresh.jpg", thresh)

    # laplacian = cv2.Laplacian(blur, -1, ksize=17, delta=-50)
    # laplacian = cv2.Laplacian(thresh, cv2.CV_64F)
    laplacian = cv2.Laplacian(thresh, cv2.CV_8UC1)
    debug_info("./test_pic_laplacian.jpg", laplacian)
    # gray_lapl = cv2.cvtColor(laplacian, cv2.COLOR_BGR2GRAY)

    # binary = cv2.threshold(laplacian, 165, 255, cv2.THRESH_BINARY)
    # binary = cv2.adaptiveThreshold(laplacian, 500, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 55, 2)
    # cv2.imwrite("./test_pic_green_laplacian_binary.jpg", binary)

    clr_high_contrast = cv2.cvtColor(high_contrast, cv2.COLOR_GRAY2BGR)
    return laplacian, high_contrast, clr_high_contrast
    # return binary, high_contrast, clr_high_contrast


def get_contours(binary_image):
    contours = cv2.findContours(binary_image, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    #contours = cv2.findContours(binary_image.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    #contours = cv2.findContours(binary_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    #contours = cv2.findContours(binary_image.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    return imutils.grab_contours(contours)


def draw_contours(image, green_df, red_df, other_df, plate_df):
    image_copy = image.copy()
    for index, green in green_df.iterrows():
        # watershed-recovered plaques in cyan, normal detections in green
        colour = (255, 255, 0) if green.get('SOURCE', 'auto') == 'watershed' else (0, 255, 0)
        draw_one_contour(image_copy, green, colour)
        if debug_mode:
            for index, red in red_df.iterrows():
                draw_one_contour(image_copy, red, (0, 0, 255))
            for index, other in other_df.iterrows():
                # draw_one_contour(image_copy, other, (200, 150, 150))
                draw_one_contour(image_copy, other, (100, 100, 100))
            for index, plate in plate_df.iterrows():
                draw_one_contour(image_copy, plate, (0, 128, 255))

    return image_copy


def draw_one_contour(image, c_df, color):
    m = cv2.moments(c_df['CONTOURS'])
    if m["m00"] != 0:
        cx = int((m["m10"] / m["m00"]))
        cy = int((m["m01"] / m["m00"]))
    else:
        cx = 0
        cy = 0

    pd.set_option('display.precision', 2)
    image_w_contours = cv2.drawContours(image, [c_df['HULL']], -1, color, 1)
    # cv2.putText(image, f"#{c_df['INDEX_COL']}:{c_df['ENCL_DIAMETER_MM']}", (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
    #             color, 1)

    if c_df['DIAMETER_MM'] == 0:
        cv2.putText(image, f"#{c_df['INDEX_COL']}:{c_df['DIAMETER_PXL']}", (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (25, 51, 0), 1)
    else:
        cv2.putText(image, f"#{c_df['INDEX_COL']}:{c_df['DIAMETER_MM']}", (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (25,51,0), 1)
    return image_w_contours


OUTPUT_DIR_NAMES = ('out', 'out_batch', 'out_turbidity', 'out_precise', 'out_precise_smoke',
                    'training_data')
OUTPUT_FILE_PREFIXES = ('out_', 'overlay_', 'precise_overlay_', 'figure_', 'plaquetk_')


def is_toolkit_output_dir(name):
    """True for folders the toolkit itself writes, so batch walkers skip them."""
    return (name in OUTPUT_DIR_NAMES or name.startswith(('out_turb_', 'out_precise_'))
            or name.endswith('_fiji'))


def is_toolkit_output_file(name, folder=None):
    """True for images the toolkit itself writes next to the inputs (annotated overlays,
    figures, the Fiji plate crop that always has a .fiji.txt sibling)."""
    stem = os.path.splitext(name)[0]
    if stem.startswith(OUTPUT_FILE_PREFIXES):
        return True
    if stem.endswith('_plate') and folder and os.path.exists(os.path.join(folder, stem + '.fiji.txt')):
        return True
    return False


def get_image_paths(image, directory):
    images = []
    if image:
        images.append(image)
    else:
        exts = ('.tif', '.tiff', '.jpg', '.jpeg', '.png', '.heic', '.heif')
        skip = os.path.abspath(out_dir_path)
        skipped = []
        for r, d, f in os.walk(directory):
            # Deterministic order, and never descend into the toolkit's own output folders:
            # a second `-d .` run used to ingest out/out_<plate>.tif as a new plate.
            d[:] = sorted(x for x in d if os.path.abspath(os.path.join(r, x)) != skip
                          and not is_toolkit_output_dir(x))
            for file in sorted(f):
                if os.path.splitext(file)[1].lower() in exts:   # case-insensitive; incl. HEIC
                    if is_toolkit_output_file(file, r):
                        skipped.append(os.path.join(r, file))
                        continue
                    images.append(os.path.join(r, file))
        if skipped:
            print("NOTE: skipped %d file(s) that look like toolkit outputs (out_*, overlay_*, "
                  "figure_*, Fiji plate crops): %s" % (len(skipped), ", ".join(
                      os.path.basename(p) for p in skipped[:5]) + (" ..." if len(skipped) > 5 else "")))
    return images


def assign_output_stems(image_paths, directory=None):
    """Decide the output stem for every input image.

    The stem is the image's basename unless two inputs share one, in which case each
    colliding image gets its path relative to `directory` with separators replaced by
    `__` (so `a/Plate_2.tif` and `b/Plate_2.tif` become `a__Plate_2` and `b__Plate_2`).
    Non-colliding images keep the plain basename, so default output names are unchanged.
    """
    global _output_stems
    _output_stems = {}
    counts = {}
    for p in image_paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        counts[stem] = counts.get(stem, 0) + 1
    clashes = []
    for p in image_paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        if counts[stem] > 1:
            rel = os.path.relpath(p, directory) if directory else p
            rel = os.path.splitext(rel)[0]
            uniq = rel.replace(os.sep, '__').replace('/', '__').replace('..__', '')
            _output_stems[p] = uniq
            clashes.append((p, uniq))
    if clashes:
        print("NOTE: %d input images share a file name; their outputs are named by sub-folder "
              "so none overwrites another:" % len(clashes))
        for p, uniq in clashes:
            print("  %s -> data-green-%s.csv" % (p, uniq))
    return _output_stems


def output_stem(image_path):
    """The stem used for this image's CSV and annotated image (see assign_output_stems)."""
    return _output_stems.get(image_path) or os.path.splitext(os.path.basename(image_path))[0]


def imwrite_checked(path, img):
    """cv2.imwrite that cannot fail silently (AUDIT-2026-09.md PT-20).

    cv2.imwrite returns False -- it does not raise -- when it cannot open the path,
    which on Windows happens for any non-ASCII output path. Every caller in the
    toolkit ignored that return value and then reported the image as saved. This
    helper encodes with the same OpenCV encoder and default parameters (so the bytes
    are identical) and writes through Python's own file API, which handles any path,
    and raises if even that fails.
    """
    try:
        ok = bool(cv2.imwrite(path, img))
    except cv2.error:
        ok = False
    if ok:
        return path
    ext = os.path.splitext(path)[1] or '.png'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError("could not encode image for %s" % path)
    with open(path, 'wb') as fh:
        fh.write(buf.tobytes())
    return path


def write_images(out_dir, output_image, binary_image, high_contrast_image, image_path):
    stem = output_stem(image_path)
    ext = os.path.splitext(image_path)[1]
    if ext.lower() in ('.heic', '.heif'):   # OpenCV cannot write HEIC
        ext = '.png'
    imwrite_checked(f'{out_dir}/out_{stem}{ext}', output_image)
    # cv2.imwrite(f'{out_dir}/out_red-{os.path.split(image_path)[1]}', output_image_red)
    #cv2.imwrite(f'{out_dir}/contrast-{os.path.split(image_path)[1]}', high_contrast_image)
    #cv2.imwrite(f'{out_dir}/binary-{os.path.split(image_path)[1]}', binary_image)


def write_data(out_dir, image_path, green_df, red_df, other_df):
    write_one_data(out_dir, image_path, 'green', green_df)
    #write_one_data(out_dir, image_path, 'red', red_df)
    #write_one_data(out_dir, image_path, 'other', other_df)


MEASUREMENT_COLUMNS = ['INDEX_COL', 'AREA_PXL', 'DIAMETER_PXL', 'AREA_MM2', 'DIAMETER_MM',
                       'MEAN_GRAY', 'TURBIDITY_REL']


def write_one_data(out_dir, image_path, prefix, df):
    """Write the per-plate measurement CSV.

    ALWAYS writes the file, even for a plate with zero plaques: "0 plaques" is a real
    observation (a negative control, or a dilution that came up empty), and dropping it
    biases every mean count and titer computed downstream. The old `if df.empty != True`
    guard made such plates vanish from summarize_plates.py entirely. See PT-3.
    """
    image_name = output_stem(image_path)
    cols = list(MEASUREMENT_COLUMNS)
    if 'SOURCE' in df.columns:
        cols.append('SOURCE')
    for extra in ('QC_FLAG', 'QC_REASON'):      # opt-in (--qc); absent by default
        if extra in df.columns:
            cols.append(extra)
    out = df.copy()
    for c in cols:                      # an empty frame may never have gained a column
        if c not in out.columns:
            out[c] = []
    out.to_csv(path_or_buf=f'{out_dir}/data-{prefix}-{image_name}.csv', index=False,
               columns=cols)


def calc_AREA_PXL_diff(contour_df):
    encl_AREA_PXL = 3.1415 * (contour_df['ENCL_DIAMETER_PXL'] ** 2) / 4
    return abs(1 - contour_df['AREA_PXL'] / encl_AREA_PXL)


def prepare_df(contours):
    pd.options.display.float_format = '{:,.2f}'.format
    if len(contours) == 0:                       # blank / featureless image -> 0 plaques (no crash)
        return pd.DataFrame(columns=['CONTOURS', 'HULL', 'AREA_PXL', 'ENCL_CENTER',
                                     'ENCL_DIAMETER_PXL', 'PERIMETER_PXL'])
    contours_obj = np.empty(len(contours), dtype=object)
    for _i in range(len(contours)):
        contours_obj[_i] = contours[_i]
    df = pd.DataFrame({'CONTOURS': contours_obj})
    # df = pd.DataFrame(imutils.grab_contours(contours), columns=['CONTOURS'])
    df['HULL'] = df.apply(lambda x: cv2.convexHull(x['CONTOURS']), axis=1)
    df['AREA_PXL'] = df.apply(lambda x: cv2.contourArea(x['HULL']), axis=1)
    encl_circle = df.apply(lambda x: cv2.minEnclosingCircle(x['HULL']), axis=1)
    df['ENCL_CENTER'] = encl_circle.str[0]
    df['ENCL_DIAMETER_PXL'] = encl_circle.str[1] * 2
    df['PERIMETER_PXL'] = df.apply(lambda x: f"{cv2.arcLength(x['HULL'], True):.2f}", axis=1)

    return df


def filter_contours(contours, image_size):
    df = prepare_df(contours)
    # df = prepare_df(imutils.grab_contours(contours))

    # filter_other = df.apply(lambda x: x['AREA_PXL'] < 100 or x['AREA_PXL'] > 100000, axis=1)
    #filter_other = df.apply(lambda x: x['AREA_PXL'] < 100 or (x['AREA_PXL'] > 100 and calc_AREA_PXL_diff(x)) > 0.21, axis=1)
    #other_df = df[filter_other]
    #wo_other_df = df[~filter_other]

    plaque_minimum_size = image_size[1]/15
    # green-plaque size gates (separate vars so --sensitive doesn't disturb red/other)
    green_min_size = plaque_minimum_size
    green_diam_min = 12 if small_plaques else 30
    if sensitive:                       # catch very small plaques (more, but noisier)
        green_min_size = 25
        green_diam_min = 5
    filter_green = df.apply(lambda x: x['AREA_PXL'] < 100000 and x['AREA_PXL'] > green_min_size
                            and calc_AREA_PXL_diff(x) < 0.21 and x['ENCL_DIAMETER_PXL'] > green_diam_min, axis=1)

    #filter_green = df.apply(lambda x: x['AREA_PXL'] < 100000 and x['AREA_PXL'] > 100 and calc_AREA_PXL_diff(x) < 0.21, axis=1)
    filter_plate = df.apply(lambda x: x['AREA_PXL'] > 100000 and calc_AREA_PXL_diff(x) < 0.21, axis=1)
    filter_red = df.apply(lambda x: x['AREA_PXL'] > plaque_minimum_size and calc_AREA_PXL_diff(x) > 0.21 and x['ENCL_DIAMETER_PXL'] < 30, axis=1)
    filter_other = df.apply(lambda x: x['AREA_PXL'] < plaque_minimum_size or calc_AREA_PXL_diff(x) > 0.21, axis=1)
    #filter_other = df.apply(lambda x: calc_AREA_PXL_diff(x) > 0.23, axis=1)
    #filter_other = df.copy()
    # filter_plate = filter_plate.apply(lambda x: calc_AREA_PXL_diff(x) < 0.21, axis=1)

    green_df = df[filter_green]
    red_df = df[filter_red]
    plate_df = df[filter_plate]
    other_df = df[filter_other]


    green_df.reset_index()
    green_df = reindex(green_df)

    red_df.reset_index()
    red_df = reindex(red_df)

    other_df.reset_index()
    other_df = reindex(other_df)

    plate_df.reset_index()
    plate_df = reindex(plate_df)

    return green_df, red_df, other_df, plate_df


def reindex(df):
    dfNew = df.copy()
    dfNew['INDEX_COL'] = df.index
    return dfNew

def _check_duplicate_plaques_published(obj_df):
    # Exact upstream behaviour (verified against ellinium/plaque_size_tool). NOTE: this
    # does NOT drop both members of a concentric pair, although that is what the toolkit
    # said until 1.1.0. The loop iterates the ORIGINAL frame but tests each row against the
    # already-MUTATED frame: A sees B and is dropped; B no longer sees A and is kept. So the
    # first-visited member goes and the second survives. Current mode keeps the first.
    # On a chain A~B, B~C, A!~C only C survives here, while Current keeps A and C, so the
    # two rules can differ in COUNT on such plates (they do not on the bundled Test_plates).
    def dup(obj, df):
        for x in df.iterrows():
            if obj['INDEX_COL'] != x[0]:
                if (abs(obj['ENCL_CENTER'][0] - x[1]['ENCL_CENTER'][0]) <= 5 and
                        abs(obj['ENCL_CENTER'][1] - x[1]['ENCL_CENTER'][1]) <= 5):
                    return True
        return False
    for green in obj_df.iterrows():
        if dup(green[1], obj_df):
            obj_df = obj_df.drop(obj_df[obj_df.index == green[0]].index)
    return obj_df


def check_duplicate_plaques(obj_df):
    # De-duplicate concentric detections (circle-in-circle) by KEEPING the first of
    # each group and dropping only later near-coincident centers. The published version
    # keeps the SECOND member of a pair instead (see _check_duplicate_plaques_published),
    # so the two rules usually agree on the count but can keep a different survivor.
    if use_published:
        return _check_duplicate_plaques_published(obj_df)
    kept_centers = []
    drop_idx = []
    for idx, row in obj_df.iterrows():
        cx, cy = row['ENCL_CENTER'][0], row['ENCL_CENTER'][1]
        if any(abs(cx - kx) <= 5 and abs(cy - ky) <= 5 for kx, ky in kept_centers):
            drop_idx.append(idx)
        else:
            kept_centers.append((cx, cy))
    return obj_df.drop(drop_idx)

# Last computed pixel->mm calibration, so the provenance record can report it
# without changing any function's return type. Reset per image in main().
last_calibration = {'mm_per_px': None}


def _calculate_size_mm_published(plate_size, obj_df, plate_df):
    # exact published behaviour: values stored as 2-dp strings; DIAMETER_MM derived
    # from the truncated AREA_MM2 string; no warning if the dish isn't found.
    if obj_df.size > 0:
        obj_df['DIAMETER_PXL'] = obj_df.apply(
            lambda x: f"{np.sqrt(float(x['AREA_PXL'])/np.pi)*2:.2f}", axis=1)
    if plate_size and obj_df.size > 0:
        mpp = float(plate_size) / float(plate_df['ENCL_DIAMETER_PXL'].max())
        last_calibration['mm_per_px'] = mpp
        obj_df['ENCL_DIAMETER_MM'] = obj_df.apply(lambda x: f"{x['ENCL_DIAMETER_PXL']*mpp:.2f}", axis=1)
        obj_df['AREA_MM2'] = obj_df.apply(lambda x: f"{x['AREA_PXL']*mpp*mpp:.2f}", axis=1)
        obj_df['DIAMETER_MM'] = obj_df.apply(lambda x: f"{np.sqrt(float(x['AREA_MM2'])/np.pi)*2:.2f}", axis=1)
    else:
        obj_df['ENCL_DIAMETER_MM'] = 0
        obj_df['AREA_MM2'] = 0
        obj_df['DIAMETER_MM'] = 0
    return obj_df


def calculate_size_mm(plate_size, obj_df, plate_df):
    if use_published:
        return _calculate_size_mm_published(plate_size, obj_df.copy(), plate_df)
    # Keep every measurement NUMERIC (not formatted strings) so values aren't
    # truncated to 2 dp mid-computation and stay consistent with the GUI.
    obj_df = obj_df.copy()
    if len(obj_df) == 0:
        for col in ('DIAMETER_PXL', 'ENCL_DIAMETER_MM', 'AREA_MM2', 'DIAMETER_MM'):
            obj_df[col] = []
        return obj_df

    # area-equivalent diameter in pixels (from the true, unrounded area)
    obj_df['DIAMETER_PXL'] = obj_df['AREA_PXL'].apply(lambda a: round(float(np.sqrt(float(a) / np.pi) * 2), 2))

    max_plate_diameter = (plate_df['ENCL_DIAMETER_PXL'].max()
                          if (plate_df is not None and not plate_df.empty) else float('nan'))
    if plate_size and float(max_plate_diameter) > 0:
        mm_per_px = float(plate_size) / float(max_plate_diameter)
        last_calibration['mm_per_px'] = mm_per_px
        obj_df['ENCL_DIAMETER_MM'] = obj_df['ENCL_DIAMETER_PXL'].apply(lambda d: round(float(d) * mm_per_px, 2))
        obj_df['AREA_MM2'] = obj_df['AREA_PXL'].apply(lambda a: round(float(a) * mm_per_px * mm_per_px, 2))
        # diameter from the TRUE area (not a 2-dp-truncated AREA_MM2 string)
        obj_df['DIAMETER_MM'] = obj_df['AREA_PXL'].apply(
            lambda a: round(float(np.sqrt(float(a) * mm_per_px * mm_per_px / np.pi) * 2), 2))
    else:
        if plate_size and not last_calibration.get('warned_no_dish'):
            # calculate_size_mm runs once per contour class, so say this once per image
            last_calibration['warned_no_dish'] = True
            print("  WARNING: -p was given but no Petri dish was detected; "
                  "reporting pixels only (mm columns = 0).")
        obj_df['ENCL_DIAMETER_MM'] = 0
        obj_df['AREA_MM2'] = 0
        obj_df['DIAMETER_MM'] = 0

    return obj_df

def get_brightness(im_file):
    """UPSTREAM-EXACT brightness statistic (only used by --upstream-exact).

    This is upstream's function verbatim, quirk included: the result of
    ``im.convert('L')`` is discarded, so ``stat.mean[0]`` is the mean of the
    **red channel** of the RGB image, not the luma of a greyscale conversion.
    On a neutral-grey plate that equals BT.601 luma; on a colour-cast plate
    (warm agar, tungsten light) it does not, and the >70 dimming decision --
    and therefore every measured diameter -- can differ. Preserved deliberately
    so --upstream-exact reproduces the published tool bit for bit; the default
    Current/Published paths use ``brightness_luma()`` instead. See PT-1/PT-21.
    """
    im = Image.open(im_file)
    im.convert('L')                    # (no-op in upstream; kept for fidelity)
    stat = ImageStat.Stat(im)
    return stat.mean[0]


def brightness_luma(bgr):
    """The toolkit's brightness statistic: BT.601 luma of the whole frame.

    Unlike upstream's red-channel mean this is colour-cast-insensitive. It is
    what every mode except --upstream-exact uses."""
    return float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).mean())


def _tmp_path_for(image_path):
    """Upstream's temp-file name: '<path>.tmp<ext>' beside the input image."""
    return image_path + '.tmp' + os.path.splitext(image_path)[1]


def read_and_dim_upstream_exact(image_path):
    """UPSTREAM-EXACT read + dim: cv2.imread with NO EXIF transpose, red-channel
    brightness gate, and (when bright) PIL ImageEnhance re-encoded through a temp
    file that is then re-read -- so lossy formats lose the same information they
    lost upstream. Returns (working_image, original_image, brightness).

    Raises ValueError for inputs upstream could not read at all (e.g. HEIC), rather
    than silently falling back to a path upstream never had."""
    def _unreadable():
        return ValueError(
            "--upstream-exact cannot read %r: the original Plaque Size Tool used a bare "
            "cv2.imread() with no PIL/HEIC fallback, so this file is outside the behaviour "
            "this mode reproduces. Convert it to TIFF/PNG first (heic_to_tiff.py), or drop "
            "--upstream-exact." % os.path.basename(image_path))

    if os.path.splitext(image_path)[1].lower() in ('.heic', '.heif'):
        raise _unreadable()          # upstream had no HEIC support at all
    brightness = float(get_brightness(image_path))
    image = cv2.imread(image_path)
    if image is None:
        raise _unreadable()
    original = _ensure_bgr(image).copy()
    if brightness > 70:
        tmp = _tmp_path_for(image_path)
        try:
            im = Image.open(image_path)
            ImageEnhance.Brightness(im).enhance(0.5).save(tmp)
            dimmed = cv2.imread(tmp)
            if dimmed is not None:
                image = dimmed
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return _ensure_bgr(image), original, brightness


def read_and_dim(image_path):
    """Default read + dim: HEIC-safe, EXIF-honouring, luma brightness gate, and the
    0.5x dimming applied in memory (no lossy temp-file round trip).

    Byte-identical to upstream on neutral-grey TIFF/PNG input; see
    docs/UPSTREAM_EXACT.md for the cases where it deliberately differs.
    Returns (working_image, original_image, brightness)."""
    if upstream_exact:
        return read_and_dim_upstream_exact(image_path)
    image = read_image_bgr(image_path)
    original = image.copy()            # true (undimmed) image, used for turbidity
    brightness = brightness_luma(image)
    if brightness > 70:
        image = np.clip(image.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)
    return image, original, brightness

def _mask_from_contour(shape, contour):
    mask = np.zeros(shape[:2], dtype="uint8")
    cv2.drawContours(mask, [np.asarray(contour, dtype=np.int32)], -1, 255, -1)
    return mask


def dish_axis_ratio(plate_df):
    """Major/minor axis ratio of the detected dish rim. >1 means the dish looks elliptical
    (camera tilt / perspective foreshortening), which biases the mm calibration. None if no dish."""
    if plate_df is None or plate_df.empty:
        return None
    big = plate_df['ENCL_DIAMETER_PXL'].idxmax()
    hull = np.asarray(plate_df.loc[big, 'HULL'], dtype=np.int32)
    if len(hull) < 5:
        return None
    try:
        (_cx, _cy), (ax1, ax2), _ang = cv2.fitEllipse(hull)
    except Exception:
        return None
    lo = min(ax1, ax2)
    return (max(ax1, ax2) / lo) if lo > 0 else None


def mean_gray_in_mask(gray, mask):
    return float(cv2.mean(gray, mask)[0])


def estimate_lawn_gray(gray, dish_mask=None, exclude_masks=None):
    """Median grey of the bacterial lawn (dish interior minus plaque regions)."""
    if dish_mask is None:
        region = np.full(gray.shape[:2], 255, dtype="uint8")
    else:
        region = dish_mask.copy()
    if exclude_masks:
        for m in exclude_masks:
            region[m > 0] = 0
    vals = gray[region > 0]
    if vals.size == 0:
        vals = gray.ravel()
    return float(np.median(vals))


def turbidity_indices(mean_grays, lawn_gray):
    """0 = as clear as the clearest plaque, 1 = as opaque as the lawn.

    Uses each plaque's brightness deviation from the lawn, normalised to the most
    deviated (clearest) plaque, so it is direction-agnostic (works whether clear
    plaques read brighter or darker than the lawn) and robust to overall lighting.
    """
    devs = [abs(g - lawn_gray) for g in mean_grays]
    max_dev = max(devs) if devs else 0.0
    if max_dev <= 1e-6:
        return [0.0 for _ in mean_grays]
    return [max(0.0, min(1.0, 1.0 - d / max_dev)) for d in devs]


def add_turbidity(orig_bgr, plate_df, green_df):
    """Add MEAN_GRAY (raw 0-255, original image) and TURBIDITY_REL, a WITHIN-PLATE relative
    clarity index (0 = clearest plaque on this plate .. 1 = lawn). NOT comparable across plates
    -- for cross-phage turbidity use plaque_turbidity.py's optical-density OD instead."""
    green_df = green_df.copy()
    if green_df.empty:
        green_df['MEAN_GRAY'] = []
        green_df['TURBIDITY_REL'] = []
        return green_df
    gray = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2GRAY)
    dish_mask = None
    if plate_df is not None and not plate_df.empty:
        big = plate_df['ENCL_DIAMETER_PXL'].idxmax()
        dish_mask = _mask_from_contour(gray.shape, plate_df.loc[big, 'HULL'])
    plaque_masks = [_mask_from_contour(gray.shape, h) for h in green_df['HULL']]
    lawn = estimate_lawn_gray(gray, dish_mask, plaque_masks)
    means = [mean_gray_in_mask(gray, m) for m in plaque_masks]
    green_df['MEAN_GRAY'] = [round(v, 2) for v in means]
    green_df['TURBIDITY_REL'] = [round(v, 3) for v in turbidity_indices(means, lawn)]
    return green_df


def main():
    import warnings
    warnings.filterwarnings('ignore')
    args = parse_args()

    global out_dir_path, _run_id
    if args.get('out'):
        out_dir_path = args['out']
    _run_id = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S.%f') + '-' + str(os.getpid())
    image_paths = get_image_paths(args['image'], args['directory'])
    assign_output_stems(image_paths, args['directory'])
    plate_size = args['plate_size']

    global small_plaques
    global debug_mode
    global use_published
    global watershed_enabled
    global sensitive
    global upstream_exact
    small_plaques = args['small_plaque']
    debug_mode = args['debug']
    upstream_exact = args.get('upstream_exact', False)
    # --upstream-exact is a superset of --published: it adds the original read path on
    # top of the original measurement maths.
    use_published = args.get('published', False) or upstream_exact
    watershed_enabled = args.get('watershed', False) and not use_published
    sensitive = args.get('sensitive', False) and not use_published
    if upstream_exact:
        print("(running in --upstream-exact mode: original upstream read path -- red-channel "
              "brightness gate, lossy temp-file dimming, no EXIF transpose -- plus --published maths)")
    elif use_published:
        print("(running in --published mode: published Plaque Size Tool measurement behaviour; "
              "modernised read path -- add --upstream-exact for the original read path too)")
    if watershed_enabled:
        print("(watershed recovery ON: touching plaques will be split and recovered)")
    if sensitive:
        print("(sensitive mode ON: detecting very small plaques - expect more, and some false positives)")

    run_images = []                      # provenance rows, one per image (PT-9)
    failed = []

    def _flush_metadata():
        # Written after every image, not only at the end, so a crash mid-batch still
        # leaves a record of what was measured and with which engine (PT-25).
        if provenance is not None:
            provenance.write_metadata(
                out_dir_path, "plaque_size_tool.py",
                provenance.engine_name(published=use_published, upstream_exact=upstream_exact,
                                       sensitive=sensitive),
                {"plate_size_mm": plate_size, "small_plaque": bool(small_plaques),
                 "published": bool(use_published), "upstream_exact": bool(upstream_exact),
                 "sensitive": bool(sensitive), "watershed": bool(watershed_enabled),
                 "image": args.get('image'), "directory": args.get('directory'),
                 "out": out_dir_path},
                run_images, extra={"run_id": _run_id, "n_failed": len(failed)})

    for image_path in image_paths:
        print("Processing " + image_path)

        last_calibration['mm_per_px'] = None
        last_calibration['warned_no_dish'] = False
        try:
            _process_one(image_path, plate_size, run_images, args)
        except Exception as exc:
            # One unreadable or corrupt file used to abort the whole batch with a traceback
            # and no run_metadata.json at all (PT-25). Record it and carry on.
            failed.append(image_path)
            print("  ERROR: %s could not be processed (%s: %s); skipping it"
                  % (image_path, type(exc).__name__, exc))
            run_images.append({"file": os.path.basename(image_path), "path": image_path,
                               "error": "%s: %s" % (type(exc).__name__, exc)})
        _flush_metadata()

    if failed:
        print("\n%d of %d image(s) FAILED and have no CSV: %s" % (
            len(failed), len(image_paths), ", ".join(os.path.basename(f) for f in failed)))
        print("These are NOT zero-plaque plates; see run_metadata.json for the errors.")
        raise SystemExit(1)


def _process_one(image_path, plate_size, run_images, args):
    """Measure one image and write its CSV, annotated image and provenance row."""
    if True:
        # read + dim (see read_and_dim / read_and_dim_upstream_exact)
        image, orig_image, image_brightness = read_and_dim(image_path)

        binary_image, high_contrast, clr_high_contrast = process_image(image, 2.5)
        #       cv2.imshow("Binary image", binary_image)
        contours = get_contours(binary_image)
        image_size = binary_image.shape

        green_df, red_df, other_df, plate_df = filter_contours(contours, image_size)

        _ar = dish_axis_ratio(plate_df)
        if _ar is not None and _ar > 1.03:
            print(f"  WARNING: dish looks elliptical (axis ratio {_ar:.2f}) - the photo may be "
                  f"tilted/foreshortened, biasing mm calibration. Image plates straight-on.")

        # OPT-IN watershed recovery of touching/merged plaques. No-op (and no SOURCE
        # column) unless --watershed and not --published, so default output is unchanged.
        if watershed_enabled and not use_published:
            green_df = green_df.copy()
            green_df['SOURCE'] = 'auto'
            recovered_df = recover_merged_plaques(image_size, green_df, red_df, other_df)
            if not recovered_df.empty:
                recovered_df = recovered_df.copy()
                recovered_df['SOURCE'] = 'watershed'
                green_df = pd.concat([green_df, recovered_df], ignore_index=True)
                green_df = reindex(green_df.reset_index(drop=True))

        # Filter plaques duplicates (circle in circle) in valid plaques and plates
        green_df_copy = green_df.copy()
        plate_df_copy = plate_df.copy()
        green_df_copy = check_duplicate_plaques(green_df_copy)
        plate_df_copy = check_duplicate_plaques(plate_df_copy)

        red_df_copy = red_df.copy()
        other_df_copy = other_df.copy()

        green_df_copy = calculate_size_mm(plate_size, green_df_copy, plate_df)
        red_df_copy = calculate_size_mm(plate_size, red_df_copy, plate_df)
        other_df_copy = calculate_size_mm(plate_size, other_df_copy, plate_df)
        plate_df_copy = calculate_size_mm(plate_size, plate_df_copy, plate_df)

        if(green_df_copy.size > 0):
            # get Petri dish size and adjust plaques sizes
            green_df_copy['MEAN_COLOUR'] = green_df_copy.apply(lambda x: get_mean_grey_colour(high_contrast, x['CONTOURS']),
                                                               axis=1)

            green_df_copy['MEAN_COLOUR'] = green_df_copy.apply(
                lambda x: get_mean_grey_colour(clr_high_contrast, x['CONTOURS']),
                axis=1)

            #Remove extra black contours
            #TODO dark plaques are being filtered out (online_image.png
            filter_dev_colour = green_df_copy.apply(lambda x: abs(x['MEAN_COLOUR'] ) < 40, axis=1)
            green_df_copy = green_df_copy[~filter_dev_colour]
        else:
            green_df_copy['MEAN_COLOUR'] = 0

        green_df_copy = renumerate_df(green_df_copy)
        green_df_copy = add_turbidity(orig_image, plate_df, green_df_copy)
        if args.get('qc') and len(green_df_copy):
            try:
                import plaque_qc
                dish = None
                if plate_df is not None and not plate_df.empty:
                    big = plate_df['ENCL_DIAMETER_PXL'].idxmax()
                    c = plate_df.loc[big, 'ENCL_CENTER']
                    dish = (float(c[0]), float(c[1]), float(plate_df.loc[big, 'ENCL_DIAMETER_PXL']) / 2.0)
                fl, why = plaque_qc.flags_for_dataframe(green_df_copy, image_size, dish=dish)
                green_df_copy = green_df_copy.copy()
                green_df_copy['QC_FLAG'] = fl
                green_df_copy['QC_REASON'] = why
            except Exception as exc:             # QC must never break a measurement run
                print("  (QC flags skipped: %s)" % exc)
        renumerate_df(red_df)
        renumerate_df(other_df)

        output = draw_contours(clr_high_contrast, green_df_copy, red_df_copy, other_df_copy, plate_df_copy)

        if not os.path.exists(out_dir_path):
            os.makedirs(out_dir_path)
        write_images(out_dir_path, output, binary_image, high_contrast, image_path)

        # format float values
        # green_df_copy['ENCL_DIAMETER_MM'] = green_df_copy['ENCL_DIAMETER_MM'].apply(lambda x: f"{x:.2f}")
        write_data(out_dir_path, image_path, green_df_copy, red_df_copy, other_df)
        try:                             # provenance must never break a measurement run
            run_images.append({
                "file": os.path.basename(image_path),
                "path": image_path,
                "sha256_16": provenance.file_digest(image_path) if provenance else "",
                "n_plaques": int(len(green_df_copy)),
                "brightness": round(float(image_brightness), 4),
                "dimmed": bool(image_brightness > 70),
                "mm_per_px": last_calibration['mm_per_px'],
                "dish_axis_ratio": (round(float(_ar), 4) if _ar is not None else None),
                "csv": "data-green-%s.csv" % output_stem(image_path),
            })
        except Exception as exc:         # pragma: no cover - defensive only
            run_images.append({"file": os.path.basename(image_path),
                               "provenance_error": str(exc)})
        print("Process completed successfully")
        print(str(len(green_df_copy)) + ' plaques were found\n')


def renumerate_df(df):
    df_new = df.copy()
    df = df_new.reset_index()

    df_new['INDEX_COL'] = df.index + 1
    return df_new


def get_mean_grey_colour(img, contour):
    contour_mask = np.zeros(img.shape[:2], dtype="uint8")
    contour_mask = cv2.drawContours(contour_mask, [contour], -1, 255, -1)
    mean = cv2.mean(img, contour_mask)
    return mean[0]


# --------------------------------------------------------------------------- #
#  Watershed recovery of TOUCHING / MERGED plaques (opt-in: --watershed)
#  Splits blobs the circularity filter rejected, then re-measures each fragment
#  with the SAME per-contour math. OFF by default and in --published mode.
#  (Inspired by the DL instance-segmentation in PlaqSeg, done with classical CV
#  so it needs no extra dependencies and never alters the validated default.)
# --------------------------------------------------------------------------- #
WS_DEDUPE_CENTER_PX = 8   # a fragment within this of an existing green centre is a duplicate


def _watershed_split(mask, exp_radius):
    """Local-maxima marker-controlled watershed on a SMALL cropped blob mask.
    Seeds from LOCAL distance-transform maxima (min spacing ~ one plaque radius) so two
    overlapping plaques each get a seed even when one peak is shorter -- a single global
    distance threshold fails on real overlap. Returns sub-region contours in crop coords;
    empty list if the blob has only one seed (nothing to split)."""
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    if dt.max() <= 0:
        return []
    ksize = max(int(round(exp_radius)) | 1, 3)   # odd kernel ~ one plaque radius
    dil = cv2.dilate(dt, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize)))
    peaks = ((dt >= dil) & (dt > 0.25 * dt.max())).astype("uint8") * 255
    n_lbl, seeds = cv2.connectedComponents(peaks)
    if n_lbl <= 2:                                # <=1 real seed (label 0 = background)
        return []
    sure_bg = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=3)
    unknown = cv2.subtract(sure_bg, peaks)
    markers = seeds + 1
    markers[unknown > 0] = 0
    markers = cv2.watershed(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), markers)
    return _labels_to_contours(markers)


def _labels_to_contours(markers):
    contours = []
    for lbl in range(2, markers.max() + 1):
        region = np.uint8(markers == lbl) * 255
        if region.sum() == 0:
            continue
        cnts = imutils.grab_contours(
            cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE))
        if cnts:
            contours.append(max(cnts, key=cv2.contourArea))
    return contours


def recover_merged_plaques(image_size, green_df, red_df, other_df):
    """OPT-IN: split TOUCHING/MERGED plaques the circularity filter rejected and return the
    EXTRA recovered plaques as a green-shaped DataFrame. Empty when disabled/published/none.

    We only watershed-split blobs the detector ALREADY found but rejected for being large &
    non-circular (i.e. fused plaques), one blob at a time -- never the whole image. Each
    fragment must then pass the SAME green acceptance test, so junk is rejected by the
    validated filter. The recovered rows re-enter the normal green pipeline in main()."""
    empty = green_df.iloc[0:0].copy()
    # need a stable typical-plaque size; skip when too few plaques to trust the median
    if not watershed_enabled or use_published or len(green_df) < 5:
        return empty
    median_area = float(green_df['AREA_PXL'].median())   # typical single-plaque area
    exp_radius = max((median_area / np.pi) ** 0.5, 4.0)
    frames = [df for df in (red_df, other_df) if df is not None and not df.empty]
    if not frames:
        return empty
    blobs = pd.concat(frames, ignore_index=True)
    # red & other overlap -> drop blobs with the same centre so none is split twice
    blobs = blobs.assign(_cx=blobs['ENCL_CENTER'].apply(lambda c: round(c[0])),
                         _cy=blobs['ENCL_CENTER'].apply(lambda c: round(c[1]))) \
                 .drop_duplicates(subset=['_cx', '_cy']).drop(columns=['_cx', '_cy'])
    # merged candidates: clearly bigger than one plaque AND non-circular (the fused signature)
    merged = blobs[blobs.apply(
        lambda x: (1.3 * median_area < x['AREA_PXL'] < 100000
                   and calc_AREA_PXL_diff(x) > 0.21), axis=1)]
    if merged.empty:
        return empty

    H, W = image_size[:2]
    recovered = []
    for c in merged['CONTOURS']:
        c = np.asarray(c, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(c)
        x0, y0 = max(x - 3, 0), max(y - 3, 0)
        x1, y1 = min(x + w + 3, W), min(y + h + 3, H)
        sub = np.zeros((y1 - y0, x1 - x0), dtype='uint8')   # crop: ~100x cheaper than full frame
        cv2.drawContours(sub, [c - np.array([x0, y0], dtype=np.int32)], -1, 255, -1)
        off = np.array([x0, y0], dtype=np.int32)
        for cc in _watershed_split(sub, exp_radius):
            recovered.append(cc + off)                      # offset contour back to full image
    if not recovered:
        return empty

    cand = prepare_df(recovered)
    pms = image_size[1] / 15
    diam_min = 12 if small_plaques else 30
    keep = cand.apply(
        lambda x: (x['AREA_PXL'] < 100000 and x['AREA_PXL'] > pms
                   and calc_AREA_PXL_diff(x) < 0.21 and x['ENCL_DIAMETER_PXL'] > diam_min),
        axis=1)
    cand = cand[keep] if len(cand) else cand
    if cand.empty:
        return empty
    existing = [tuple(c) for c in green_df['ENCL_CENTER']]

    def _is_new(row):
        cx, cy = row['ENCL_CENTER']
        return not any(abs(cx - ex) <= WS_DEDUPE_CENTER_PX and abs(cy - ey) <= WS_DEDUPE_CENTER_PX
                       for ex, ey in existing)
    cand = cand[cand.apply(_is_new, axis=1)] if len(cand) else cand
    if cand.empty:
        return empty
    return check_duplicate_plaques(reindex(cand.reset_index(drop=True)))


if __name__ == '__main__':
    main()
