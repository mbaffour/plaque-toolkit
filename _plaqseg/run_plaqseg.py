"""Run PlaqSeg's YOLO-seg weights headlessly with the app's 1280px / 1024-stride tiling,
then merge detections across tiles (global NMS). Outputs a per-detection CSV, a count, and
an annotated overlay. Sizing uses the segmented MASK area (area-equivalent diameter), made
comparable to our tool via the same dish calibration (mm/px).

Usage:
  python run_plaqseg.py WEIGHTS IMAGE OUT_DIR TAG [--conf 0.25] [--iou 0.5] [--ppm 0.0363]
  (--ppm is mm-per-pixel from our dish calibration; omit to report pixels only)
"""
import argparse, os, json
import numpy as np
import cv2
from ultralytics import YOLO


def starts(total, tile, stride):
    if total <= tile:
        return [0]
    s = list(range(0, total - tile + 1, stride))
    if s[-1] != total - tile:
        s.append(total - tile)
    return s


def detect_plaqseg(model, img, conf=0.1, iou=0.5, ppm=0.0,
                   tile=1280, stride=1024, imgsz=1280):
    """Run the tiled YOLO-seg inference + global NMS on a BGR image array.

    ``model`` is a pre-loaded ``ultralytics.YOLO`` instance (so callers can reuse it
    in-process). Returns ``(rows, raw_count)`` where ``rows`` is a list of dicts with
    keys X, Y, AREA_PXL, DIAMETER_PXL, DIAMETER_MM, CONF -- exactly the schema written
    to plaqseg_<tag>.csv. ``ppm`` is mm-per-pixel (0 -> DIAMETER_MM stays 0).

    This is the importable core shared by the CLI ``main()`` and the in-process Precise
    pipeline (precise/pipeline.py); the algorithm is defined here once."""
    H, W = img.shape[:2]
    boxes, scores, areas = [], [], []
    for y0 in starts(H, tile, stride):
        for x0 in starts(W, tile, stride):
            crop = img[y0:y0 + tile, x0:x0 + tile]
            r = model.predict(crop, imgsz=imgsz, conf=conf, iou=iou, verbose=False)[0]
            if r.boxes is None or len(r.boxes) == 0:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy()
            cf = r.boxes.conf.cpu().numpy()
            polys = r.masks.xy if (r.masks is not None) else None
            for i in range(len(xyxy)):
                b = xyxy[i]
                gb = [float(b[0] + x0), float(b[1] + y0), float(b[2] + x0), float(b[3] + y0)]
                if polys is not None and i < len(polys) and len(polys[i]) >= 3:
                    area = float(cv2.contourArea(polys[i].astype(np.float32)))
                else:
                    area = float((b[2] - b[0]) * (b[3] - b[1]))
                boxes.append(gb); scores.append(float(cf[i])); areas.append(area)

    keep = []
    if boxes:
        xywh = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes]
        idxs = cv2.dnn.NMSBoxes(xywh, scores, conf, iou)
        keep = [int(i) for i in np.array(idxs).flatten()] if len(idxs) else []

    rows = []
    for k in keep:
        b = boxes[k]; area = areas[k]
        dia_px = 2.0 * np.sqrt(max(area, 0.0) / np.pi)
        dia_mm = dia_px * ppm if ppm > 0 else 0.0
        rows.append(dict(X=round((b[0]+b[2])/2, 1), Y=round((b[1]+b[3])/2, 1),
                         AREA_PXL=round(area, 1), DIAMETER_PXL=round(dia_px, 2),
                         DIAMETER_MM=round(dia_mm, 3), CONF=round(scores[k], 3)))
    return rows, len(boxes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weights"); ap.add_argument("image"); ap.add_argument("out_dir"); ap.add_argument("tag")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--ppm", type=float, default=0.0)      # mm per pixel (0 = pixels only)
    ap.add_argument("--tile", type=int, default=1280)
    ap.add_argument("--stride", type=int, default=1024)
    ap.add_argument("--imgsz", type=int, default=1280)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    model = YOLO(a.weights)
    img = cv2.imread(a.image)
    if img is None:
        raise SystemExit("could not read " + a.image)

    rows, raw = detect_plaqseg(model, img, conf=a.conf, iou=a.iou, ppm=a.ppm,
                               tile=a.tile, stride=a.stride, imgsz=a.imgsz)

    overlay = img.copy()
    diams_mm = []
    for r in rows:
        if a.ppm > 0 and r["DIAMETER_MM"] > 0:
            diams_mm.append(r["DIAMETER_MM"])
        cv2.circle(overlay, (int(r["X"]), int(r["Y"])),
                   max(int(r["DIAMETER_PXL"] / 2), 3), (0, 0, 255), 2)

    base = a.tag
    csv_path = os.path.join(a.out_dir, "plaqseg_%s.csv" % base)
    with open(csv_path, "w", newline="") as f:
        import csv as _csv
        w = _csv.DictWriter(f, fieldnames=["X","Y","AREA_PXL","DIAMETER_PXL","DIAMETER_MM","CONF"])
        w.writeheader(); [w.writerow(r) for r in rows]
    cv2.imwrite(os.path.join(a.out_dir, "plaqseg_overlay_%s.jpg" % base), overlay)

    summary = dict(tag=base, image=os.path.basename(a.image), weights=os.path.basename(a.weights),
                   conf=a.conf, iou=a.iou, count=len(rows), raw_detections=raw,
                   ppm_mm_per_px=a.ppm,
                   median_diam_mm=(round(float(np.median(diams_mm)),3) if diams_mm else None),
                   mean_diam_mm=(round(float(np.mean(diams_mm)),3) if diams_mm else None))
    print("PLAQSEG_RESULT " + json.dumps(summary))


if __name__ == "__main__":
    main()
