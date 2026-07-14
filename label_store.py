"""label_store.py — a persistent, catalogued store for plaque ground-truth labels.

Files a label set (from the desktop app's "Ground-truth labels" export, from a Fiji
Results.csv, or from any labels_*.json) into a growing training-data store, with enriched
metadata, so labels accumulate into a dataset ready for retraining the classifier.

Stdlib-only (json/csv/hashlib/shutil) so it is dependency-light and PyInstaller bundles it
automatically (it is a plain top-level import from app/plaque_canvas.py).

Store layout (default: <repo>/training_data/ from source, else ~/Plaque Toolkit Training Data;
override with the PLAQUE_TRAINING_DIR environment variable):

    training_data/
      catalog.csv                 # one row per labelled plate (the index for training)
      labels/<label_id>.json      # the label set (meta + per-plaque records)
      labels/<label_id>.csv       # the same records, flat
      images/<label_id>.<ext>     # a copy of the source plate image (if copy_image)

Label schema: {"meta": {...}, "plaques": [{index, x_px, y_px, r_px, area_px, diam_mm,
source, kind}, ...]} — the same "plaque-groundtruth-v1" the app already writes.
"""
import csv
import datetime
import hashlib
import json
import os
import re
import shutil

SCHEMA = "plaque-groundtruth-v1"
CATALOG_COLS = ["date", "label_id", "sample", "replicate", "image", "image_stored", "label_json",
                "n_plaques", "n_manual", "mm_per_px", "source", "engine", "app_version",
                "image_sha1", "notes"]


def store_root():
    """Resolve the training-data store folder (env override > source checkout > user home)."""
    env = os.environ.get("PLAQUE_TRAINING_DIR")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    markers = ("app", "_research", "plaque_size_tool.py")
    if any(os.path.exists(os.path.join(here, m)) for m in markers):
        return os.path.join(here, "training_data")                       # source checkout
    return os.path.join(os.path.expanduser("~"), "Plaque Toolkit Training Data")


def sha1_file(path, block=1 << 20):
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(block), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:                                                    # noqa: BLE001
        return None


def parse_sample_replicate(stem):
    """'WT-1' -> ('WT','1'); 'T65I_2' -> ('T65I','2'); 'IMG_3907' -> ('IMG_3907', None)."""
    m = re.match(r"^(?P<s>.+?)[-_](?P<r>\d+)$", str(stem))
    if m and not m.group("s").upper().startswith("IMG"):
        return m.group("s"), m.group("r")
    return str(stem), None


def _now():
    return datetime.datetime.now()


def file_into_store(meta, plaques, image_path=None, *, source="app", engine=None,
                    app_version=None, notes="", copy_image=True, root=None):
    """Write a label set (+ optional image copy) into the store and append a catalog row.

    `meta`/`plaques` follow the app's schema. Returns the stored label .json path.
    """
    root = os.path.abspath(root or store_root())
    labels_dir = os.path.join(root, "labels")
    imgs_dir = os.path.join(root, "images")
    os.makedirs(labels_dir, exist_ok=True)
    os.makedirs(imgs_dir, exist_ok=True)

    img = image_path or meta.get("image_path") or meta.get("image")
    stem = os.path.splitext(os.path.basename(meta.get("image") or img or "label"))[0]
    sample, rep = parse_sample_replicate(stem)
    now = _now()
    label_id = "%s_%s" % (re.sub(r"[^A-Za-z0-9._-]", "_", stem), now.strftime("%Y%m%d-%H%M%S"))
    sha = sha1_file(img) if (img and os.path.exists(img)) else None

    image_stored = ""
    if copy_image and img and os.path.exists(img):
        ext = os.path.splitext(img)[1] or ".png"
        image_stored = os.path.join("images", label_id + ext)
        try:
            shutil.copy2(img, os.path.join(root, image_stored))
        except Exception:                                                # noqa: BLE001
            image_stored = ""

    full_meta = dict(meta)
    full_meta.update(schema=SCHEMA, label_id=label_id,
                     date=now.isoformat(timespec="seconds"),
                     sample=sample, replicate=rep, source=source, engine=engine,
                     app_version=app_version, image_sha1=sha,
                     image_stored=(image_stored or None), notes=notes)

    label_json = os.path.join(labels_dir, label_id + ".json")
    with open(label_json, "w", encoding="utf-8") as f:
        json.dump({"meta": full_meta, "plaques": plaques}, f, indent=2)

    if plaques:                                                          # flat CSV of the records
        cols = list(plaques[0].keys())
        with open(os.path.join(labels_dir, label_id + ".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for p in plaques:
                w.writerow({k: p.get(k) for k in cols})

    n_manual = sum(1 for p in plaques if str(p.get("source", "auto")) != "auto")
    row = {"date": full_meta["date"], "label_id": label_id, "sample": sample, "replicate": rep or "",
           "image": os.path.basename(img) if img else "", "image_stored": image_stored,
           "label_json": os.path.relpath(label_json, root).replace("\\", "/"),
           "n_plaques": len(plaques), "n_manual": n_manual,
           "mm_per_px": meta.get("mm_per_px"), "source": source, "engine": engine or "",
           "app_version": app_version or "", "image_sha1": sha or "", "notes": notes}
    cat = os.path.join(root, "catalog.csv")
    new = not os.path.exists(cat)
    with open(cat, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_COLS)
        if new:
            w.writeheader()
        w.writerow(row)
    return label_json


def ingest_label_file(path, *, source="import", notes="", copy_image=True, root=None):
    """Read an existing labels_*.json (app export) and file it into the store."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    meta = d.get("meta", {})
    plaques = d.get("plaques", d.get("records", []))
    img = meta.get("image_path")
    if not (img and os.path.exists(img)):                                # try next to the json
        cand = os.path.join(os.path.dirname(path), meta.get("image", ""))
        img = cand if os.path.exists(cand) else None
    return file_into_store(meta, plaques, img, source=source, engine=meta.get("engine"),
                           app_version=meta.get("app_version"), notes=notes,
                           copy_image=copy_image, root=root)


def catalog_summary(root=None):
    """Return (n_plates, n_plaques, by_sample dict) from the store's catalog, or (0,0,{})."""
    root = os.path.abspath(root or store_root())
    cat = os.path.join(root, "catalog.csv")
    if not os.path.exists(cat):
        return 0, 0, {}
    n, tot, by = 0, 0, {}
    with open(cat, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            n += 1
            try:
                tot += int(r.get("n_plaques") or 0)
            except ValueError:
                pass
            by[r.get("sample", "")] = by.get(r.get("sample", ""), 0) + 1
    return n, tot, by


if __name__ == "__main__":
    r = store_root()
    n, tot, by = catalog_summary(r)
    print("training-data store:", r)
    print("labelled plates: %d | plaques: %d | by sample: %s" % (n, tot, by))
