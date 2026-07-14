#!/usr/bin/env python3
"""ingest_labels.py — file existing ground-truth labels into the training-data store.

Takes the app's exported `labels_*.json` files (single files or whole folders) and files each
into the persistent training store (label + image copy + catalog row), ready for retraining.

Usage:
    python ingest_labels.py path\to\labels_folder
    python ingest_labels.py labels_WT-1.json labels_T65I-2.json --notes "batch 2026-07"
    python ingest_labels.py <folder> --no-image     # reference images instead of copying
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
import label_store as ls


def _gather(paths):
    files = []
    for path in paths:
        if os.path.isdir(path):
            hit = sorted(glob.glob(os.path.join(path, "labels_*.json"))) \
                or sorted(glob.glob(os.path.join(path, "*.json")))
            files += hit
        elif path.lower().endswith(".json"):
            files.append(path)
    # skip files that already look like store entries (avoid re-ingesting the store into itself)
    return [f for f in files if os.path.basename(os.path.dirname(f)) != "labels"]


def main(argv=None):
    p = argparse.ArgumentParser(description="File existing labels_*.json into the training store.")
    p.add_argument("paths", nargs="+", help="labels_*.json files, or folders that contain them")
    p.add_argument("--source", default="import", help="tag for the catalog 'source' column")
    p.add_argument("--notes", default="", help="free-text note recorded with each entry")
    p.add_argument("--no-image", action="store_true", help="reference images by path instead of copying")
    ns = p.parse_args(argv)

    files = _gather(ns.paths)
    if not files:
        raise SystemExit("No label .json files found in: %s" % ", ".join(ns.paths))
    print("store: %s" % ls.store_root())
    ok = 0
    for fp in files:
        try:
            out = ls.ingest_label_file(fp, source=ns.source, notes=ns.notes,
                                       copy_image=not ns.no_image)
            print("  filed  %-40s -> %s" % (os.path.basename(fp), os.path.basename(out)))
            ok += 1
        except Exception as e:                                       # noqa: BLE001
            print("  SKIP   %-40s (%s)" % (os.path.basename(fp), e))
    n, tot, by = ls.catalog_summary()
    print("\nIngested %d/%d files. Store now: %d labelled plates, %d plaques. By sample: %s"
          % (ok, len(files), n, tot, by))


if __name__ == "__main__":
    main()
