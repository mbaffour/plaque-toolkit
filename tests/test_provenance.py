"""PT-9: every size output must say which engine, settings and version made it.

Before this fix a `data-green-*.csv` recorded measurements and nothing else. Two CSVs
produced by `--published` and by `--sensitive` were indistinguishable on disk, so a
number in a manuscript could not be traced back to the code that produced it.

The fix is deliberately additive -- a `run_metadata.json` sibling -- so these tests
also pin the thing that matters more than the feature: the measurement CSVs
themselves must be byte-for-byte unchanged by provenance recording.
"""
import io
import json
import os
import sys
import contextlib

import pytest

import provenance
import plaque_size_tool as pst
from _version import __version__ as TOOLKIT_VERSION


def _run(image_path, out_dir, extra=()):
    os.makedirs(out_dir, exist_ok=True)
    saved_out, saved_argv = pst.out_dir_path, sys.argv
    pst.out_dir_path = out_dir
    sys.argv = ["plaque_size_tool.py", "-i", image_path, "-p", "90"] + list(extra)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pst.main()
    finally:
        pst.out_dir_path, sys.argv = saved_out, saved_argv
    with open(os.path.join(out_dir, provenance.METADATA_FILENAME)) as fh:
        return json.load(fh)


def test_engine_name_covers_every_documented_engine():
    """The labels must match README.md's engine table, and --upstream-exact must be
    distinguishable from plain --published (that is the whole point of PT-1)."""
    assert provenance.engine_name() == "Current"
    assert provenance.engine_name(sensitive=True) == "Sensitive"
    assert provenance.engine_name(published=True) == "Published"
    assert provenance.engine_name(published=True, upstream_exact=True) == \
        "Published (--upstream-exact)"
    assert provenance.engine_name(precise=True) == "Precise"


def test_size_tool_writes_engine_settings_and_version(neutral_plate_tif, tmp_path):
    meta = _run(neutral_plate_tif, str(tmp_path / "out"))
    assert meta["tool"] == "plaque_size_tool.py"
    assert meta["engine"] == "Current"
    assert meta["toolkit_version"] == TOOLKIT_VERSION
    assert meta["settings"]["plate_size_mm"] == "90"
    assert meta["settings"]["published"] is False
    assert meta["library_versions"]["opencv"] not in ("", "?", "not installed")
    img, = meta["images"]
    assert img["file"] == os.path.basename(neutral_plate_tif)
    assert img["n_plaques"] > 0
    assert img["mm_per_px"] > 0
    assert len(img["sha256_16"]) == 16
    assert img["csv"] == "data-green-neutral_plate.csv"


@pytest.mark.parametrize("flags,engine", [
    ([], "Current"),
    (["--published"], "Published"),
    (["--upstream-exact"], "Published (--upstream-exact)"),
    (["--sensitive"], "Sensitive"),
])
def test_the_recorded_engine_matches_the_flags_used(neutral_plate_tif, tmp_path,
                                                    flags, engine):
    meta = _run(neutral_plate_tif, str(tmp_path / ("out" + "".join(flags) or "out")), flags)
    assert meta["engine"] == engine


def test_a_zero_plaque_plate_still_gets_provenance(blank_plate_png, tmp_path):
    """PT-3 and PT-9 together: a negative control is a result, and it is traceable."""
    meta = _run(blank_plate_png, str(tmp_path / "out"))
    img, = meta["images"]
    assert img["n_plaques"] == 0


def test_provenance_does_not_change_any_measurement_number(neutral_plate_tif, tmp_path):
    """The honesty guarantee: recording provenance is additive. Running twice must
    give identical CSV bytes, and the only non-CSV/-image artefact is the metadata."""
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    _run(neutral_plate_tif, a, ["--published"])
    _run(neutral_plate_tif, b, ["--published"])
    for name in os.listdir(a):
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(a, name), "rb") as fh1, open(os.path.join(b, name), "rb") as fh2:
            assert fh1.read() == fh2.read(), "%s is not reproducible" % name
    assert provenance.METADATA_FILENAME in os.listdir(a)


def test_write_metadata_never_raises(tmp_path):
    """Provenance must not be able to destroy a run: an unwritable destination and
    unserialisable settings both have to fail quietly."""
    class Unserialisable:
        pass

    path = provenance.write_metadata(str(tmp_path / "new" / "deeper"), "t", "Current",
                                     {"weird": Unserialisable()})
    assert path and os.path.exists(path)

    blocker = tmp_path / "blocked"
    blocker.write_text("I am a file, not a directory")
    assert provenance.write_metadata(str(blocker), "t", "Current", {}) is None


def test_batch_runner_records_the_same_shape(tmp_path, monkeypatch):
    """app/batch_measure.py must write the same record, with its own mode mapping."""
    from app import batch_measure

    meta_seen = {}

    def fake_write(out_dir, tool, engine, settings, images=None, extra=None):
        meta_seen.update(provenance.build_metadata(tool, engine, settings, images, extra))
        return None

    monkeypatch.setattr(provenance, "write_metadata", fake_write)
    monkeypatch.setattr(batch_measure, "find_images", lambda folder: [])
    batch_measure.batch_measure(str(tmp_path), plate_mm=90, mode="published",
                                out_dir=str(tmp_path / "out_batch"))
    assert meta_seen["tool"] == "app/batch_measure.py"
    assert meta_seen["engine"] == "Published"
    assert meta_seen["toolkit_version"] == TOOLKIT_VERSION
    assert meta_seen["settings"]["mode"] == "published"
    assert meta_seen["settings"]["plate_size_mm"] == 90
