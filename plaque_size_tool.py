import argparse
import imutils
import cv2
import numpy as np
import os
import pandas as pd
from PIL import Image, ImageStat, ImageEnhance, ImageOps

# allow reading iPhone HEIC/HEIF images directly
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass


def read_image_bgr(path):
    """Read any supported image (incl. iPhone HEIC), honouring EXIF orientation."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.heic', '.heif', '.jpg', '.jpeg'):
        im = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    img = cv2.imread(path)
    if img is not None:
        return img
    im = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


__version__ = "1.0.0"
out_dir_path = './out'
small_plaques = False
debug_mode = False
# When True, reproduce the EXACT published Plaque Size Tool behaviour (for citation /
# comparison). Default False uses two small corrections: numeric (un-truncated) sizes,
# and concentric-duplicate de-dup that keeps one plaque instead of deleting both.
use_published = False
# Opt-in (--watershed): split touching/merged plaques. Never runs in published mode.
watershed_enabled = False
# Opt-in (--sensitive): lower the size gates to catch very small (<~0.4 mm) plaques.
# Detects many more on dense small-plaque plates, at the cost of more false positives.
sensitive = False


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
                    help="reproduce the EXACT published Plaque Size Tool output (no corrections)")
    ap.add_argument("-watershed", "--watershed", required=False, action="store_true",
                    help="opt-in: split touching/merged plaques via watershed and recover them "
                         "(adds a SOURCE column; ignored in --published mode)")
    ap.add_argument("-sensitive", "--sensitive", required=False, action="store_true",
                    help="opt-in: lower the size gates to catch very small (<~0.4 mm) plaques "
                         "(detects many more on dense plates, but more false positives; ignored in --published)")
    ap.add_argument("-debug", "--debug", required=False, action = "store_true")
    args = vars(ap.parse_args())
    if args['image'] ==  None and args['directory'] == None:
        raise Exception('Either -i or -d flags must be provided!')
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


def get_image_paths(image, directory):
    images = []
    if image:
        images.append(image)
    else:
        exts = ('.tif', '.tiff', '.jpg', '.jpeg', '.png', '.heic', '.heif')
        for r, d, f in os.walk(directory):
            for file in sorted(f):
                if os.path.splitext(file)[1].lower() in exts:   # case-insensitive; incl. HEIC
                    images.append(os.path.join(r, file))
    return images


def write_images(out_dir, output_image, binary_image, high_contrast_image, image_path):
    stem, ext = os.path.splitext(os.path.split(image_path)[1])
    if ext.lower() in ('.heic', '.heif'):   # OpenCV cannot write HEIC
        ext = '.png'
    cv2.imwrite(f'{out_dir}/out_{stem}{ext}', output_image)
    # cv2.imwrite(f'{out_dir}/out_red-{os.path.split(image_path)[1]}', output_image_red)
    #cv2.imwrite(f'{out_dir}/contrast-{os.path.split(image_path)[1]}', high_contrast_image)
    #cv2.imwrite(f'{out_dir}/binary-{os.path.split(image_path)[1]}', binary_image)


def write_data(out_dir, image_path, green_df, red_df, other_df):
    write_one_data(out_dir, image_path, 'green', green_df)
    #write_one_data(out_dir, image_path, 'red', red_df)
    #write_one_data(out_dir, image_path, 'other', other_df)


def write_one_data(out_dir, image_path, prefix, df):
    image_file_name = os.path.split(image_path)[1]
    image_name = os.path.splitext(image_file_name)[0]
    if df.empty != True:
        cols = ['INDEX_COL', 'AREA_PXL', 'DIAMETER_PXL', 'AREA_MM2', 'DIAMETER_MM',
                'MEAN_GRAY', 'TURBIDITY_REL']
        if 'SOURCE' in df.columns:
            cols.append('SOURCE')
        df.to_csv(path_or_buf=f'{out_dir}/data-{prefix}-{image_name}.csv', index=False,
                  columns=cols)
                  #columns=['INDEX_COL', 'AREA_PXL', 'PERIMETER_PXL', 'ENCL_CENTER', 'ENCL_DIAMETER_PXL'])


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
    # exact published behaviour: drops BOTH members of every concentric pair
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
    # dropped BOTH members of every pair, silently deleting real plaques (use --published).
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

def _calculate_size_mm_published(plate_size, obj_df, plate_df):
    # exact published behaviour: values stored as 2-dp strings; DIAMETER_MM derived
    # from the truncated AREA_MM2 string; no warning if the dish isn't found.
    if obj_df.size > 0:
        obj_df['DIAMETER_PXL'] = obj_df.apply(
            lambda x: f"{np.sqrt(float(x['AREA_PXL'])/np.pi)*2:.2f}", axis=1)
    if plate_size and obj_df.size > 0:
        mpp = float(plate_size) / float(plate_df['ENCL_DIAMETER_PXL'].max())
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
        obj_df['ENCL_DIAMETER_MM'] = obj_df['ENCL_DIAMETER_PXL'].apply(lambda d: round(float(d) * mm_per_px, 2))
        obj_df['AREA_MM2'] = obj_df['AREA_PXL'].apply(lambda a: round(float(a) * mm_per_px * mm_per_px, 2))
        # diameter from the TRUE area (not a 2-dp-truncated AREA_MM2 string)
        obj_df['DIAMETER_MM'] = obj_df['AREA_PXL'].apply(
            lambda a: round(float(np.sqrt(float(a) * mm_per_px * mm_per_px / np.pi) * 2), 2))
    else:
        if plate_size:
            print("  WARNING: -p was given but no Petri dish was detected; "
                  "reporting pixels only (mm columns = 0).")
        obj_df['ENCL_DIAMETER_MM'] = 0
        obj_df['AREA_MM2'] = 0
        obj_df['DIAMETER_MM'] = 0

    return obj_df

def get_brightness( im_file ):
   im = Image.open(im_file)
   im.convert('L')
   stat = ImageStat.Stat(im)
   return stat.mean[0]

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

    image_paths = get_image_paths(args['image'], args['directory'])
    plate_size = args['plate_size']

    global small_plaques
    global debug_mode
    global use_published
    global watershed_enabled
    global sensitive
    small_plaques = args['small_plaque']
    debug_mode = args['debug']
    use_published = args.get('published', False)
    watershed_enabled = args.get('watershed', False) and not use_published
    sensitive = args.get('sensitive', False) and not use_published
    if use_published:
        print("(running in --published mode: exact published Plaque Size Tool behaviour)")
    if watershed_enabled:
        print("(watershed recovery ON: touching plaques will be split and recovered)")
    if sensitive:
        print("(sensitive mode ON: detecting very small plaques - expect more, and some false positives)")

    for image_path in image_paths:
        print("Processing " + image_path)

        # read (HEIC-safe) and dim too-bright images in memory (no temp files)
        image = read_image_bgr(image_path)
        orig_image = image.copy()   # true (undimmed) image, used for turbidity
        image_brightness = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean())
        if image_brightness > 70:
            image = np.clip(image.astype(np.float32) * 0.5, 0, 255).astype(np.uint8)

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
        renumerate_df(red_df)
        renumerate_df(other_df)

        output = draw_contours(clr_high_contrast, green_df_copy, red_df_copy, other_df_copy, plate_df_copy)

        if not os.path.exists(out_dir_path):
            os.makedirs(out_dir_path)
        write_images(out_dir_path, output, binary_image, high_contrast, image_path)

        # format float values
        # green_df_copy['ENCL_DIAMETER_MM'] = green_df_copy['ENCL_DIAMETER_MM'].apply(lambda x: f"{x:.2f}")
        write_data(out_dir_path, image_path, green_df_copy, red_df_copy, other_df)
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
