#!/usr/bin/env python3
"""plaque_stats.py — publication-ready violin plots + statistics for grouped plaque measurements.

Reads a tidy CSV of measurements grouped by SAMPLE (and, ideally, by REPLICATE / plate), then:
  1. writes data summaries (per group and per replicate),
  2. computes group-comparison statistics that treat the PLATE as the experimental unit
     (avoiding pseudoreplication — the correct default for plaque data),
  3. draws a customizable, reproducible, publication-ready violin plot,
  4. writes a plain-language report + a machine-readable run_config.json for reproducibility.

Only dependencies: pandas, numpy, matplotlib, scipy (>= 1.11).

------------------------------------------------------------------------------------------------
INPUT DATA FORMAT  (tidy CSV — one row per plaque)
------------------------------------------------------------------------------------------------
LONG (recommended — one file can hold several metrics):
    group,replicate,metric,value
    T4,plate1,diameter_mm,2.34
    T4,plate1,diameter_mm,2.51
    T7,plate1,diameter_mm,1.80
WIDE (matches the app's per-plaque export — just add group/replicate columns):
    group,replicate,diameter_mm,area_mm2,turbidity
    T4,plate1,2.34,4.30,0.12
Columns:
  group      (REQUIRED) the sample/condition/phage you compare — the x-axis categories.
  replicate  (recommended) the plate / experimental-unit id — used so stats are per-plate.
  value      (LONG only) the number to analyse; pair with a `metric` column to hold many metrics.
  <numeric>  (WIDE) any numeric column (diameter_mm, area_mm2, turbidity, …) selectable with --value.

Usage:
    python plaque_stats.py DATA.csv --group group --value diameter_mm --replicate replicate --out results
    python plaque_stats.py DATA.csv --config my_config.json          # everything from a JSON config
    python plaque_stats.py --make-example                            # write example + template CSVs
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch

# keep text EDITABLE in vector exports (Illustrator / Inkscape) — for every figure and table
matplotlib.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42})

import scipy
from scipy import stats as st

try:                                    # flat: python plaque_stats.py, the wheel, the Shiny app
    import legend_key as _lk
except ImportError:                     # imported as plaque_stats.plaque_stats (desktop app, repo root)
    from . import legend_key as _lk

__version__ = "1.1.0"            # the stand-alone plaque-stats package's own version


def _toolkit_version():
    """Version shown in report headers and run_config: the Plaque Toolkit's (repo `_version.py`)
    when this engine runs inside the toolkit, else the stand-alone package's own (CT-R1 web F23)."""
    try:
        from _version import __version__ as v          # repo root on sys.path (desktop app, tests)
        return "Plaque Toolkit %s" % v
    except Exception:                                  # noqa: BLE001
        pass
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        vp = os.path.join(os.path.dirname(here), "_version.py")
        if os.path.isfile(vp) and os.path.isfile(os.path.join(os.path.dirname(here), "plaque_size_tool.py")):
            ns = {}
            with open(vp, encoding="utf-8") as fh:
                exec(compile(fh.read(), vp, "exec"), ns)     # dependency-free by its own contract
            return "Plaque Toolkit %s" % ns["__version__"]
    except Exception:                                  # noqa: BLE001
        pass
    return "plaque_stats v%s" % __version__


def _stamp(args):
    """The report timestamp: the caller's, or the real time when none (or an empty one) is passed."""
    return (args or {}).get("_stamp") or datetime.now().strftime("%Y-%m-%d %H:%M")


class StatsError(ValueError, SystemExit):
    """A problem with the input or the options, worded for the user.

    It is BOTH a ValueError and a SystemExit: the command line still exits with the message
    (as every `raise StatsError("[error] ...")` here always did, and as existing callers and
    tests expect), while a GUI's ordinary `except Exception` now catches it and can show it
    instead of the process dying (CT-R1 DA-F1, web F1)."""

    def __init__(self, msg):
        msg = str(msg)
        if not msg.startswith("[error]"):
            msg = "[error] " + msg
        super().__init__(msg)
        self.code = msg

    @property
    def message(self):
        """The message without the CLI's '[error] ' prefix (for a GUI label)."""
        return str(self.code)[len("[error] "):]

    def __str__(self):
        return str(self.code)

# Okabe–Ito colour-blind-safe qualitative palette (the publication default, for the group violins)
OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
             "#D55E00", "#F0E442", "#999999", "#000000"]

# muted qualitative palette for REPLICATES (plates): SuperPlot points + plate-mean markers are
# coloured by plate, so plate-to-plate structure is visible (Lord et al. 2020; Kenny & Schoen 2021)
REP_PALETTE = ["#4C6E9C", "#E0A458", "#6AAA64", "#B65C5C", "#8A78B0",
               "#4FA3A5", "#C77CB5", "#9A8C6B", "#6C6C6C"]


def _darken(hexc, f=0.62):
    hexc = str(hexc).lstrip("#")
    if len(hexc) != 6:
        return "#33413c"
    r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))

DEFAULTS = {
    "group": "group", "value": None, "replicate": "replicate", "metric": "metric",
    "subgroup": None, "control": None,   # grouped control-comparison mode (2nd factor + its control)
    "unit": "auto",                # auto | replicate | plaque  (statistical unit)
    "order": None,                 # explicit group order (list) or None = as-they-appear
    "palette": OKABE_ITO,
    "title": None, "ylabel": None, "xlabel": "",
    "parametric": "auto",          # auto | parametric | nonparametric
    "annotate": "auto",            # auto | all | adjacent | none  (which pairs get brackets)
    "show_points": True, "show_box": True, "show_mean": True,
    "log_y": False, "width": 8.0, "height": 5.2, "dpi": 300,
    "point_size": 16.0, "jitter": 0.08, "violin_alpha": 0.55, "seed": 7,
    "formats": ["png", "svg", "pdf"], "theme": "clean", "legend": True, "violin_fill": "auto",
    "show_n": True, "show_value": True, "center": "mean", "error": "auto", "frame": False,
    "stats_table": True,
    "legend_key": True,            # write <figure>_legend_key.<fmt> + <figure>_legend_text.txt
}

# named colour themes for --palette (or pass your own comma-separated hex list)
PALETTES = {
    "okabe": OKABE_ITO,
    "set2": ["#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"],
    "tab10": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2",
              "#7f7f7f", "#bcbd22", "#17becf"],
    "warm": ["#B4451F", "#D98032", "#E9B44C", "#9B2226", "#CA6702", "#BB3E03", "#AE2012", "#EE9B00"],
    "cool": ["#3D5A80", "#5E8B9E", "#98C1D9", "#293241", "#4C6E9C", "#6AAA9E", "#5C7AA0", "#7FB3C9"],
    "grays": ["#4d4d4d", "#7f7f7f", "#a6a6a6", "#c9c9c9", "#2b2b2b", "#8f8f8f", "#606060", "#b8b8b8"],
}


# --------------------------------------------------------------------------- I/O
# Column names that hold LABELS (never numbers), used when read_table() is not told which
# columns are labels. run() always tells it, so the CLI never depends on this list.
LABEL_COLUMN_NAMES = ("group", "subgroup", "replicate", "plate", "sample", "host", "phage",
                      "strain", "condition", "treatment", "metric", "name", "label", "id")
_NUM_RE = r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$"
_DECIMAL_COMMA_RE = r"^[+-]?\d+,\d+$"
_DELIM_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}


def _cells(series):
    """A column's cells as trimmed text, with only really-empty cells missing (NaN)."""
    miss = series.isna()
    txt = series.astype(str).str.strip()
    return txt.where(~miss & (txt != ""), np.nan)


def _labels(series):
    """Label text exactly as typed (CT-R1 SM-F1/F2, DA-F2): only whitespace is trimmed and only
    an empty cell is missing. 'None', 'NA', 'nan', 'null', '007', '1.0', 'T7 #2' are labels.
    A NUMERIC column is different: there the text was produced by pandas, not typed, and pandas
    turns the integer ids 1, 2 into 1.0, 2.0 as soon as one cell is blank -- so whole-number
    floats are written back as integers (this is all the old `_clean` '.0' stripping was for)."""
    if pd.api.types.is_bool_dtype(series):
        return series.astype(str)
    if pd.api.types.is_numeric_dtype(series):
        miss = series.isna()
        vals = series[~miss].astype(float)
        if len(vals) and np.all(np.isfinite(vals)) and np.all(vals == np.round(vals)):
            out = series.map(lambda v: np.nan if v != v else str(int(v)))
        else:
            out = series.map(lambda v: np.nan if v != v else repr(float(v)) if isinstance(v, float) else str(v))
        return out.astype(object)
    return _cells(series).astype(object)


def _numbers(series):
    """(float values, n cells that are text but not a number, decimal-commas-converted?)."""
    if pd.api.types.is_bool_dtype(series):
        return pd.Series(np.nan, index=series.index), int(series.notna().sum()), False
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").astype(float), 0, False
    txt = _cells(series)
    num = pd.to_numeric(txt, errors="coerce")
    bad = txt.notna() & num.isna() & ~txt.astype(str).str.lower().isin(["nan"])
    comma = False
    if bad.any() and txt[bad].astype(str).str.match(_DECIMAL_COMMA_RE).all():
        # European decimal commas ("2,34"): read them as numbers instead of dropping every row
        num = pd.to_numeric(txt.astype(str).str.replace(",", ".", regex=False).where(txt.notna(), np.nan),
                            errors="coerce")
        bad = txt.notna() & num.isna()
        comma = True
    return num.astype(float), int(bad.sum()), comma


def numeric_columns(df, exclude=()):
    """Columns whose every non-empty cell is a number (numeric dtype, or text that parses as
    numbers, decimal commas included). Use this instead of a dtype test to offer value columns."""
    out = []
    for c in df.columns:
        if c in exclude:
            continue
        if pd.api.types.is_bool_dtype(df[c]):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            out.append(c); continue
        num, nbad, _ = _numbers(df[c])
        if nbad == 0 and num.notna().any():
            out.append(c)
    return out


def _sniff_delimiter(header, default):
    """The delimiter of a text table, from its header line (outside quotes)."""
    counts, inq = {d: 0 for d in _DELIM_NAMES}, False
    for ch in header:
        if ch == '"':
            inq = not inq
        elif not inq and ch in counts:
            counts[ch] += 1
    best = max(counts, key=lambda d: (counts[d], d == default))
    return best if counts[best] else default


def read_table(path, text_columns=None, return_info=False):
    """Read a CSV / TSV / TXT / XLSX table the way a person typed it (CT-R1 SM-F1, SM-F2, web F4).

    * Labels stay labels: nothing is turned into "missing" except an empty cell (pandas' default
      NA strings -- None, NA, nan, null, N/A ... -- are ordinary names here), and label columns are
      kept as text exactly as typed ('007', '1.0', '0.10').
    * `#` is not a comment character: only whole lines that START with `#` are skipped, so a
      sample called 'T7 #2' or a plate called 'plate #1' keeps its row.
    * The delimiter (comma, semicolon, tab, pipe) is detected from the header, and European
      decimal commas ("2,34") are read as numbers. A file that parses to a single column is
      refused with a message that says so.

    text_columns : names of the columns to keep as text (run() passes the group / subgroup /
                   replicate / metric columns). None = every column that is not purely numeric,
                   plus label-named columns (group, replicate, plate, sample, ...) and columns
                   with leading-zero ids such as 007. "all" = keep everything as text (then use
                   numeric_columns() to list the value columns).
    return_info  : also return {"delimiter", "decimal", "rows", "columns", "comment_lines",
                   "note"} -- `note` is one short sentence for a GUI ("read 219 rows x 5
                   columns; semicolon-separated; decimal comma").
    Returns the DataFrame, or (DataFrame, info) with return_info=True."""
    ext = os.path.splitext(str(path))[1].lower()
    info = {"delimiter": None, "decimal": ".", "rows": 0, "columns": [], "comment_lines": 0}
    if ext in (".xlsx", ".xls"):
        raw = pd.read_excel(path, dtype=object, keep_default_na=False, na_values=[""])
        info["delimiter"] = "excel"
    else:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            lines = fh.read().splitlines()
        kept = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
        info["comment_lines"] = sum(1 for ln in lines if ln.lstrip().startswith("#"))
        if not kept:
            raise StatsError("%s is empty (no header line)." % os.path.basename(str(path)))
        sep = _sniff_delimiter(kept[0], "\t" if ext in (".tsv", ".txt") else ",")
        import io
        try:
            raw = pd.read_csv(io.StringIO("\n".join(kept)), sep=sep, dtype=str,
                              keep_default_na=False, na_values=[""], skip_blank_lines=True)
        except Exception as e:                                         # noqa: BLE001
            raise StatsError("could not read %s as a %s-separated table: %s"
                             % (os.path.basename(str(path)), _DELIM_NAMES[sep], e))
        info["delimiter"] = sep
        if raw.shape[1] < 2:
            raise StatsError(
                "%s was read as ONE column (%r). Expected a comma-, semicolon- or tab-separated "
                "table with a header row, e.g. group,replicate,diameter_mm."
                % (os.path.basename(str(path)), str(raw.columns[0]) if raw.shape[1] else ""))
    raw.columns = [str(c).strip() for c in raw.columns]
    keep_all = isinstance(text_columns, str) and text_columns == "all"
    named = None if (text_columns is None or keep_all) else {str(c) for c in text_columns if c}
    df = raw.copy()
    for c in raw.columns:
        if keep_all or (named is not None and c in named):
            df[c] = _labels(raw[c]); continue
        num, nbad, comma = _numbers(raw[c])
        cells = _cells(raw[c])
        numeric = nbad == 0 and num.notna().any()
        if numeric and named is None:
            lead0 = cells.dropna().astype(str).str.match(r"^[+-]?0\d").any()     # 007 is an id
            if c.lower() in LABEL_COLUMN_NAMES or lead0:
                numeric = False
        if numeric:
            df[c] = num
            if comma:
                info["decimal"] = ","
        else:
            df[c] = _labels(raw[c])
    info["rows"], info["columns"] = int(len(df)), list(df.columns)
    bits = ["read %d row%s x %d columns" % (len(df), "" if len(df) == 1 else "s", df.shape[1])]
    if info["delimiter"] not in (None, "excel", ","):
        bits.append("%s-separated" % _DELIM_NAMES.get(info["delimiter"], info["delimiter"]))
    if info["decimal"] == ",":
        bits.append("decimal commas read as decimal points")
    if info["comment_lines"]:
        bits.append("%d line%s starting with # skipped" % (info["comment_lines"],
                                                          "" if info["comment_lines"] == 1 else "s"))
    info["note"] = "; ".join(bits) + "."
    return (df, info) if return_info else df


def _resolve_col(cols, name):
    """The real column for `name`: exact, else the single case-insensitive match, else None."""
    if name is None:
        return None
    name = str(name).strip()
    if name in cols:
        return name
    hits = [c for c in cols if str(c).lower() == name.lower()]
    return hits[0] if len(hits) == 1 else None


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _normalize_core(df, group, value, replicate, metric, subgroup=None):
    """Shared by normalize() and normalize_grouped(): pick the columns, keep labels as typed,
    and COUNT every row that is left out (attrs['dropped'] / attrs['notes'])."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    cols = list(df.columns)
    gcol = _resolve_col(cols, group)
    if gcol is None:
        raise StatsError(f"[error] group column {group!r} not found. Columns: {sorted(cols)}")
    scol = None
    if subgroup is not None:
        scol = _resolve_col(cols, subgroup)
        if scol is None:
            raise StatsError("[error] subgroup column %r not found. Columns: %s" % (subgroup, sorted(cols)))
    rcol = _resolve_col(cols, replicate)
    mcol = _resolve_col(cols, metric)
    vlong = _resolve_col(cols, "value")          # the LONG layout's value column (any case)
    vres = _resolve_col(cols, value)
    labels = [c for c in (gcol, scol, rcol, mcol) if c]

    # LONG layout: a `value` column plus a `metric` column naming what each row measures.
    # `--value <metric name>` picks the metric. Before 1.1.1 the filter below was dead code
    # (its guard contradicted the long_mode test), so a LONG file was either analysed with
    # ALL its metrics pooled into one sample (diameter + area + turbidity) or, with the
    # documented --value, rejected as a missing column (AUDIT-2026-10.md, PT-41).
    long_mode = vlong is not None and (value is None or vres == vlong or vres is None)
    if long_mode:
        vcol = vlong
        pick = None if (value is None or vres == vlong) else str(value).strip()
        if mcol is not None:
            mlab = _labels(df[mcol])
            mets = [str(m) for m in mlab.dropna().unique()]
            if pick is not None:
                if pick not in mets:
                    low = [m for m in mets if m.lower() == pick.lower()]
                    if len(low) != 1:
                        raise StatsError("[error] metric %r not found in column %r. Available: %s"
                                         % (value, mcol, ", ".join(mets)))
                    pick = low[0]
                df = df[(mlab == pick).values]
                value = pick
            elif len(mets) > 1:
                raise StatsError("[error] this LONG file holds %d metrics (%s). Pass --value <metric> "
                                 "to choose one; pooling them would mix units." % (len(mets), ", ".join(mets)))
            elif mets:
                value = mets[0]
            else:
                value = vcol
        elif pick is not None:
            # CT-R1 SM-F24: a typo'd --value on a LONG file without a metric column used to be
            # accepted silently as the metric's display name
            raise StatsError("[error] value column %r not found. This file has a %r column but no "
                             "%r column, so --value must be %r or one of: %s"
                             % (value, vlong, metric or "metric", vlong,
                                ", ".join(c for c in cols if c not in labels)))
        else:
            value = vcol
    elif value is None:
        numeric = numeric_columns(df, exclude=labels)
        if len(numeric) != 1:
            raise StatsError("[error] specify --value (one of: %s)" % ", ".join(numeric) if numeric
                             else "[error] no numeric value column found")
        vcol = value = numeric[0]
    else:
        if vres is None:
            raise StatsError(f"[error] value column {value!r} not found. Columns: {sorted(cols)}")
        vcol = value = vres

    rows_in = int(len(df))
    out = pd.DataFrame({"group": _labels(df[gcol]).values})
    if scol is not None:
        out["subgroup"] = _labels(df[scol]).values
    out["replicate"] = _labels(df[rcol]).values if rcol is not None else np.nan
    num, nbad, comma = _numbers(df[vcol])
    out["value"] = num.values
    dropped, notes = [], []
    if comma:
        notes.append("Decimal commas in %r were read as decimal points." % vcol)

    def _drop(mask, reason):
        nonlocal out
        n = int(mask.sum())
        if n:
            dropped.append((n, reason))
            out = out[~mask.values]

    _drop(out["group"].isna(), "no %s label" % gcol)
    if scol is not None:
        _drop(out["subgroup"].isna(), "no %s label" % scol)
    blank_v = out["value"].isna()
    if blank_v.any():
        n_text = min(nbad, int(blank_v.sum()))
        why = "no numeric %s value" % vcol
        if n_text:
            why += " (%d not a number, %d empty)" % (n_text, int(blank_v.sum()) - n_text)
        _drop(blank_v, why)
    # CT-R1 SM-F6: rows with a blank plate label, when other rows have one, used to be drawn
    # and summarised but left out of the test. They are now left out everywhere, and counted.
    if out["replicate"].notna().any() and out["replicate"].isna().any():
        mask = out["replicate"].isna()
        gone = [g for g in dict.fromkeys(out.loc[mask, "group"]) if not (out["group"][~mask] == g).any()]
        why = "blank %s label while other rows have one" % rcol
        if gone:
            why += " (this removes every row of: %s)" % ", ".join(map(str, gone))
        _drop(mask, why)
    out = out.reset_index(drop=True)
    if out.empty:
        raise StatsError("[error] no numeric values after parsing — check your columns."
                         + ("  (%s)" % "; ".join("%s: %s" % (_plural(n, "row"), r) for n, r in dropped)
                            if dropped else ""))
    for n, r in dropped:
        notes.append("%s dropped: %s." % (_plural(n, "row"), r))
    out.attrs["rows_read"] = rows_in
    out.attrs["dropped"] = dropped
    out.attrs["notes"] = notes
    return out, value


def normalize(df, group, value, replicate, metric):
    """Return a tidy frame with columns: group, replicate, value (float) — long or wide input.
    `value` may be None in wide mode only if there is exactly one numeric column.
    Rows that cannot be used are counted: `out.attrs["dropped"]` = [(n, reason), ...] and
    `out.attrs["notes"]` = ready-to-show sentences (CT-R1 SM-F1)."""
    return _normalize_core(df, group, value, replicate, metric)


def data_notes(df):
    """The "N rows dropped: reason." sentences recorded by normalize() / normalize_grouped()."""
    return list(getattr(df, "attrs", {}).get("notes", []))


def resolve_order(order, present, what="--order"):
    """The analysis order: the names asked for, de-duplicated, each of which must exist.
    A typo used to drop that sample silently and change the test (CT-R1 SM-F24, web F8)."""
    present_l = list(dict.fromkeys(present))
    if not order:
        return present_l
    want = list(dict.fromkeys(str(g).strip() for g in order if str(g).strip() != ""))
    unknown = [g for g in want if g not in set(present_l)]
    if unknown:
        raise StatsError("[error] %s names %s not in the data: %s. Names in the data: %s"
                         % (what, "a sample that is" if len(unknown) == 1 else "samples that are",
                            ", ".join(repr(u) for u in unknown), ", ".join(map(str, present_l))))
    return want


def _load(data, text_columns):
    """A DataFrame is used as given (no file round trip: CT-R1 DA-F1/F2); a path is read."""
    if isinstance(data, pd.DataFrame):
        return data, {"note": "in-memory table, %d rows." % len(data), "rows": int(len(data))}
    return read_table(data, text_columns=text_columns, return_info=True)


# --------------------------------------------------------------------- summaries
def _ci95(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return (np.nan, np.nan)
    sem = st.sem(x)
    h = sem * st.t.ppf(0.975, n - 1)
    return (float(np.mean(x) - h), float(np.mean(x) + h))


def describe(values):
    x = np.asarray(values, float)
    n = len(x)
    lo, hi = _ci95(x)
    m = float(np.mean(x)) if n else np.nan
    sd = float(np.std(x, ddof=1)) if n > 1 else np.nan
    q1, q3 = (np.percentile(x, [25, 75]) if n else (np.nan, np.nan))
    return {
        "n": n, "mean": m, "sd": sd,
        "sem": float(st.sem(x)) if n > 1 else np.nan,
        "ci95_lo": lo, "ci95_hi": hi,
        "median": float(np.median(x)) if n else np.nan,
        "q1": float(q1), "q3": float(q3), "iqr": float(q3 - q1) if n else np.nan,
        "min": float(np.min(x)) if n else np.nan, "max": float(np.max(x)) if n else np.nan,
        "cv_pct": float(100 * sd / m) if (n > 1 and m) else np.nan,
    }


def group_summary(df, order, unit=None):
    """Per-sample descriptives. The first block is PER PLAQUE (names and meaning unchanged);
    the `unit_*` block describes the statistical unit -- the plate means when the file has
    plates (or the plaques when it has none / when unit="plaque") -- i.e. the numbers the test
    and the figure's bar and whisker use (CT-R1 SM-F7, DA-F12)."""
    rm = replicate_means(df)
    per_plate = rm is not None and unit != "plaque"
    rows = []
    for g in order:
        d = describe(df.loc[df["group"] == g, "value"].values)
        d["group"] = g
        d["n_replicates"] = df.loc[df["group"] == g, "replicate"].nunique(dropna=True)
        u = describe(rm.loc[rm["group"] == g, "value"].values if per_plate
                     else df.loc[df["group"] == g, "value"].values)
        d.update({"unit": "plate" if per_plate else "plaque", "n_units": u["n"],
                  "unit_mean": u["mean"], "unit_sd": u["sd"], "unit_sem": u["sem"],
                  "unit_ci95_lo": u["ci95_lo"], "unit_ci95_hi": u["ci95_hi"]})
        rows.append(d)
    cols = ["group", "n", "n_replicates", "mean", "sd", "sem", "ci95_lo", "ci95_hi",
            "median", "q1", "q3", "iqr", "min", "max", "cv_pct",
            "unit", "n_units", "unit_mean", "unit_sd", "unit_sem", "unit_ci95_lo", "unit_ci95_hi"]
    return pd.DataFrame(rows)[cols]


def replicate_means(df):
    """Per-(group, replicate) mean value — the plate-level table used for correct stats."""
    if df["replicate"].isna().all():
        return None
    rm = (df.dropna(subset=["replicate"])
            .groupby(["group", "replicate"], as_index=False)
            .agg(value=("value", "mean"), n_plaques=("value", "size")))
    return rm


# ------------------------------------------------------------------- statistics
def stars(p):
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "n/a"       # a test that did not run must not read as 'not significant'
    return "***" if p < 1e-3 else "**" if p < 1e-2 else "*" if p < 5e-2 else "ns"


def cohens_d(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return np.nan
    sp = math.sqrt(((na - 1) * np.var(a, ddof=1) + (nb - 1) * np.var(b, ddof=1)) / (na + nb - 2))
    return float((np.mean(a) - np.mean(b)) / sp) if sp else np.nan


def _eta_squared(groups_values):
    """eta^2 effect size for one-way ANOVA = SS_between / SS_total."""
    allv = np.concatenate([np.asarray(g, float) for g in groups_values])
    grand = float(allv.mean())
    ssb = sum(len(g) * (float(np.mean(g)) - grand) ** 2 for g in groups_values)
    sst = float(np.sum((allv - grand) ** 2))
    return float(ssb / sst) if sst else float("nan")


def dunn(groups):
    """Dunn's post-hoc after Kruskal–Wallis, with tie correction; returns {(i,j): p_holm}."""
    labels = list(groups)
    allv = np.concatenate([np.asarray(groups[g], float) for g in labels])
    ranks = st.rankdata(allv)
    N = len(allv)
    idx, rbar, n = {}, {}, {}
    pos = 0
    for g in labels:
        k = len(groups[g])
        rr = ranks[pos:pos + k]
        idx[g] = rr; rbar[g] = rr.mean(); n[g] = k; pos += k
    _, counts = np.unique(allv, return_counts=True)
    ties = np.sum(counts ** 3 - counts)
    sigma2 = (N * (N + 1) / 12.0) - ties / (12.0 * (N - 1))
    raw = {}
    for a, b in itertools.combinations(labels, 2):
        se = math.sqrt(sigma2 * (1.0 / n[a] + 1.0 / n[b]))
        z = (rbar[a] - rbar[b]) / se if se else 0.0
        raw[(a, b)] = 2 * st.norm.sf(abs(z))
    return _holm(raw)


def pairwise_mwu(groups):
    raw = {}
    for a, b in itertools.combinations(groups, 2):
        try:
            raw[(a, b)] = float(st.mannwhitneyu(groups[a], groups[b], alternative="two-sided").pvalue)
        except ValueError:
            raw[(a, b)] = np.nan
    return _holm(raw)


def tukey(groups):
    """Tukey HSD (Tukey-Kramer for unequal n). Groups with fewer than 2 values cannot be
    tested: they get p = NaN (reported as n/a) instead of crashing scipy (AUDIT-2026-10.md)."""
    labels = list(groups)
    ok = [g for g in labels if len(groups[g]) >= 2]
    out = {}
    if len(ok) >= 2:
        res = st.tukey_hsd(*[np.asarray(groups[g], float) for g in ok])
        for i, j in itertools.combinations(range(len(ok)), 2):
            out[(ok[i], ok[j])] = float(res.pvalue[i, j])
    for i, j in itertools.combinations(range(len(labels)), 2):
        out.setdefault((labels[i], labels[j]), float("nan"))
    return out


def games_howell(groups):
    """Games-Howell pairwise test (unequal variances), via the studentized range
    distribution with Welch-Satterthwaite degrees of freedom."""
    labels = [g for g in groups if len(groups[g]) >= 2]
    k = len(labels)
    out = {}
    for a, b in itertools.combinations(labels, 2):
        x, y = np.asarray(groups[a], float), np.asarray(groups[b], float)
        na, nb = len(x), len(y)
        va, vb = x.var(ddof=1) / na, y.var(ddof=1) / nb
        se = math.sqrt(va + vb)
        if se == 0:
            out[(a, b)] = float("nan"); continue
        t = abs(x.mean() - y.mean()) / se
        df = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
        out[(a, b)] = float(st.studentized_range.sf(t * math.sqrt(2.0), k, df))
    for a, b in itertools.combinations(list(groups), 2):
        out.setdefault((a, b), float("nan"))
    return out


def welch_anova_p(gv):
    """Welch's one-way ANOVA p-value (unequal variances)."""
    gv = [np.asarray(v, float) for v in gv if len(v) >= 2]
    k = len(gv)
    if k < 2:
        return float("nan")
    n = np.array([len(v) for v in gv], float)
    m = np.array([v.mean() for v in gv])
    s2 = np.array([v.var(ddof=1) for v in gv])
    if np.any(s2 == 0):
        return float("nan")
    w = n / s2
    mw = (w * m).sum() / w.sum()
    num = ((w * (m - mw) ** 2).sum()) / (k - 1)
    lam = (3.0 / (k * k - 1)) * (((1 - w / w.sum()) ** 2) / (n - 1)).sum()
    den = 1 + 2.0 * (k - 2) / 3.0 * lam
    F = num / den
    df2 = 1.0 / lam if lam > 0 else float("inf")
    return float(st.f.sf(F, k - 1, df2))


def _holm(raw):
    items = [(k, v) for k, v in raw.items() if v == v]  # drop nan
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    adj, prev = {}, 0.0
    for rank, (k, p) in enumerate(items):
        a = min(1.0, (m - rank) * p)
        a = max(a, prev); prev = a
        adj[k] = a
    for k, v in raw.items():
        adj.setdefault(k, v)
    return adj


def hedges_g(a, b):
    """Hedges' g: Cohen's d times the small-sample correction J = 1 - 3 / (4 (na + nb - 2) - 1).
    At 3 vs 3 plates d overstates the effect by 25 % (CT-R1 SM-F12)."""
    d = cohens_d(a, b)
    dfree = len(a) + len(b) - 2
    if d != d or dfree < 2:
        return float("nan")
    return float(d * (1.0 - 3.0 / (4.0 * dfree - 1.0)))


def _welch_se_df(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    se = math.sqrt(va + vb)
    den = va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)
    return se, ((va + vb) ** 2 / den if den > 0 else float("nan"))


def tost_p(a, b, margin):
    """Two one-sided Welch t-tests (TOST) for equivalence within +/- margin: the p-value is the
    larger of the two one-sided p-values; p < 0.05 means the difference of means lies inside
    (-margin, +margin) with 95 % confidence. NaN when a side has < 2 values or no variance."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or len(b) < 2 or not margin or margin <= 0:
        return float("nan")
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p1 = st.ttest_ind(a + margin, b, equal_var=False, alternative="greater").pvalue
            p2 = st.ttest_ind(a - margin, b, equal_var=False, alternative="less").pvalue
    return float(max(p1, p2)) if (p1 == p1 and p2 == p2) else float("nan")


def dunnett(groups, control, seed=7):
    """Dunnett's many-to-one test: every group vs `control` (scipy.stats.dunnett, seeded so a
    re-run prints the same digits). Returns ({(g, control): p}, {(g, control): (lo, hi)}) where
    (lo, hi) is the SIMULTANEOUS 95 % CI of mean(g) - mean(control). Groups with fewer than 2
    values cannot be tested (NaN)."""
    labels = [g for g in groups if g != control]
    pv = {(g, control): float("nan") for g in labels}
    ci = {(g, control): (float("nan"), float("nan")) for g in labels}
    ok = [g for g in labels if len(groups[g]) >= 2]
    ctrl = np.asarray(groups.get(control, []), float)
    if len(ctrl) >= 2 and ok:
        import warnings
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            try:
                res = st.dunnett(*[np.asarray(groups[g], float) for g in ok], control=ctrl,
                                 random_state=seed)
                c = res.confidence_interval(confidence_level=0.95)
                for i, g in enumerate(ok):
                    pv[(g, control)] = float(res.pvalue[i])
                    ci[(g, control)] = (float(c.low[i]), float(c.high[i]))
            except Exception:                                     # noqa: BLE001 -- degenerate data
                pass
    return pv, ci


def _power_two_sample(d, n, alpha=0.05):
    """Power of a two-sided two-sample t-test with n per group for a standardised difference d
    (noncentral t)."""
    dfree = 2 * n - 2
    nc = d * math.sqrt(n / 2.0)
    tc = st.t.ppf(1 - alpha / 2.0, dfree)
    return float(st.nct.sf(tc, dfree, nc) + st.nct.cdf(-tc, dfree, nc))


def plates_needed(d, power=0.80, alpha=0.05, n_max=1000):
    """Smallest n per group that detects a standardised difference d with the given power
    (None when it would take more than n_max)."""
    if not (d == d) or d <= 0:
        return None
    for n in range(2, n_max + 1):
        if _power_two_sample(d, n, alpha) >= power:
            return n
    return None


def power_summary(groups, power=0.80, alpha=0.05):
    """What this design can detect (CT-R1 B3), from the observed unit-level pooled SD:
    the smallest difference found with 80 % power at the current n per group, and the n per
    group needed for the largest and the smallest observed pairwise difference (two-sided
    alpha = 0.05, two-sample t, noncentral t). {"available": False, "reason": ...} when the
    data cannot support it (a single unit per group, no spread)."""
    use = {g: np.asarray(v, float) for g, v in groups.items() if len(v) >= 2}
    if len(use) < 2:
        return {"available": False, "reason": "it needs at least two samples with 2 or more units"}
    dfw = sum(len(v) - 1 for v in use.values())
    sd = math.sqrt(sum((len(v) - 1) * v.var(ddof=1) for v in use.values()) / dfw)
    if not (sd > 0):
        return {"available": False, "reason": "the units show no spread (pooled SD = 0)"}
    n = int(min(len(v) for v in use.values()))
    from scipy.optimize import brentq
    d_det = brentq(lambda d: _power_two_sample(d, n, alpha) - power, 1e-6, 1e4)
    means = {g: float(np.mean(v)) for g, v in groups.items() if len(v) >= 1}
    diffs = sorted(abs(means[a] - means[b]) for a, b in itertools.combinations(means, 2))
    diffs = [d for d in diffs if d > 0]
    out = {"available": True, "pooled_sd": float(sd), "n_per_group": n, "power": power, "alpha": alpha,
           "equal_n": len({len(v) for v in use.values()}) == 1,
           "detectable_diff": float(d_det * sd)}
    if diffs:
        out.update({"largest_diff": diffs[-1], "n_for_largest": plates_needed(diffs[-1] / sd, power, alpha),
                    "smallest_diff": diffs[0], "n_for_smallest": plates_needed(diffs[0] / sd, power, alpha)})
    return out


def plate_variance_share(df):
    """Share of the within-sample variance that lies BETWEEN plates: the one-way random-effects
    intraclass correlation of plaques within plates, pooled over samples (plates nested in
    sample[/subgroup]; ANOVA estimator with the unbalanced-design n0). None when the file has no
    plates or too few to estimate it. It shows why the plate is the unit (CT-R1 B5)."""
    if "replicate" not in df.columns or df["replicate"].isna().all():
        return None
    d = df.dropna(subset=["replicate"])
    gk = ["group"] + (["subgroup"] if "subgroup" in d.columns else [])
    cell = d.groupby(gk + ["replicate"])["value"].agg(["size", "mean", "var"]).reset_index()
    N, b = int(cell["size"].sum()), int(len(cell))
    a = int(cell.groupby(gk).ngroups)
    if b - a < 1 or N - b < 1:
        return None
    ss_p, corr = 0.0, 0.0
    for _, sub in cell.groupby(gk):
        ng = float(sub["size"].sum())
        gm = float((sub["size"] * sub["mean"]).sum() / ng)
        ss_p += float((sub["size"] * (sub["mean"] - gm) ** 2).sum())
        corr += float((sub["size"] ** 2).sum() / ng)
    ss_e = float(((cell["size"] - 1) * cell["var"].fillna(0.0)).sum())
    msb, msw = ss_p / (b - a), ss_e / (N - b)
    n0 = (N - corr) / (b - a)
    vb = max(0.0, (msb - msw) / n0) if n0 > 0 else 0.0
    tot = vb + msw
    return {"icc": float(vb / tot) if tot > 0 else float("nan"), "var_between_plates": float(vb),
            "var_within_plate": float(msw), "n0": float(n0), "n_plates": b, "n_plaques": N}


def compact_letters(order, posthoc, alpha=0.05):
    """Compact letter display from adjusted pairwise p-values (insert-absorb algorithm,
    Piepho 2004): samples that share a letter are NOT significantly different; samples with no
    letter in common are. A sample none of whose comparisons could be run gets "" (n/a); a
    single untestable pair counts as 'not different'."""
    def _p(a, b):
        v = posthoc.get((a, b), posthoc.get((b, a)))
        return v if (v is not None and v == v) else float("nan")
    live = [g for g in order if any(_p(g, h) == _p(g, h) for h in order if h != g)]
    cols = [set(live)] if live else []
    for a, b in itertools.combinations(live, 2):
        if not (_p(a, b) < alpha):
            continue
        new = []
        for c in cols:                                    # insert: split every column holding both
            if a in c and b in c:
                new.append(c - {a}); new.append(c - {b})
            else:
                new.append(c)
        cols = []
        for c in sorted(new, key=len, reverse=True):      # absorb: drop columns inside another one
            if c and not any(c <= k for k in cols):
                cols.append(c)
    cols.sort(key=lambda c: min(order.index(g) for g in c))
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = {g: "" for g in order}
    for i, c in enumerate(cols):
        for g in c:
            out[g] += alphabet[i % len(alphabet)]
    return out


def pairwise_table(groups, posthoc, omni, margin=None):
    """One row per tested pair on the statistical UNIT (plate means, or plaques): means, the
    difference A - B with its 95 % CI, Cohen's d, Hedges' g, the adjusted p, and -- with an
    equivalence margin -- the TOST p and verdict (CT-R1 B2, B4). `ci_method` says what the CI is:
    simultaneous for Tukey / Games-Howell / Dunnett (it excludes 0 exactly when p_adj < 0.05),
    a plain Welch-t interval otherwise."""
    name = omni.get("posthoc") or omni.get("test") or ""
    tg = [g for g in groups if len(groups[g]) >= 2]
    kt = len(tg)
    dfw = sum(len(groups[g]) - 1 for g in tg)
    mse = (sum((len(groups[g]) - 1) * np.var(groups[g], ddof=1) for g in tg) / dfw) if dfw > 0 else float("nan")
    dci = omni.get("_dunnett_ci", {})
    qcache = {}

    def _q(k, dfree):
        key = (k, round(float(dfree), 4))
        if key not in qcache:
            qcache[key] = float(st.studentized_range.ppf(0.95, k, dfree))
        return qcache[key]

    rows = []
    for (a, b), p in posthoc.items():
        xa, xb = np.asarray(groups.get(a, []), float), np.asarray(groups.get(b, []), float)
        ma = float(np.mean(xa)) if len(xa) else float("nan")
        mb = float(np.mean(xb)) if len(xb) else float("nan")
        lo = hi = float("nan"); method = ""
        if len(xa) >= 2 and len(xb) >= 2:
            diff = ma - mb
            se, dfree = _welch_se_df(xa, xb)
            with np.errstate(all="ignore"):
                if name == "Tukey HSD" and mse == mse and mse > 0:
                    half = _q(kt, dfw) / math.sqrt(2.0) * math.sqrt(mse * (1.0 / len(xa) + 1.0 / len(xb)))
                    lo, hi, method = diff - half, diff + half, "Tukey simultaneous"
                elif name == "Games-Howell" and se > 0 and dfree == dfree:
                    half = _q(kt, dfree) / math.sqrt(2.0) * se
                    lo, hi, method = diff - half, diff + half, "Games-Howell simultaneous"
                elif name == "Dunnett" and (a, b) in dci:
                    lo, hi = dci[(a, b)]; method = "Dunnett simultaneous"
                elif se > 0 and dfree == dfree:
                    half = float(st.t.ppf(0.975, dfree)) * se
                    lo, hi = diff - half, diff + half
                    method = "Welch t" if omni.get("test") == "Welch t-test" else "Welch t (unadjusted)"
        row = {"group_a": a, "group_b": b, "mean_a": ma, "mean_b": mb, "mean_diff": ma - mb,
               "p_adj": p, "signif": stars(p),
               "n_a": int(len(xa)), "n_b": int(len(xb)),
               "diff_ci95_lo": lo, "diff_ci95_hi": hi, "ci_method": method,
               "cohens_d": cohens_d(xa, xb), "hedges_g": hedges_g(xa, xb)}
        if margin:
            tp = tost_p(xa, xb, margin)
            row["tost_p"] = tp
            row["equivalence"] = ("not testable" if tp != tp else
                                  "equivalent within ±%g" % margin if tp < 0.05 else "not shown equivalent")
        rows.append(row)
    return pd.DataFrame(rows)


def _check_choice(value, allowed, flag):
    v = "auto" if value is None else str(value).strip().lower()
    if v not in allowed:
        raise StatsError("%s must be one of %s (got %r)." % (flag, ", ".join(allowed), value))
    return v


def _quiet(fn, *a, **kw):
    """Run a scipy test without its degenerate-data warnings; NaN when it cannot be computed."""
    import warnings
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        try:
            return fn(*a, **kw)
        except ValueError:
            return None


def run_stats(df, order, unit, parametric, equal_var="auto", posthoc="auto", control=None,
              equivalence_margin=None):
    """Compute normality, an omnibus test, and pairwise post-hoc p-values on the chosen unit.

    Returns (omni, posthoc, unit, have_rep) as always. New keyword arguments (all optional):
      equal_var  auto | yes | no  -- auto keeps the Levene rule; no = Welch ANOVA + Games-Howell;
                                     yes = classic ANOVA + Tukey (CT-R1 SM-F5).
      posthoc    auto | dunnett   -- dunnett = every sample vs `control` (default: first in order).
      equivalence_margin          -- adds a TOST equivalence test per pair (same units as the data).
    New keys in `omni`: posthoc, warnings (complete list), notes, variance_rule, choice_note,
    equal_var, sd_ratio, untestable, pairwise (records), power, icc, letters, control."""
    unit = _check_choice(unit, ("auto", "replicate", "plaque"), "--unit")
    parametric = _check_choice(parametric, ("auto", "parametric", "nonparametric"), "--parametric")
    equal_var = _check_choice({True: "yes", False: "no"}.get(equal_var, equal_var),
                              ("auto", "yes", "no"), "--equal-var")
    posthoc_req = _check_choice(posthoc, ("auto", "dunnett"), "--posthoc")
    rm = replicate_means(df)
    have_rep = rm is not None
    # CT-R1 SM-F3 / web F3: '--unit replicate' without plates used to test plaques and report
    # the result as plate-level.
    if unit == "replicate" and not have_rep:
        raise StatsError("no plate/replicate column: --unit replicate needs a plate id on every row "
                         "(a 'replicate' column). Add one, or choose --unit plaque to test the plaques "
                         "themselves (pseudoreplicated: plaques on one plate are not independent).")
    unit_requested = unit
    # CT-R1 SM-F4 / DA-F9: a sample with a single plate no longer flips the whole analysis to
    # per-plaque statistics. The plate stays the unit; that sample's comparisons are n/a.
    if unit == "auto":
        unit = "replicate" if have_rep else "plaque"
    src = rm if unit == "replicate" else df
    uw = "plate" if unit == "replicate" else "plaque"
    groups = {g: np.asarray(src.loc[src["group"] == g, "value"].values, float) for g in order}
    ns = {g: len(v) for g, v in groups.items()}
    tg = [g for g in order if ns[g] >= 2]                    # samples that can be tested
    untestable = [g for g in order if ns[g] < 2]

    warns, notes = [], []
    if unit == "plaque":
        if have_rep:
            warns.append("Statistical unit is the PLAQUE because --unit plaque was chosen, although the "
                         "data have plates: plaques from the same plate are not independent "
                         "(pseudoreplication), so p-values are anti-conservative. Use --unit replicate.")
        else:
            warns.append("Statistical unit is the PLAQUE, not the plate: plaques from the same plate are not "
                         "independent (pseudoreplication), so p-values are anti-conservative. Add a "
                         "'replicate' (plate) column and use --unit replicate.")
    for g in untestable:
        warns.append("%s has %s: it cannot be tested; add %ss (its comparisons are n/a)."
                     % (g, _plural(ns[g], uw), uw))

    # normality (Shapiro per group) + equal variance (Levene) to guide parametric vs not
    normal = {}
    for g, v in groups.items():
        if len(v) < 3 or np.ptp(v) == 0:
            normal[g] = np.nan
        elif len(v) > 5000:
            # CT-R1 SM-F24: above 5,000 values Shapiro was skipped and the sample counted as normal
            sub = np.random.default_rng(7).choice(v, 5000, replace=False)
            r = _quiet(st.shapiro, sub)
            normal[g] = float(r.pvalue) if r is not None else np.nan
            notes.append("Shapiro–Wilk for %s was run on a seeded random subsample of 5,000 of its "
                         "%s values (the test is not valid above 5,000)." % (g, format(len(v), ",")))
        else:
            r = _quiet(st.shapiro, v)
            normal[g] = float(r.pvalue) if r is not None else np.nan
    vals = [groups[g] for g in tg]
    r = _quiet(st.levene, *vals) if len(vals) >= 2 else None
    levene_p = float(r.pvalue) if r is not None else np.nan
    sds = [float(np.std(groups[g], ddof=1)) for g in tg]
    if len(sds) >= 2 and max(sds) > 0:
        sd_ratio = float(max(sds) / min(sds)) if min(sds) > 0 else float("inf")
    else:
        sd_ratio = float("nan")
    all_normal = all((p != p) or p > 0.05 for p in normal.values())
    min_n = min(ns.values()) if ns else 0
    if parametric == "auto":
        # At small replicate n (the usual case: ~3 plates) Shapiro–Wilk is uninformative AND
        # non-parametric tests are underpowered — Mann–Whitney cannot reach p<0.05 at 3 vs 3, and
        # Kruskal–Wallis p is floored/approximate at small N. So default to PARAMETRIC on the plate
        # means, as SuperPlots recommend (Lord et al. 2020; Kenny & Schoen 2021); only let Shapiro
        # pick non-parametric once there are enough replicates for it to mean something (>=8 per
        # group). Unequal variances alone no longer send normal data to a rank test: Welch's
        # ANOVA / Games-Howell handle them (CT-R1 SM-F5).
        use_param = True if min_n < 8 else bool(all_normal)
        if min_n < 8:
            choice = ("With fewer than 8 %ss per sample (here %d) a parametric test is used on the %s: "
                      "Shapiro–Wilk is unreliable and rank tests are underpowered at this size "
                      "(Mann–Whitney cannot go below p = 0.10 at 3 vs 3). This follows SuperPlots "
                      "(Lord et al. 2020). Override with `--parametric`."
                      % (uw, min_n, "plate means" if unit == "replicate" else "plaque values"))
        elif use_param:
            choice = ("Every sample has at least 8 %ss and none fails Shapiro–Wilk (all p > 0.05), so a "
                      "parametric test is used. Override with `--parametric`." % uw)
        else:
            bad = [g for g, p in normal.items() if p == p and p <= 0.05]
            choice = ("With at least 8 %ss per sample, Shapiro–Wilk rejects normality for %s (p ≤ 0.05), "
                      "so a rank-based test is used. Override with `--parametric`." % (uw, ", ".join(map(str, bad))))
    else:
        use_param = (parametric == "parametric")
        choice = "`--parametric %s` was chosen by the user." % parametric

    k = len(order)
    ctrl = None
    if posthoc_req == "dunnett" and k > 2:
        if parametric == "nonparametric":
            raise StatsError("Dunnett's test is parametric: drop --parametric nonparametric, or drop "
                             "--posthoc dunnett to get Dunn's test.")
        if equal_var == "no":
            raise StatsError("Dunnett's test assumes similar variances, so it cannot be combined with "
                             "--equal-var no. Drop --posthoc dunnett to get Games-Howell (all pairs).")
        ctrl = order[0] if control in (None, "") else str(control)
        if ctrl not in order:
            raise StatsError("control %r is not one of the samples: %s" % (control, ", ".join(map(str, order))))
        if not use_param:
            notes.append("Shapiro–Wilk rejects normality for at least one sample; Dunnett's test "
                         "(parametric) was run because --posthoc dunnett was chosen.")
        use_param = True
        choice = "`--posthoc dunnett` was chosen by the user (a parametric test). " + choice \
            if parametric == "auto" else choice

    if not use_param and min_n < 4:
        warns.append("Non-parametric test with <4 per group: significance can be UNREACHABLE "
                     "(Mann–Whitney floor p=0.10 at 3 vs 3) or floored/approximate (Kruskal–Wallis at "
                     "small N). With few plates prefer a parametric test on the plate means.")

    omni = {"unit": unit, "unit_requested": unit_requested, "n_per_group": ns, "min_n": min_n,
            "levene_p": levene_p, "sd_ratio": sd_ratio, "equal_var": equal_var,
            "normality_p": normal, "parametric_used": use_param, "warnings": warns, "notes": notes,
            "untestable": untestable, "choice_note": choice, "posthoc": None, "variance_rule": "",
            "control": ctrl,
            # descriptives of the values the test actually used (plate means when
            # unit == 'replicate'), so the report can quote the tested numbers (PT-43)
            "unit_stats": {g: {"mean": float(np.mean(v)) if len(v) else float("nan"),
                               "sd": float(np.std(v, ddof=1)) if len(v) > 1 else float("nan"),
                               "sem": float(np.std(v, ddof=1) / math.sqrt(len(v))) if len(v) > 1 else float("nan"),
                               "n": int(len(v))} for g, v in groups.items()}}
    lev_txt = "Levene p = %s" % fmt_p(levene_p)
    if k == 2:
        a, b = groups[order[0]], groups[order[1]]
        omni["test"] = "Welch t-test" if use_param else "Mann–Whitney U"
        p = np.nan
        if len(a) >= 2 and len(b) >= 2:
            r = (_quiet(st.ttest_ind, a, b, equal_var=False) if use_param
                 else _quiet(st.mannwhitneyu, a, b, alternative="two-sided"))
            p = float(r.pvalue) if r is not None else np.nan
            if p != p:
                notes.append("The two samples have no spread (identical values), so no test is possible (p = n/a).")
        omni["p"] = p
        omni["effect"] = {"cohens_d": cohens_d(a, b), "hedges_g": hedges_g(a, b)}
        omni["variance_rule"] = ("Welch's t-test does not assume equal variances." if use_param
                                 else "Mann–Whitney U is rank-based (no variance assumption).")
        if posthoc_req == "dunnett":
            notes.append("With two samples Dunnett's test reduces to a two-sample test; the %s was used." % omni["test"])
        posthoc = {(order[0], order[1]): omni["p"]}
    elif k > 2:
        gv = [groups[g] for g in tg]
        if len(tg) < k and len(tg) >= 2:
            notes.append("The omnibus test covers the %d samples with at least 2 %ss (%s)."
                         % (len(tg), uw, ", ".join(map(str, tg))))
        posthoc = {}
        if len(tg) < 2:
            omni["test"] = "n/a (need ≥2 samples with ≥2 %ss)" % uw; omni["p"] = np.nan
        elif use_param:
            # Classic ANOVA + Tukey assume equal variances. When Levene rejects that, use
            # Welch's ANOVA + Games-Howell instead of printing Levene and ignoring it
            # (AUDIT-2026-10.md, PT-42). Equal-variance data takes the old path unchanged.
            # CT-R1 SM-F5: Levene cannot reject at 3 plates per group, so the user can now force
            # either method with --equal-var, and `auto` warns when the SDs differ a lot.
            lev_unequal = (levene_p == levene_p) and levene_p < 0.05
            if ctrl is not None:
                welch = False
                rule = ("Dunnett's test pools the variance of all samples (it assumes similar variances; %s)."
                        % lev_txt)
            elif equal_var == "no":
                welch = True
                rule = "`--equal-var no`: Welch's ANOVA + Games-Howell (no equal-variance assumption) by request."
            elif equal_var == "yes":
                welch = False
                rule = "`--equal-var yes`: classic ANOVA + Tukey HSD (equal variances assumed) by request; %s." % lev_txt
            else:
                welch = lev_unequal
                rule = ("`--equal-var auto`: %s (< 0.05), so Welch's ANOVA + Games-Howell were used."
                        % lev_txt if welch else
                        "`--equal-var auto`: %s (not < 0.05), so equal variances were assumed "
                        "(classic ANOVA + Tukey HSD)." % lev_txt)
            omni["effect"] = {"eta_squared": _eta_squared(gv)}
            if welch:
                pw = welch_anova_p(gv)
                if pw != pw:
                    # CT-R1 SM-F11: an undefined Welch omnibus (a sample with zero variance) used to
                    # print "p = n/a" beside significant Games-Howell pairs
                    welch = False
                    rule += (" Welch's ANOVA is undefined here (a sample has zero variance), so classic "
                             "ANOVA + Tukey HSD were used instead.")
                    notes.append("Welch's ANOVA could not be computed (a sample has zero variance); "
                                 "classic ANOVA + Tukey HSD were used instead.")
                else:
                    omni["test"] = "Welch ANOVA"; omni["p"] = pw
                    posthoc = games_howell({g: groups[g] for g in order})
                    omni["posthoc"] = "Games-Howell"
                    if equal_var == "auto":
                        warns.append("Levene p = %.3f: group variances differ, so Welch's ANOVA and "
                                     "Games-Howell (no equal-variance assumption) were used." % levene_p)
            if not welch:
                omni["test"] = "one-way ANOVA"
                r = _quiet(st.f_oneway, *gv)
                omni["p"] = float(r.pvalue) if r is not None else np.nan
                if ctrl is not None:
                    posthoc, omni["_dunnett_ci"] = dunnett({g: groups[g] for g in order}, ctrl)
                    omni["posthoc"] = "Dunnett"
                else:
                    posthoc = _quiet(tukey, {g: groups[g] for g in order}) or {}
                    omni["posthoc"] = "Tukey HSD"
                if omni["p"] != omni["p"]:
                    notes.append("All values are identical within and between the samples, so no test "
                                 "is possible (p = n/a).")
                # the SD-ratio warning: pooled-variance methods at an n where Levene cannot object
                if sd_ratio == sd_ratio and sd_ratio > 3 and equal_var != "yes":
                    n_txt = ("%d %ss" % (min(ns[g] for g in tg), uw))
                    warns.append(
                        "The largest sample SD is %s the smallest (%s level). Levene's test cannot "
                        "detect unequal variances with %s per group; consider --equal-var no "
                        "(Welch's ANOVA + Games-Howell)%s."
                        % ("%.1f×" % sd_ratio if math.isfinite(sd_ratio) else "far larger than",
                           uw, n_txt, "" if ctrl is None else " instead of Dunnett"))
            omni["variance_rule"] = rule
        else:
            hres = _quiet(st.kruskal, *gv)
            N = sum(len(x) for x in gv); kk = len(gv)
            omni["test"] = "Kruskal–Wallis"
            omni["p"] = float(hres.pvalue) if hres is not None else np.nan
            if hres is None or omni["p"] != omni["p"]:
                # CT-R1 SM-F11: scipy raises "All numbers are identical in kruskal"
                notes.append("All values are identical, so no test is possible (p = n/a).")
                omni["effect"] = {"epsilon_squared": float("nan")}
            else:
                H = float(hres.statistic)
                # CT-R1 SM-F12: epsilon squared is H / (N - 1). The value printed under this name
                # before was (H - k + 1) / (N - k), which is eta squared (H); both are given now.
                omni["effect"] = {"epsilon_squared": H / (N - 1) if N > 1 else float("nan"),
                                  "eta_squared_H": (H - kk + 1) / (N - kk) if N > kk else float("nan")}
                posthoc = dunn({g: groups[g] for g in tg})
            omni["posthoc"] = "Dunn (Holm)"
            omni["variance_rule"] = "Kruskal–Wallis and Dunn's test are rank-based (no variance assumption)."
        if ctrl is None:
            posthoc = {(a, b): posthoc.get((a, b), posthoc.get((b, a), float("nan")))
                       for a, b in itertools.combinations(order, 2)}
    else:
        omni["test"] = "n/a (need ≥2 groups)"; omni["p"] = np.nan; posthoc = {}

    # ---- beyond the p-values: enriched pairwise table, power, plate variance share, letters
    try:
        margin = float(equivalence_margin) if equivalence_margin not in (None, "") else None
    except (TypeError, ValueError):
        raise StatsError("--equivalence-margin must be a number (got %r)." % (equivalence_margin,))
    if margin is not None and margin <= 0:
        raise StatsError("--equivalence-margin must be greater than 0 (got %r)." % (equivalence_margin,))
    omni["equivalence_margin"] = margin
    pw = pairwise_table(groups, posthoc, omni, margin) if posthoc else pd.DataFrame()
    omni["pairwise"] = pw.to_dict("records")
    omni["power"] = power_summary(groups)
    omni["icc"] = plate_variance_share(df)
    omni["letters"] = compact_letters(list(order), posthoc) if (k > 2 and ctrl is None and posthoc) else {}
    return omni, posthoc, unit, have_rep


# ----------------------------------------------------------------------- plotting
# rcParams of every figure drawn here. They are applied with matplotlib.rc_context inside each
# plotting function, so nothing leaks into the caller's other figures (CT-R1 DA-F18: after one
# Analyze run the Fiji agreement figure changed size and font).
_FIG_RC = {"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42,
           "font.size": 12, "font.family": "sans-serif", "axes.linewidth": 0.9}
# marker shapes for plates: all circles until the palette runs out of colours, then the next
# shape, so no two plates of one figure share colour AND marker (CT-R1 DA-F13, SM-F20)
PLATE_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
BOOT_N, BOOT_SEED = 2000, 7
_INK, _INK2 = "#12211d", "#33413c"


def check_center_error(center, error):
    """Validate --center / --error together; returns the error bar actually drawn.
    A mean-based spread (SD, SEM) around a MEDIAN is refused (CT-R1 SM-F8, DA-F16)."""
    center = "mean" if center in (None, "") else str(center).lower()
    error = "auto" if error in (None, "") else str(error).lower()
    if center not in ("mean", "median"):
        raise StatsError("--center must be mean or median (got %r)." % center)
    if error not in ("auto", "sd", "sem", "ci95", "iqr", "none"):
        raise StatsError("--error must be one of auto, sd, sem, ci95, iqr, none (got %r)." % error)
    if error == "auto":
        error = "iqr" if center == "median" else "sem"
    if center == "median" and error in ("sd", "sem"):
        raise StatsError("--error %s describes the spread around a MEAN and cannot be drawn around a "
                         "median. With --center median use --error iqr, ci95 (bootstrap CI of the "
                         "median) or none; or use --center mean." % error)
    return error


def clean_palette(palette, needed=0, what="sample"):
    """The palette as a list of valid colours. Hex codes without '#' are accepted; anything that
    is not a colour is an error naming it; a CUSTOM list shorter than the number of colours the
    figure needs is an error saying how many are needed (a named palette cycles, as before)
    (CT-R1 DA-F13, web F13)."""
    from matplotlib import colors as mcolors
    if palette is None or (isinstance(palette, (list, tuple)) and not len(palette)):
        return list(OKABE_ITO)
    if isinstance(palette, str):
        if palette.strip().lower() in PALETTES:
            return list(PALETTES[palette.strip().lower()])
        palette = [x for x in palette.replace(";", ",").split(",")]
    out = []
    for c in palette:
        t = c.strip() if isinstance(c, str) else c
        if isinstance(t, str) and t == "":
            continue
        if isinstance(t, str) and not mcolors.is_color_like(t) and mcolors.is_color_like("#" + t):
            t = "#" + t
        if not mcolors.is_color_like(t):
            raise StatsError("palette entry %r is not a colour. Use hex codes such as #0072B2 "
                             "(comma-separated) or a named palette: %s." % (c, ", ".join(PALETTES)))
        out.append(t)
    if not out:
        return list(OKABE_ITO)
    named = any([str(x).lower() for x in out] == [y.lower() for y in pal] for pal in PALETTES.values())
    if needed and len(out) < needed and not named:
        raise StatsError("the custom palette has %s but this figure needs %d (one per %s). Add %s, "
                         "or choose a named palette."
                         % (_plural(len(out), "colour"), needed, what,
                            _plural(needed - len(out), "more colour")))
    return out


def _plot_opts(opts):
    """Options with every default filled in (GUI dicts may not start from DEFAULTS)."""
    o = dict(DEFAULTS); o.update(opts or {})
    o["_error"] = check_center_error(o.get("center"), o.get("error"))
    o["center"] = "mean" if o.get("center") in (None, "") else str(o["center"]).lower()
    return o


def _boot_median_ci(vals, clusters=None, n_boot=BOOT_N, seed=BOOT_SEED):
    """Seeded percentile-bootstrap 95 % CI of a median. With `clusters` (one array of plaques per
    plate, >= 2 plates) whole PLATES are resampled with replacement and their plaques pooled, so
    the interval respects the plate structure; without plates the plaques are resampled."""
    rng = np.random.default_rng(seed)
    if clusters is not None and len(clusters) >= 2:
        cl = [np.asarray(c, float) for c in clusters]
        m = len(cl)
        meds = [float(np.median(np.concatenate([cl[i] for i in rng.integers(0, m, m)])))
                for _ in range(n_boot)]
    else:
        v = np.asarray(vals, float)
        if len(v) < 2:
            return float("nan"), float("nan")
        meds = np.median(v[rng.integers(0, len(v), (n_boot, len(v)))], axis=1)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    return float(lo), float(hi)


def _center_spread(vals, center, error="auto", clusters=None):
    """Return (centre, low, high) for the group marker.
    centre = mean|median; error bar = sd|sem|ci95|iqr|none (auto → sem for mean, iqr for median).
    Around a median, ci95 is a seeded bootstrap CI of the median (plates resampled when
    `clusters` is given); sd / sem around a median are refused (check_center_error)."""
    error = check_center_error(center, error)
    v = np.asarray(vals, float); n = len(v)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    cen = float(np.median(v)) if center == "median" else float(np.mean(v))
    if error == "none" or n < 2:
        return cen, cen, cen
    if error == "iqr":
        return cen, float(np.percentile(v, 25)), float(np.percentile(v, 75))
    if center == "median":                                   # ci95 of a median: bootstrap
        lo, hi = _boot_median_ci(v, clusters)
        return (cen, lo, hi) if lo == lo else (cen, cen, cen)
    sd = float(np.std(v, ddof=1)); sem = sd / math.sqrt(n)
    half = sd if error == "sd" else (sem * st.t.ppf(0.975, n - 1) if error == "ci95" else sem)
    return cen, cen - half, cen + half


def center_table(df, order, opts, by=("group",)):
    """{key: (centre, low, high, n_units)} exactly as the figure draws the bar and whisker.
    With plates and --center mean the bar is the mean of the PLATE MEANS; with --center median
    it is the median of all plaques of the sample (its IQR, or a plate-cluster bootstrap CI).
    Used by the figure AND by the paste-ready sentence, so both quote the same numbers."""
    o = opts if "_error" in (opts or {}) else _plot_opts(opts)
    center, error = o["center"], o["_error"]
    by = list(by)
    has_rep = not df["replicate"].isna().all()
    out = {}
    for key, sub in df.groupby(by, sort=False):
        key = key if isinstance(key, tuple) else (key,)
        key = key[0] if len(by) == 1 else key
        v = sub["value"].values.astype(float)
        plates = ([g["value"].values.astype(float) for _, g in sub.dropna(subset=["replicate"]).groupby("replicate")]
                  if has_rep else [])
        if center == "median":
            cen, lo, hi = _center_spread(v, "median", error, clusters=plates if len(plates) >= 2 else None)
            n_units = len(plates) if plates else len(v)
        elif plates:
            pm = np.array([float(np.mean(x)) for x in plates])
            cen, lo, hi = _center_spread(pm, "mean", error); n_units = len(pm)
        else:
            cen, lo, hi = _center_spread(v, "mean", error); n_units = len(v)
        out[key] = (cen, lo, hi, n_units)
    return out


_ERR_WORDS = {"sd": "SD", "sem": "SEM", "ci95": "95 % CI", "iqr": "IQR (25th to 75th percentile)"}


def figure_sentence(opts, have_rep, n_units=None, grouped=False):
    """What the marks of the figure are, built from the options actually used (CT-R1 SM-F7,
    DA-F12, web F21/F25). It ends the legend text starter and the report's Figure section.
    No semicolons: the text starter separates its entries with them."""
    o = opts if "_error" in (opts or {}) else _plot_opts(opts)
    center, error = o["center"], o["_error"]
    ns = sorted({int(n) for n in (n_units or []) if n is not None})
    if not ns:
        ntxt = ""
    elif len(ns) == 1:
        ntxt = "%d " % ns[0]
    else:
        ntxt = "%d to %d " % (ns[0], ns[-1])
    bits = []
    if have_rep:
        bits.append("Violins: all plaques.")
        if o.get("show_points", True):
            bits.append("Small points: single plaques.")
        bits.append("Large points: plate means.")
        if center == "median":
            bar = "median of all plaques"
            wh = ("95 % CI of the median (plates resampled, %s bootstrap resamples, seed %d)"
                  % (format(BOOT_N, ","), BOOT_SEED)) if error == "ci95" else _ERR_WORDS.get(error)
            if error == "iqr":
                wh = "IQR of the plaques (25th to 75th percentile)"
        else:
            bar = "mean of the %splate means" % ntxt
            wh = _ERR_WORDS.get(error)
            if wh:
                wh += " of the plate means"
    else:
        bits.append("Violins%s: all plaques." % (" and points" if o.get("show_points", True) else ""))
        if center == "median":
            bar = "median of the plaques"
            wh = ("95 % CI of the median (%s bootstrap resamples of the plaques, seed %d)"
                  % (format(BOOT_N, ","), BOOT_SEED)) if error == "ci95" else _ERR_WORDS.get(error)
        else:
            bar = "mean of the plaques"
            wh = _ERR_WORDS.get(error)
            if wh:
                wh += " of the plaques (plaques on one plate are not independent, so it is too narrow)"
    bits.append("Bar: %s." % bar)
    bits.append("Whisker: %s." % wh if wh else "No whisker.")
    if o.get("show_n", True):
        bits.append("n = plaques, N = plates." if have_rep else "n = plaques.")
    return " ".join(bits)


def _style_axes(ax, opts):
    """Journal-style axes: left+bottom spines by default, or a full frame/box when frame=True."""
    frame = bool(opts.get("frame"))
    for s in ("top", "right"):
        ax.spines[s].set_visible(frame)
    for s in ax.spines.values():
        s.set_linewidth(0.9); s.set_color("#33413c")
    ax.tick_params(width=0.9, color="#33413c", length=4, labelsize=11)
    if opts.get("theme") == "grid":
        ax.yaxis.grid(True, color="#ececec", lw=0.8); ax.set_axisbelow(True)


# ---- layout helpers shared by both figures -------------------------------------------------
def _renderer(fig):
    try:
        return fig.canvas.get_renderer()
    except Exception:                                    # noqa: BLE001
        return fig._get_renderer()


def _text_in(fig, text, **kw):
    """(width, height) in inches of `text` drawn with the given font properties."""
    t = fig.text(0, 0, text, **kw)
    try:
        bb = t.get_window_extent(_renderer(fig))
        return bb.width / fig.dpi, bb.height / fig.dpi
    except Exception:                                    # noqa: BLE001 -- estimate from the font size
        fs = float(kw.get("fontsize", 10))
        lines = str(text).split("\n")
        return max(len(x) for x in lines) * fs * 0.6 / 72.0, len(lines) * fs * 1.25 / 72.0
    finally:
        t.remove()


def _axes_in(fig, ax):
    bb = ax.get_position()
    w, h = fig.get_size_inches()
    return bb.width * w, bb.height * h


def _log_guard(values, opts, what="value"):
    """(mask of values to DRAW, caption or None). On a log axis values <= 0 cannot be drawn:
    refuse and say how many, unless the user asked to hide them (CT-R1 SM-F13, DA-F15)."""
    v = np.asarray(values, float)
    if not opts.get("log_y"):
        return np.ones(len(v), bool), None
    bad = int(np.sum(v <= 0))
    if not bad:
        return np.ones(len(v), bool), None
    if not opts.get("log_y_drop_nonpositive"):
        raise StatsError("%s of %d are zero or negative and cannot be drawn on a log axis. Turn the "
                         "log axis off, or pass --log-y-drop-nonpositive to hide them on the figure "
                         "(they stay in the statistics)." % (_plural(bad, what), len(v)))
    return v > 0, ("%s ≤ 0 %s not shown on the log axis (still in the statistics)"
                   % (_plural(bad, what), "is" if bad == 1 else "are"))


def _log_axis(ax, lo, hi):
    """Readable log ticks: 1, 2, 5, 10 ... written as plain numbers (CT-R1 DA-F15)."""
    from matplotlib.ticker import LogLocator, FuncFormatter, NullFormatter
    ax.set_yscale("log")
    decades = math.log10(hi / lo) if (lo > 0 and hi > lo) else 1.0
    subs = (1.0, 2.0, 5.0) if decades <= 3 else (1.0,)
    ax.yaxis.set_major_locator(LogLocator(base=10.0, subs=subs, numticks=15))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: "%g" % v))
    ax.yaxis.set_minor_formatter(NullFormatter())


def _fit_xticklabels(fig, ax):
    """Rotate the x tick labels 30° (right-aligned) when they would run into each other
    (CT-R1 DA-F10, web F14)."""
    labs = [t for t in ax.get_xticklabels() if t.get_text()]
    if len(labs) < 2:
        return False
    try:
        r = _renderer(fig)
        w = max(t.get_window_extent(r).width for t in labs)
        xs = sorted(ax.transData.transform((t.get_position()[0], 0))[0] for t in labs)
        gap = min(b - a for a, b in zip(xs, xs[1:]))
    except Exception:                                    # noqa: BLE001
        return False
    if w > 0.92 * gap:
        for t in labs:
            t.set_rotation(30); t.set_ha("right"); t.set_rotation_mode("anchor")
        return True
    return False


def _wrap_title(fig, ax, opts):
    """Title wrapped to the axes width instead of running off the figure (CT-R1 DA-F21)."""
    title = opts.get("title")
    if not title:
        return
    import textwrap
    kw = dict(fontsize=14, fontweight="bold")
    txt = _lk.safe_text(str(title))
    aw, _ = _axes_in(fig, ax)
    w, _h = _text_in(fig, txt, **kw)
    if w > aw and len(txt) > 12:
        per = max(12, int(len(txt) * aw / w) - 1)
        txt = "\n".join(textwrap.wrap(txt, per, break_long_words=True)) or txt
    ax.set_title(txt, loc="left", pad=8, **kw)


def _caption(fig, bits):
    """One small caption line under the axes (log-axis notes, what n and N are)."""
    bits = [b for b in bits if b]
    if not bits:
        return None
    return fig.text(0.012, 0.008, " · ".join(bits) + ".", ha="left", va="bottom", fontsize=7.5,
                    color="#5b6a65", style="italic")


def _layout(fig, caption):
    fig.tight_layout(rect=(0, 0.04, 1, 1) if caption is not None else None)


def _n_label_plan(fig, labels_full, labels_short, slot_in):
    """Pick the n-label wording and font that fit their slot: the full two-line wording when it
    fits, else the short one ("n=54 / N=3"), shrinking, else staggered on two rows.
    Returns (texts, fontsize, stagger, block height in inches, used_short)."""
    for fs in (9.5, 8.5, 7.5):
        w, h = max((_text_in(fig, t, fontsize=fs, fontweight="bold") for t in labels_full),
                   key=lambda wh: wh[0])
        if w <= slot_in:
            return labels_full, fs, False, h, False
    short = labels_short or labels_full
    for fs in (8.5, 7.5, 6.5):
        w, h = max((_text_in(fig, t, fontsize=fs, fontweight="bold") for t in short),
                   key=lambda wh: wh[0])
        if w <= slot_in:
            return short, fs, False, h, True
    w, h = max((_text_in(fig, t, fontsize=6.5, fontweight="bold") for t in short), key=lambda wh: wh[0])
    return short, 6.5, w > slot_in, h, True


def _bracket_levels(pairs, order):
    """Greedy rows for the brackets: shorter spans first, each on the lowest row where it does
    not overlap another bracket (two brackets may meet at a sample and share a row)."""
    items = sorted(((min(order.index(a), order.index(b)), max(order.index(a), order.index(b)), (a, b))
                    for a, b in pairs), key=lambda t: (t[1] - t[0], t[0]))
    rows, out = [], []
    for i, j, pair in items:
        for lv, row in enumerate(rows):
            if all(j <= i2 or j2 <= i for i2, j2 in row):
                row.append((i, j)); out.append((pair, lv)); break
        else:
            rows.append([(i, j)]); out.append((pair, len(rows) - 1))
    return out, len(rows)


def annotation_plan(order, posthoc, opts):
    """Which comparisons the figure annotates, and a sentence saying so.
    {"mode": "brackets"|"letters"|"none", "pairs": [...], "letters": {...}, "note": str}.
    auto with more than 5 samples draws only the significant comparisons against the reference
    (--control, else the first sample): 12 samples have 66 pairs, which is not a figure
    (CT-R1 DA-F10, web F14)."""
    mode = str((opts or {}).get("annotate", "auto") or "auto").lower()
    order = list(order)
    plan = {"mode": "none", "pairs": [], "letters": {}, "note": ""}
    if mode == "none" or not posthoc or len(order) < 2:
        return plan

    def _p(pair):
        v = posthoc.get(pair, posthoc.get((pair[1], pair[0])))
        return v if (v is not None and v == v) else 1.0       # p == 0.0 is significant

    def _has(pair):
        return pair in posthoc or (pair[1], pair[0]) in posthoc

    allpairs = [pr for pr in itertools.combinations(order, 2) if _has(pr)]
    complete = len(allpairs) == len(order) * (len(order) - 1) // 2
    if mode == "letters":
        if complete and len(order) > 2:
            plan.update(mode="letters", letters=compact_letters(order, posthoc),
                        note="Letters above the samples are a compact letter display: samples that "
                             "share a letter are not significantly different (adjusted p ≥ 0.05).")
            return plan
        mode = "auto"
        plan["note"] = ("A compact letter display needs every pair of 3 or more samples to be "
                        "tested, so brackets are drawn instead. ")
    plan["mode"] = "brackets"
    if not complete:                                  # Dunnett: only the comparisons that were made
        sig = [pr for pr in allpairs if _p(pr) < 0.05]
        plan["pairs"] = allpairs if mode in ("all", "adjacent") else (sig or allpairs)
        plan["note"] += "Brackets: each sample against the control."
    elif mode == "adjacent":
        plan["pairs"] = [(order[i], order[i + 1]) for i in range(len(order) - 1)]
        plan["note"] += "Brackets: neighbouring samples only."
    elif mode == "all":
        plan["pairs"] = allpairs
        plan["note"] += "Brackets: every pair."
    else:  # auto: annotate significant pairs (fall back to adjacent if none significant)
        sig = [pr for pr in allpairs if _p(pr) < 0.05]
        if len(order) > 5:
            ref = (opts or {}).get("control")
            ref = ref if ref in order else order[0]
            plan["pairs"] = [pr for pr in sig if ref in pr]
            plan["note"] += ("With %d samples the figure shows only the significant comparisons "
                             "against %s (%d of the %d significant pairs, out of %d pairs tested). "
                             "Every pair is in the pairwise table. `--annotate letters` gives a "
                             "compact letter display, `--annotate all` every bracket."
                             % (len(order), ref, len(plan["pairs"]), len(sig), len(allpairs)))
        else:
            plan["pairs"] = sig or [(order[i], order[i + 1]) for i in range(len(order) - 1)]
            plan["note"] += ("Brackets: the significant pairs." if sig else
                             "No pair is significant, so brackets show neighbouring samples (ns).")
    if not plan["pairs"]:
        plan["mode"] = "none"
    return plan


def _pairs_to_annotate(order, posthoc, mode):
    return annotation_plan(order, posthoc, {"annotate": mode})["pairs"]


def _plate_style(reps, opts, neutral):
    """Plate -> colour and plate -> marker. Grey violins (the SuperPlot default): the plates take
    the CHOSEN palette. Violins coloured by sample: that palette is already used for the samples,
    so the plates take the muted plate palette. When the colours run out the marker shape
    changes, so no two plates share colour and marker (CT-R1 DA-F13)."""
    pal = clean_palette(opts.get("palette")) if neutral else list(REP_PALETTE)
    rcol = {r: pal[i % len(pal)] for i, r in enumerate(reps)}
    rmark = {r: PLATE_MARKERS[(i // len(pal)) % len(PLATE_MARKERS)] for i, r in enumerate(reps)}
    return rcol, rmark


def violin_colours(df, order, opts, rm=None):
    """The single colour mapping of the violin SuperPlot: (sample -> colour, plate -> colour,
    neutral violins?, plates). plot_violin draws from it and violin_key builds the key from it."""
    if rm is None:
        rm = replicate_means(df)
    vfill = opts.get("violin_fill", "auto")
    neutral = (vfill == "neutral") or (vfill == "auto" and rm is not None)  # grey when points carry plate colour
    by_sample = (not neutral) or rm is None          # does a colour encode the SAMPLE?
    gpal = clean_palette(opts.get("palette"), needed=len(order) if by_sample else 0, what="sample")
    gcol = {g: gpal[i % len(gpal)] for i, g in enumerate(order)}
    reps = sorted(df["replicate"].dropna().unique().tolist()) if rm is not None else []
    rcol, _ = _plate_style(reps, opts, neutral)
    return gcol, rcol, neutral, reps


def _and_list(names):
    names = [str(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def violin_key(order, gcol, rcol, reps, neutral, have_rep, opts):
    """Legend key of the violin SuperPlot, from the same dicts the figure was drawn with.
    Samples are listed when colour encodes them (coloured violins, or coloured points without
    replicates); plates when the plate colour encodes the plate means."""
    afac = float(opts.get("violin_alpha", 0.55)) / 0.55
    entries = []
    pts_by_group = (not have_rep) and opts.get("show_points", True)
    if not neutral or pts_by_group:
        for g in order:
            c = gcol[g]
            em = (dict(marker="o", colour=c, edge="none", alpha=0.42, size=5.0)
                  if pts_by_group else None)
            if not neutral:
                entries.append(_lk.entry(g, c, kind="patch", edge=_darken(c),
                                         alpha=min(1.0, 0.22 * afac), linewidth=0.9,
                                         shape="violin", section="sample", extra_marker=em))
            else:
                entries.append(_lk.entry(g, c, kind="marker", marker="o", edge="none", alpha=0.42,
                                         size=5.0, section="sample"))
    if have_rep:
        _, rmark = _plate_style(reps, opts, neutral)
        for r in reps:
            entries.append(_lk.entry(r, rcol[r], kind="marker", marker=rmark[r], edge="#12211d",
                                     size=7, section="plate"))
    # CT-R1 SM-F20: when the colour-coded items are plates, the text starter still names the samples
    preamble = None
    if neutral and have_rep and order:
        preamble = ("%s %s shown as grey violins. Points are coloured by plate"
                    % (_and_list(order), "is" if len(order) == 1 else "are"))
    return _lk.make_key(entries, fontsize=9, frameon=False, preamble=preamble)


def plot_violin(df, order, opts, metric_name, posthoc):
    """Violin SuperPlot (Lord et al. 2020; Kenny & Schoen 2021): soft violins of all plaques,
    plaque points and plate means coloured by plate, summary = mean ± SEM of the plate means.
    No boxes — the plate means ARE the summary. Without replicates the bar is the mean ± SEM of
    the plaques (choose --center median --error iqr for a median/IQR bar).
    Runs inside matplotlib.rc_context: the caller's rcParams are left as they were."""
    with matplotlib.rc_context(_FIG_RC):
        return _plot_violin(df, list(order), _plot_opts(opts), metric_name, posthoc or {})


def _plot_violin(df, order, opts, metric_name, posthoc):
    rng = np.random.default_rng(opts["seed"])
    fig, ax = plt.subplots(figsize=(opts["width"], opts["height"]))
    rm = replicate_means(df)
    # the colour mapping this figure is drawn from -- and its legend key is built from
    gcol, rcol, neutral, reps = violin_colours(df, order, opts, rm)
    _, rmark = _plate_style(reps, opts, neutral)
    log_y = bool(opts.get("log_y"))
    drawmask, log_note = _log_guard(df["value"].values, opts)
    ddf = df[drawmask]                                     # what can be DRAWN (all of it, unless log)
    cen_tab = center_table(df, order, opts)                # the statistic: from ALL the values

    data = [ddf.loc[ddf["group"] == g, "value"].values for g in order]
    n_all = [int((df["group"] == g).sum()) for g in order]
    pos = np.arange(1, len(order) + 1)
    drawn = [i for i in range(len(order)) if len(data[i])]

    afac = float(opts.get("violin_alpha", 0.55)) / 0.55   # 0.55 (default) keeps the tuned look; scales from there
    if log_y:                                             # density estimated in log space
        ax.set_yscale("log")
    if drawn:
        parts = ax.violinplot([np.log10(data[i]) if log_y else data[i] for i in drawn],
                              positions=pos[drawn], showextrema=False, widths=0.80)
        for b, i in zip(parts["bodies"], drawn):
            if neutral:
                b.set_facecolor("#b9c2bd"); b.set_edgecolor("#6f7b74"); b.set_alpha(min(1.0, 0.38 * afac))
            else:
                c = gcol[order[i]]
                b.set_facecolor(c); b.set_edgecolor(_darken(c)); b.set_alpha(min(1.0, 0.22 * afac))
            b.set_linewidth(0.9)
            verts = b.get_paths()[0].vertices                 # trim the violin to the data range
            if log_y:
                verts[:, 1] = 10.0 ** verts[:, 1]
            verts[:, 1] = np.clip(verts[:, 1], float(np.min(data[i])), float(np.max(data[i])))

    tops = {}                                             # per sample: top of everything drawn
    for i, g in enumerate(order):
        v = data[i]; x0 = pos[i]; c = gcol[g]
        sub = ddf[ddf["group"] == g]
        cen, lo, hi, _nu = cen_tab.get(g, (float("nan"),) * 4)
        if log_y:                                         # a bar or whisker end <= 0 cannot be drawn
            lo = lo if lo > 0 else (cen if cen > 0 else float("nan"))
        ok_bar = cen == cen and (cen > 0 or not log_y)
        top = float(np.max(v)) if len(v) else float("-inf")
        if rm is not None:                                # ---------- Violin SuperPlot ----------
            if opts["show_points"]:
                for r in reps:
                    vv = sub.loc[sub["replicate"] == r, "value"].values
                    if not len(vv):
                        continue
                    jx = x0 + rng.uniform(-opts["jitter"], opts["jitter"], size=len(vv))
                    ax.scatter(jx, vv, s=opts["point_size"], color=rcol[r], alpha=0.45,
                               edgecolor="none", zorder=3, marker=rmark[r])
            gm = rm[rm["group"] == g]
            if log_y:
                gm = gm[gm["value"] > 0]
            jx = (x0 + np.linspace(-0.05, 0.05, len(gm))) if len(gm) > 1 else np.array([float(x0)])
            for mk in dict.fromkeys(rmark[r] for r in gm["replicate"]):
                sel = np.array([rmark[r] == mk for r in gm["replicate"]], bool)
                ax.scatter(jx[sel], gm["value"].values[sel], s=opts["point_size"] * 5.5,
                           c=[rcol[r] for r in gm["replicate"][sel]], edgecolor="#12211d",
                           linewidth=0.9, zorder=6, marker=mk)
            if len(gm):
                top = max(top, float(gm["value"].max()))
            if ok_bar:
                ax.plot([x0 - 0.19, x0 + 0.19], [cen, cen], color="#12211d", lw=2.0,
                        solid_capstyle="round", zorder=7)
                if hi > lo:
                    ax.plot([x0, x0], [lo, hi], color="#12211d", lw=1.1, zorder=7)
                if opts.get("show_value", True):
                    ax.annotate("%.2f" % cen, (x0 + 0.21, cen), fontsize=9, fontweight="bold",
                                va="center", ha="left", color="#12211d", zorder=8,
                                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
        else:                                             # -------- no replicates: bar on the plaques --------
            if opts["show_points"] and len(v):
                jx = x0 + rng.uniform(-opts["jitter"], opts["jitter"], size=len(v))
                ax.scatter(jx, v, s=opts["point_size"], color=c, alpha=0.42, edgecolor="none", zorder=3)
            if ok_bar:
                ax.plot([x0, x0], [lo, hi], color="#33413c", lw=1.4, zorder=5)
                ax.plot([x0 - 0.10, x0 + 0.10], [cen, cen], color="#12211d", lw=2.2, zorder=6)
                if opts.get("show_value", True):
                    ax.annotate("%.2f" % cen, (x0 + 0.12, cen), fontsize=9, fontweight="bold",
                                va="center", ha="left", color="#12211d", zorder=8,
                                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))
        if ok_bar and hi == hi:
            top = max(top, float(hi), float(cen))         # CT-R1 DA-F16: brackets clear the whiskers
        tops[g] = top

    ax.set_xticks(pos); ax.set_xticklabels([_lk.safe_text(g) for g in order], fontweight="bold")
    ax.set_xlim(0.4, len(order) + 0.6)
    ax.set_ylabel(_lk.safe_text(opts["ylabel"] or metric_name), fontsize=13, fontweight="bold")
    if opts["xlabel"]:
        ax.set_xlabel(_lk.safe_text(opts["xlabel"]), fontsize=13)
    if log_y:
        y0, y1 = ax.get_ylim()
        _log_axis(ax, y0, y1)
    _style_axes(ax, opts)

    n_units = [cen_tab[g][3] for g in order if g in cen_tab]
    key = violin_key(order, gcol, rcol, reps, neutral, rm is not None, opts)
    key["note"] = figure_sentence(opts, rm is not None, n_units)
    _lk.attach(fig, key)
    if opts.get("legend", True):                 # "Place key on figure": the SAME key, outside right
        _lk.embed(ax, key, loc="upper left", bbox_to_anchor=(1.005, 1.0), handletextpad=0.3,
                  borderaxespad=0.2)

    caption_bits = [log_note]
    _wrap_title(fig, ax, opts)
    fig.tight_layout()                           # first pass: the axes get their real size
    if _fit_xticklabels(fig, ax):
        fig.tight_layout()
    aw, ah = _axes_in(fig, ax)

    # ---- everything above the data is laid out in INCHES and converted to data units at the
    # end (in log space on a log axis), so brackets, stars and n labels cannot collide whatever
    # the axis scale or the number of samples (CT-R1 SM-F13, DA-F10, DA-F15, DA-F16).
    T = (lambda y: math.log10(y)) if log_y else (lambda y: float(y))
    Ti = (lambda t: 10.0 ** t) if log_y else (lambda t: float(t))
    plan = annotation_plan(order, posthoc, opts)
    fig.annotation_note = plan["note"]
    finite_tops = [t for t in tops.values() if t == t and t != float("-inf") and (t > 0 or not log_y)]
    slot_in = aw / (len(order) + 0.2)

    n_plan = None
    if opts.get("show_n", True) and order:
        npl = {g: int(df.loc[df["group"] == g, "replicate"].nunique(dropna=True)) for g in order}
        if rm is not None:                       # CT-R1 SM-F7 / DA-F12: plaques AND plates
            full = ["n = %s\nN = %s" % (_plural(n_all[i], "plaque"), _plural(npl[g], "plate"))
                    for i, g in enumerate(order)]
            short = ["n=%d\nN=%d" % (n_all[i], npl[g]) for i, g in enumerate(order)]
        else:
            full = ["n = %s" % _plural(n_all[i], "plaque") for i in range(len(order))]
            short = ["n=%d" % n_all[i] for i in range(len(order))]
        n_plan = _n_label_plan(fig, full, short, slot_in * 0.96)

    if finite_tops and (plan["mode"] != "none" or n_plan):
        y0, _y1 = ax.get_ylim()
        bot_t, top_t = T(y0), T(max(finite_tops))
        star_fs = 11.0
        nlev = 0
        if plan["mode"] == "brackets":
            placed, nlev = _bracket_levels(plan["pairs"], order)
        elif plan["mode"] == "letters":
            nlev = 1
        hn = 0.0
        if n_plan:
            hn = n_plan[3] * (2.0 if n_plan[2] else 1.0) + 0.10
        gap = 0.10 if nlev else 0.04
        pitch = star_fs / 72.0 * 1.75
        room = ah - hn - gap - 0.42 * ah              # the data keep at least 42 % of the axes
        if nlev and nlev * pitch > room:
            star_fs = max(6.0, star_fs * room / (nlev * pitch))
            pitch = max(star_fs / 72.0 * 1.75, 0.0)
            if nlev * pitch > ah * 0.72 - hn - gap:   # absurd bracket counts: squeeze the rows
                pitch = max(0.03, (ah * 0.72 - hn - gap) / nlev)
        c = hn + gap + nlev * pitch + 0.03
        R = (top_t - bot_t) / max(0.10, 1.0 - c / ah)  # final axis range in T units
        u = R / ah                                     # T units per inch
        ax.set_ylim(Ti(bot_t), Ti(bot_t + R))
        base = top_t + gap * u
        if plan["mode"] == "brackets":
            tick = 0.22 * pitch * u
            for (a, b), lv in placed:
                i, j = sorted((order.index(a), order.index(b)))
                x1, x2 = pos[i] + 0.06, pos[j] - 0.06
                yb = base + lv * pitch * u
                ax.plot([x1, x1, x2, x2], [Ti(yb), Ti(yb + tick), Ti(yb + tick), Ti(yb)],
                        lw=1.0, color="#33413c")
                ax.text((x1 + x2) / 2, Ti(yb + tick * 1.08),
                        stars(posthoc.get((a, b), posthoc.get((b, a)))),
                        ha="center", va="bottom", fontsize=star_fs)
        elif plan["mode"] == "letters":
            for i, g in enumerate(order):
                ax.text(pos[i], Ti(base), plan["letters"].get(g) or "n/a", ha="center", va="bottom",
                        fontsize=star_fs, fontweight="bold", color="#12211d")
        if n_plan:                                      # n labels INSIDE the box, at the top
            import matplotlib.transforms as mtransforms
            texts, fs, stagger, h_in, used_short = n_plan
            tr = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)
            for i in range(len(order)):
                yfrac = 0.985 - ((h_in + 0.03) / ah if (stagger and i % 2) else 0.0)
                ax.text(pos[i], yfrac, texts[i], transform=tr, ha="center", va="top",
                        fontsize=fs, fontweight="bold", color="#33413c", linespacing=1.15)
            if used_short and rm is not None:
                caption_bits.append("n = plaques, N = plates")
    cap = _caption(fig, caption_bits)
    _layout(fig, cap)
    return fig


# --------------------------------------------------------------------- reporting
def write_report(path, metric, summ, rep_summ, omni, posthoc, unit, have_rep, args):
    L = []
    L.append(f"# Plaque statistics report — {metric}\n")
    L.append(f"_Generated {args['_stamp']} · plaque_stats v{__version__}_\n")
    L.append("## Group summary (per plaque)\n")
    L.append(_md(summ.round(4)))
    if rep_summ is not None:
        L.append("\n## Per-replicate (plate) means\n")
        L.append(_md(rep_summ.round(4)))
    L.append("\n## Group comparison\n")
    L.append(f"- **Statistical unit:** {unit}"
             + ("  _(per-plate means — avoids pseudoreplication)_" if unit == "replicate"
                else "  _(per-plaque — no replicate column, so plates are pooled;"
                     " treat with caution)_") + "\n")
    L.append("- **Omnibus test:** %s, p = %s (parametric=%s, unit n = %d per group, Levene p=%s)\n"
             % (omni["test"], _fmt_p(omni["p"]), omni["parametric_used"],
                omni.get("min_n", 0), _fmt_p(omni["levene_p"])))
    eff = omni.get("effect", {})
    if eff:
        ek, ev = next(iter(eff.items()))
        if ev == ev:
            L.append("- **Effect size:** %s = %.3f\n" % (ek.replace("_", " "), ev))
    for w in omni.get("warnings", []):
        L.append("- ⚠️ **%s**\n" % w)
    if posthoc:
        L.append("\n**Pairwise (adjusted p):**\n")
        rows = [{"pair": f"{a} vs {b}", "p_adj": _fmt_p(p), "signif": stars(p)}
                for (a, b), p in posthoc.items()]
        L.append(_md(pd.DataFrame(rows)))
    # paste-ready sentence
    L.append("\n## Paste-ready sentence\n")

    def _n(row):
        s = "n=%d" % int(row["n"])
        return s + (", %d plates" % int(row["n_replicates"]) if have_rep else " plaques")

    if len(summ) == 2:
        g1, g2 = summ.iloc[0], summ.iloc[1]
        d_txt = ""
        d_val = omni.get("effect", {}).get("cohens_d")
        us = omni.get("unit_stats", {})
        if d_val is not None and d_val == d_val:
            d_txt = ", Cohen's d = %.2f" % d_val
            if omni.get("min_n", 0) < 5:
                d_txt += " (a %d-vs-%d %s estimate; treat as rough)" % (
                    us.get(g1["group"], {}).get("n", 0), us.get(g2["group"], {}).get("n", 0),
                    "plate" if unit == "replicate" else "plaque")
        if unit == "replicate" and g1["group"] in us and g2["group"] in us:
            # Quote the numbers the test was run on (plate means +/- SEM, n = plates), not
            # per-plaque mean +/- SD beside a plate-level p (AUDIT-2026-10.md, PT-43).
            u1, u2 = us[g1["group"]], us[g2["group"]]
            L.append("> %s in %s was %.2f ± %.2f (mean ± SEM of %d plate means; %d plaques) vs %s "
                     "%.2f ± %.2f (%d plates; %d plaques); %s on plate means, p = %s%s."
                     % (metric, g1["group"], u1["mean"], u1["sem"], u1["n"], int(g1["n"]),
                        g2["group"], u2["mean"], u2["sem"], u2["n"], int(g2["n"]),
                        omni["test"], _fmt_p(omni["p"]), d_txt))
        else:
            L.append("> %s in %s was %.2f ± %.2f (%s) vs %s %.2f ± %.2f (%s); %s p = %s%s."
                     % (metric, g1["group"], g1["mean"], g1["sd"], _n(g1),
                        g2["group"], g2["mean"], g2["sd"], _n(g2),
                        omni["test"], _fmt_p(omni["p"]), d_txt))
    else:
        unit_note = ("the plate is the experimental unit" if unit == "replicate"
                     else "NOTE: unit = plaque — pseudoreplication, add plate replicates")
        L.append("> %s across %d groups: p = %s (statistical unit: %s; pairwise: %s). "
                 "Values are mean ± SD per plaque; %s."
                 % (omni["test"], len(summ), _fmt_p(omni["p"]), unit,
                    omni.get("posthoc", "Holm/Tukey"), unit_note))

    L.append("\n## Assumptions & limitations\n")
    L.append("- **Experimental unit:** %s — %s." % (
        unit, "per-plate means, the biological replicate (correct)" if unit == "replicate"
        else "per plaque; plaques on a plate are NOT independent — add a replicate/plate column"))
    L.append("- **Test choice:** %s. With **< 8 replicates per group** the tool uses a *parametric* test "
             "on the plate means — Shapiro–Wilk is unreliable and non-parametric tests are underpowered at "
             "small n (Mann–Whitney cannot reach p<0.05 at 3 vs 3); this follows SuperPlots (Lord et al. "
             "2020). Override with `--parametric`." % omni["test"])
    L.append("- **Replicates per group:** min = %d. Aim for ≥ 3 plates; more plates = more power."
             % omni.get("min_n", 0))
    for w in omni.get("warnings", []):
        L.append("- ⚠️ %s" % w)
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


def _md(df):
    try:
        return df.to_markdown(index=False)
    except Exception:
        return "```\n" + df.to_string(index=False) + "\n```"


def fmt_p(p):
    """The one p-value formatter (CT-R1 SM-F10): "< 0.001", "0.034", "> 0.999", "n/a".
    Three decimals, except that a value whose rounding would land ON or ACROSS a star threshold
    (0.05, 0.01, 0.001) gets as many more decimals as it needs to stay on its own side
    (0.04996 prints as 0.04996, not as "0.050" beside a star)."""
    if p is None:
        return "n/a"
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(p):
        return "n/a"
    if p < 1e-3:
        return "< 0.001"
    if p > 0.999:
        return "> 0.999"
    for nd in (3, 4, 5, 6):
        r = round(p, nd)
        if all((p < t) == (r < t) for t in (0.05, 0.01, 0.001)):
            return "%.*f" % (nd, p)
    return "%.6f" % p


def p_text(p):
    """A p-value with its sign, for sentences: "p < 0.001", "p = 0.034", "p > 0.999", "p = n/a"."""
    t = fmt_p(p)
    return "p %s" % t if t[0] in "<>" else "p = %s" % t


_fmt_p = fmt_p          # the old private name (the web app imports it)


# ----------------------------------------------------------------------- example
def make_example(folder):
    """Write example_data_long.csv, example_data_wide.csv and TEMPLATE.csv (reproducible)."""
    rng = np.random.default_rng(42)
    os.makedirs(folder, exist_ok=True)
    rows = []
    truth = {"T4": 2.6, "T7": 1.9, "lambda": 3.1}     # mean diameter per phage (mm)
    for phage, mu in truth.items():
        for pl in range(1, 4):                        # 3 plates each
            plate_shift = rng.normal(0, 0.12)         # plate-to-plate variation (real biology)
            for _ in range(rng.integers(18, 32)):     # plaques per plate
                d = max(0.2, rng.normal(mu + plate_shift, 0.35))
                area = math.pi * (d / 2) ** 2
                turb = float(np.clip(rng.normal(0.35 if phage != "T7" else 0.6, 0.12), 0, 1))
                rows.append((phage, f"plate{pl}", round(d, 3), round(area, 3), round(turb, 3)))
    wide = pd.DataFrame(rows, columns=["group", "replicate", "diameter_mm", "area_mm2", "turbidity"])
    wide.to_csv(os.path.join(folder, "example_data_wide.csv"), index=False)
    long = wide.melt(id_vars=["group", "replicate"], var_name="metric", value_name="value")
    long.to_csv(os.path.join(folder, "example_data_long.csv"), index=False)
    tmpl = pd.DataFrame({"group": ["SampleA", "SampleA", "SampleB"],
                         "replicate": ["plate1", "plate1", "plate1"],
                         "diameter_mm": [2.30, 2.55, 1.80],
                         "area_mm2": [4.15, 5.11, 2.54],
                         "turbidity": [0.20, 0.15, 0.62]})
    tmpl.to_csv(os.path.join(folder, "TEMPLATE.csv"), index=False)
    print("wrote example_data_long.csv, example_data_wide.csv, TEMPLATE.csv ->", os.path.abspath(folder))


def save_stats_table(summ, base, metric, unit, formats=("png",)):
    """Render the descriptive-statistics table in each requested format (PNG + editable SVG/PDF)."""
    cols = ["group", "n", "n_replicates", "mean", "sd", "sem", "ci95_lo", "ci95_hi",
            "median", "iqr", "cv_pct"]
    disp = summ[cols].copy()
    disp.columns = ["Sample", "n", "plates", "Mean", "SD", "SEM", "CI95 lo", "CI95 hi",
                    "Median", "IQR", "CV %"]
    for c in ["Mean", "SD", "SEM", "CI95 lo", "CI95 hi", "Median", "IQR", "CV %"]:
        disp[c] = disp[c].map(lambda x: ("%.3g" % x) if pd.notna(x) else "")
    # a presentation-ready combined column (mean ± SD)
    disp.insert(3, "Mean ± SD", ["%.3g ± %.2g" % (m, s) if pd.notna(m) and pd.notna(s) else ""
                                 for m, s in zip(summ["mean"], summ["sd"])])
    nrow = len(disp)
    fig, ax = plt.subplots(figsize=(min(13, 2.0 + 0.92 * len(disp.columns)), 0.55 + 0.34 * (nrow + 1)))
    ax.axis("off")
    ax.set_title("Descriptive statistics — %s  (per plaque; tests use unit: %s)" % (metric, unit),
                 fontsize=11, fontweight="bold", loc="left", pad=12)
    tbl = ax.table(cellText=disp.values.tolist(), colLabels=list(disp.columns),
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.35)
    tbl.auto_set_column_width(range(len(disp.columns)))
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d7e0db"); cell.set_linewidth(0.7)
        if r == 0:
            cell.set_facecolor("#e7efeb"); cell.set_text_props(fontweight="bold", color="#12211d")
        elif r % 2 == 0:
            cell.set_facecolor("#f6f9f7")
        if c == 0 and r > 0:
            cell.set_text_props(fontweight="bold")
    _save_all(fig, base, formats)


def _save_all(fig, base, formats):
    """Save a figure to every requested format (SVG/PDF keep text editable for Inkscape)."""
    for fmt in formats:
        kw = {"dpi": 200, "bbox_inches": "tight", "facecolor": "white"}
        if fmt in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(f"{base}.{fmt}", **kw)
    plt.close(fig)


def save_pairwise_table(unit_means, posthoc, base, metric, unit, formats=("png",)):
    """Render the pairwise comparison table (Δ magnitude + adjusted p) in each requested format."""
    rows = []
    for (a, b), p in posthoc.items():
        da, db = unit_means.get(a, float("nan")), unit_means.get(b, float("nan"))
        rows.append([str(a), str(b), "%.3g" % da, "%.3g" % db, "%+.3g" % (da - db),
                     _fmt_p(p), stars(p)])
    if not rows:
        return
    disp = pd.DataFrame(rows, columns=["Sample A", "Sample B", "mean A", "mean B",
                                       "Δ (A−B)", "p (adj)", "signif"])
    nrow = len(disp)
    fig, ax = plt.subplots(figsize=(min(12, 2.2 + 0.95 * len(disp.columns)), 0.75 + 0.32 * (nrow + 1)))
    ax.axis("off")
    ax.set_title("Pairwise comparisons — %s  (unit: %s)" % (metric, unit),
                 fontsize=11, fontweight="bold", loc="left", pad=12)
    fig.text(0.5, 0.008, "Each row compares two SAMPLES (A vs B); every mean is averaged across all "
             "plate replicates.  Δ = mean A − mean B.", ha="center", fontsize=8, color="#5b6a65")
    tbl = ax.table(cellText=disp.values.tolist(), colLabels=list(disp.columns),
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.3)
    tbl.auto_set_column_width(range(len(disp.columns)))
    sigc = list(disp.columns).index("signif")
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d7e0db"); cell.set_linewidth(0.7)
        if r == 0:
            cell.set_facecolor("#e7efeb"); cell.set_text_props(fontweight="bold", color="#12211d")
        elif r % 2 == 0:
            cell.set_facecolor("#f6f9f7")
        if r > 0 and c == sigc and disp.iloc[r - 1]["signif"] != "ns":
            cell.set_text_props(fontweight="bold", color="#0a5c43")
    _save_all(fig, base, formats)


# --------------------------------------------------------------------------- main
# =============================================================================
#  GROUPED CONTROL-COMPARISON MODE  (two factors: group × subgroup, vs a control)
#  e.g. group=phage, subgroup=host, control=the permissive host — each phage's
#  treatment host(s) tested against its control host, on the plate means.
# =============================================================================
def normalize_grouped(df, group, subgroup, value, replicate, metric):
    """Tidy frame: group, subgroup, replicate, value — for the grouped mode (labels as typed,
    dropped rows counted in attrs, exactly as normalize())."""
    out, value = _normalize_core(df, group, value, replicate, metric, subgroup=subgroup)
    return out[["group", "subgroup", "replicate", "value"]], value


def _plate_means_gs(df):
    """Per (group, subgroup, replicate) mean — the plate-level unit for grouped stats (None if no reps)."""
    if df["replicate"].isna().all():
        return None
    return (df.dropna(subset=["replicate"])
              .groupby(["group", "subgroup", "replicate"], as_index=False)
              .agg(value=("value", "mean"), n_plaques=("value", "size")))


def _two_sample_test(control_vals, treat_vals, parametric):
    """(p, test_name) comparing a treatment unit-set to the control unit-set."""
    a, b = np.asarray(control_vals, float), np.asarray(treat_vals, float)
    if len(a) < 2 or len(b) < 2:
        return float("nan"), "n/a (need ≥2 per side)"
    if parametric == "nonparametric":
        try:
            _, p = st.mannwhitneyu(a, b, alternative="two-sided")
            return float(p), "Mann–Whitney U"
        except ValueError:
            return float("nan"), "Mann–Whitney U (all ties)"
    # auto/parametric: Welch t-test (MWU can't reach p<0.05 at 3 vs 3 — underpowered at small n)
    _, p = st.ttest_ind(a, b, equal_var=False)
    return float(p), "Welch t-test"


def grouped_stats(df, group_order, sub_order, control, parametric="auto"):
    """Per (group, subgroup) summary + each non-control subgroup tested vs the control subgroup,
    on the experimental unit (plate means when replicates exist, else plaques). Returns
    (summary_df, comparisons_df, unit)."""
    pm = _plate_means_gs(df)
    unit = "replicate" if pm is not None else "plaque"
    src = pm if pm is not None else df
    rows, comps = [], []
    for g in group_order:
        ctrl = src[(src["group"] == g) & (src["subgroup"] == control)]["value"].values
        for s in sub_order:
            vals = src[(src["group"] == g) & (src["subgroup"] == s)]["value"].values
            d = describe(vals)
            rows.append({"group": g, "subgroup": s, "is_control": s == control,
                         "n_units": len(vals),
                         "n_plaques": int(df[(df["group"] == g) & (df["subgroup"] == s)].shape[0]),
                         "mean": d["mean"], "sd": d["sd"], "sem": d["sem"],
                         "ci95_lo": d["ci95_lo"], "ci95_hi": d["ci95_hi"],
                         "median": d["median"], "min": d["min"], "max": d["max"]})
            if s != control and len(ctrl) and len(vals):
                p, test = _two_sample_test(ctrl, vals, parametric)
                mc, mm = float(np.mean(ctrl)), float(np.mean(vals))
                comps.append({"group": g, "subgroup": s, "control": control,
                              "mean_control": round(mc, 4), "mean_subgroup": round(mm, 4),
                              "change_pct": round((mm - mc) / mc * 100, 1) if mc else float("nan"),
                              "cohens_d": round(cohens_d(vals, ctrl), 3),
                              "n_control": len(ctrl), "n_subgroup": len(vals),
                              # a test that didn't run (n<2 per side -> p is NaN) must NOT read as a
                              # tested 'ns'; label it n/a so the report/plot don't imply a null result
                              "test": test, "p": p, "signif": stars(p) if p == p else "n/a"})
    comps_df = pd.DataFrame(comps)
    if len(comps_df):
        # Several subgroups are each tested against the one control within a group: adjust
        # those p-values (Holm, within group) and report both (AUDIT-2026-10.md, PT-44).
        comps_df["p_raw"] = comps_df["p"]
        adj = []
        for g, sub in comps_df.groupby("group", sort=False):
            raw = {i: (float(p) if p == p else float("nan")) for i, p in zip(sub.index, sub["p"])}
            a = _holm(raw)
            adj += [(i, a[i]) for i in sub.index]
        for i, p in adj:
            comps_df.loc[i, "p"] = p
            comps_df.loc[i, "signif"] = stars(p) if p == p else "n/a"
    return pd.DataFrame(rows), comps_df, unit


def plot_grouped(df, group_order, sub_order, control, opts, metric_name, comp):
    """Grouped SuperPlot: main groups on x, subgroups as neutral violins offset within each group,
    plate-mean dots + mean±SEM coloured by subgroup, and a significance star for each non-control
    subgroup vs the control (within its group). Legend marks the control."""
    plt.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42,
                         "font.size": 12, "font.family": "sans-serif", "axes.linewidth": 0.9})
    rng = np.random.default_rng(opts["seed"])
    fig, ax = plt.subplots(figsize=(opts["width"], opts["height"]))
    pal = opts["palette"]
    scol = {s: pal[i % len(pal)] for i, s in enumerate(sub_order)}          # colour per subgroup
    pm = _plate_means_gs(df)
    span = (float(df["value"].max()) - float(df["value"].min())) or 1.0
    K = max(len(sub_order), 1)
    slot = 0.82 / K
    offs = {s: (i - (K - 1) / 2.0) * slot for i, s in enumerate(sub_order)}
    pmap = {(r["group"], r["subgroup"]): r["p"] for _, r in comp.iterrows()} if len(comp) else {}
    gmax = {}
    for gi, g in enumerate(group_order):
        for s in sub_order:
            x = (gi + 1) + offs[s]
            vals = df[(df["group"] == g) & (df["subgroup"] == s)]["value"].values
            if not len(vals):
                continue
            vp = ax.violinplot([vals], positions=[x], widths=slot * 0.92, showextrema=False)
            for b in vp["bodies"]:
                b.set_facecolor("#b9c2bd"); b.set_edgecolor("#6f7b74")
                b.set_alpha(min(1.0, 0.32 * float(opts.get("violin_alpha", 0.55)) / 0.55))
                b.set_linewidth(0.8)
                vv = b.get_paths()[0].vertices
                vv[:, 1] = np.clip(vv[:, 1], float(np.min(vals)), float(np.max(vals)))
            c = scol[s]
            if pm is not None:
                if opts.get("show_points", True):        # faint raw plaques behind the plate means
                    jr = x + rng.uniform(-slot * 0.30, slot * 0.30, size=len(vals))
                    ax.scatter(jr, vals, s=opts["point_size"] * 0.7, color=c, alpha=0.20,
                               edgecolor="none", zorder=2)
                um = pm[(pm["group"] == g) & (pm["subgroup"] == s)]["value"].values
                jx = (x + np.linspace(-0.03, 0.03, len(um))) if len(um) > 1 else np.array([float(x)])
                ax.scatter(jx, um, s=opts["point_size"] * 4.0, color=c, edgecolor="#12211d",
                           linewidth=0.8, zorder=6)
                cen, lo, hi = _center_spread(um, opts.get("center", "mean"), opts.get("error", "auto"))
            else:
                jx = x + rng.uniform(-slot * 0.25, slot * 0.25, size=len(vals))
                ax.scatter(jx, vals, s=opts["point_size"], color=c, alpha=0.40, edgecolor="none", zorder=3)
                cen, lo, hi = _center_spread(vals, opts.get("center", "mean"), opts.get("error", "auto"))
            ax.plot([x - slot * 0.34, x + slot * 0.34], [cen, cen], color="#12211d", lw=2.0, zorder=7)
            if hi > lo:
                ax.plot([x, x], [lo, hi], color="#12211d", lw=1.1, zorder=7)
            if opts.get("show_value", True):                 # the mean/median value, beside the crossbar
                ax.annotate("%.2f" % cen, (x + slot * 0.38, cen), ha="left", va="center",
                            fontsize=7.5, fontweight="bold", color="#12211d", zorder=8,
                            bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="#cdd6d1", lw=0.6, alpha=0.9))
            if opts.get("show_n", True):                      # n plaques, above each sub-violin
                ax.text(x, float(np.max(vals)) + span * 0.012, "n=%d" % len(vals),
                        ha="center", va="bottom", fontsize=7.5, color="#33413c", zorder=8)
            gmax[g] = max(gmax.get(g, float("-inf")), float(np.max(vals)))

    if opts.get("annotate", "auto") != "none":       # let the desktop's Brackets=None hide them
        for gi, g in enumerate(group_order):
            lvl = gmax.get(g, float(df["value"].max())) + span * 0.075   # headroom above the n labels
            xc = (gi + 1) + offs[control]
            for s in sub_order:
                if s == control or (g, s) not in pmap:
                    continue
                xs = (gi + 1) + offs[s]
                ax.plot([xc, xc, xs, xs], [lvl, lvl + span * 0.02, lvl + span * 0.02, lvl],
                        lw=1.0, color="#33413c")
                _pv = pmap[(g, s)]
                ax.text((xc + xs) / 2, lvl + span * 0.025, stars(_pv) if _pv == _pv else "n/a",
                        ha="center", va="bottom", fontsize=11)
                lvl += span * 0.095

    ax.set_xticks(np.arange(1, len(group_order) + 1)); ax.set_xticklabels(group_order, fontweight="bold")
    ax.set_ylabel(opts["ylabel"] or metric_name, fontsize=13, fontweight="bold")
    if opts.get("xlabel"):
        ax.set_xlabel(opts["xlabel"], fontsize=13)
    if opts.get("title"):
        ax.set_title(opts["title"], fontsize=14, fontweight="bold", loc="left", pad=8)
    if opts.get("log_y"):
        ax.set_yscale("log")
    _style_axes(ax, opts)
    # legend key from the SAME subgroup -> colour dict the marks were drawn with
    key = _lk.attach(fig, grouped_key(sub_order, control, scol, pm is not None,
                                      opts.get("_sublabel", "subgroup")))
    if opts.get("legend", True):                 # "Place key on figure"
        _lk.embed(ax, key, loc="upper left", bbox_to_anchor=(1.005, 1.0))
    fig.tight_layout()
    return fig


def grouped_key(sub_order, control, scol, have_rep, sublabel="subgroup"):
    """Legend key of the grouped plot: one entry per subgroup, styled as its marks are drawn
    (plate means: filled circles with a dark outline; no replicates: plain translucent points)."""
    entries = []
    for s in sub_order:
        lab = "%s (control)" % s if s == control else s
        if have_rep:
            entries.append(_lk.entry(lab, scol[s], marker="o", edge="#12211d", size=8))
        else:
            entries.append(_lk.entry(lab, scol[s], marker="o", edge="none", alpha=0.40, size=6))
    return _lk.make_key(entries, title=sublabel, fontsize=9, frameon=True)


def _write_grouped_report(path, metric, summ, comp, unit, control, args):
    unote = ("per-plate means — the plate is the experimental unit (avoids pseudoreplication)"
             if unit == "replicate" else "per-plaque values — NO replicate column, so this is "
             "pseudoreplicated; add a replicate/plate column for defensible stats")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Grouped control-comparison — %s\n\n_Generated %s | plaque_stats v%s_\n\n"
                % (metric, args.get("_stamp", ""), __version__))
        f.write("Each subgroup is compared with the control **%s** within its group, on %s.\n\n"
                % (control, unote))
        if len(comp):
            f.write("| group | subgroup | control mean | subgroup mean | change | Cohen's d | test | p | |\n")
            f.write("|---|---|---:|---:|---:|---:|---|---:|---|\n")
            for _, r in comp.iterrows():
                f.write("| %s | %s | %.3f | %.3f | %+.1f%% | %.2f | %s | %s | %s |\n"
                        % (r["group"], r["subgroup"], r["mean_control"], r["mean_subgroup"],
                           r["change_pct"], r["cohens_d"], r["test"], _fmt_p(r["p"]), r["signif"]))
        f.write("\n_Stars: * p<0.05, ** p<0.01, *** p<0.001, ns = not significant, n/a = not tested. "
                "p-values are Holm-adjusted within each group (raw p in the CSV as p_raw). "
                "Change = (subgroup − control)/control._\n")


def run_grouped(args):
    df, metric = normalize_grouped(read_table(args["data"]), args["group"], args["subgroup"],
                                   args["value"], args["replicate"], args["metric"])
    group_order = args["order"] or list(dict.fromkeys(df["group"]))
    group_order = [g for g in group_order if g in set(df["group"])]
    subs = list(dict.fromkeys(df["subgroup"]))
    control = args.get("control") or subs[0]
    if control not in subs:
        raise StatsError("[error] control %r not among subgroup levels: %s" % (control, subs))
    sub_order = [control] + [s for s in subs if s != control]          # control drawn first
    df = df[df["group"].isin(group_order)].reset_index(drop=True)
    out = args["out"]; os.makedirs(out, exist_ok=True)
    mt = _safe(metric)

    summ, comp, unit = grouped_stats(df, group_order, sub_order, control, args.get("parametric", "auto"))
    summ.to_csv(os.path.join(out, "grouped_summary_%s.csv" % mt), index=False)
    if len(comp):
        comp.to_csv(os.path.join(out, "control_comparisons_%s.csv" % mt), index=False)

    opts = dict(args); opts["_sublabel"] = args["subgroup"]
    fig = plot_grouped(df, group_order, sub_order, control, opts, metric, comp)
    base = os.path.join(out, "grouped_%s" % mt)
    for fmt in args["formats"]:
        kw = {"dpi": args["dpi"], "bbox_inches": "tight", "facecolor": "white"}
        if fmt in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig("%s.%s" % (base, fmt), **kw)
    if args.get("legend_key", True):             # the figure's legend key + text starter, beside it
        _lk.write_key_files(_lk.from_figure(fig), base, args["formats"], dpi=args["dpi"])
    plt.close(fig)

    _write_grouped_report(os.path.join(out, "grouped_report_%s.md" % mt),
                          metric, summ, comp, unit, control, args)
    prov = {k: v for k, v in args.items() if not k.startswith("_")}
    prov.update({"mode": "grouped", "metric": metric, "groups": group_order,
                 "subgroups": sub_order, "control": control, "unit": unit,
                 "versions": {"plaque_stats": __version__, "numpy": np.__version__,
                              "pandas": pd.__version__, "scipy": scipy.__version__}})
    json.dump(prov, open(os.path.join(out, "run_config_%s.json" % mt), "w"), indent=2)
    n_sig = int((comp["p"] < 0.05).sum()) if len(comp) else 0
    print("[done] grouped %s: %d groups × %d subgroups vs '%s' (unit=%s); %d vs-control p<0.05 -> %s"
          % (metric, len(group_order), len(sub_order), control, unit, n_sig, os.path.abspath(out)))


def run(args):
    if args.get("subgroup"):
        return run_grouped(args)
    df, metric = normalize(read_table(args["data"]), args["group"], args["value"],
                           args["replicate"], args["metric"])
    order = args["order"] or list(dict.fromkeys(df["group"]))
    order = [g for g in order if g in set(df["group"])]
    df = df[df["group"].isin(order)].reset_index(drop=True)   # analyse only the selected groups
    out = args["out"]; os.makedirs(out, exist_ok=True)

    mt = _safe(metric)                        # suffix outputs by metric so runs don't overwrite
    summ = group_summary(df, order)
    rep = replicate_means(df)
    summ.to_csv(os.path.join(out, f"summary_by_group_{mt}.csv"), index=False)
    if rep is not None:
        rep.to_csv(os.path.join(out, f"summary_by_replicate_{mt}.csv"), index=False)

    omni, posthoc, unit, have_rep = run_stats(df, order, args["unit"], args["parametric"])
    # group means on the analysis unit (plate means when unit=replicate) — the "magnitude" of differences
    src = rep if (unit == "replicate" and rep is not None) else df
    unit_means = src.groupby("group")["value"].mean().to_dict()
    tests = pd.DataFrame([{"test": omni["test"], "unit": unit, "p": omni["p"],
                           "parametric": omni["parametric_used"], "levene_p": omni["levene_p"]}])
    tests.to_csv(os.path.join(out, f"omnibus_test_{mt}.csv"), index=False)
    if posthoc:
        pd.DataFrame([{"group_a": a, "group_b": b,
                       "mean_a": unit_means.get(a), "mean_b": unit_means.get(b),
                       "mean_diff": unit_means.get(a, float("nan")) - unit_means.get(b, float("nan")),
                       "p_adj": p, "signif": stars(p)}
                      for (a, b), p in posthoc.items()]).to_csv(
            os.path.join(out, f"pairwise_tests_{mt}.csv"), index=False)

    fig = plot_violin(df, order, args, metric, posthoc)
    base = os.path.join(out, f"violin_{mt}")
    for fmt in args["formats"]:
        kw = {"dpi": args["dpi"], "bbox_inches": "tight", "facecolor": "white"}
        if fmt in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(f"{base}.{fmt}", **kw)
    if args.get("legend_key", True):             # the figure's legend key + text starter, beside it
        _lk.write_key_files(_lk.from_figure(fig), base, args["formats"], dpi=args["dpi"])
    plt.close(fig)

    write_report(os.path.join(out, f"report_{mt}.md"), metric, summ, rep, omni, posthoc, unit, have_rep, args)
    if args.get("stats_table", True):
        save_stats_table(summ, os.path.join(out, f"stats_table_{mt}"), metric, unit, args["formats"])
        if posthoc:
            save_pairwise_table(unit_means, posthoc, os.path.join(out, f"pairwise_table_{mt}"),
                                metric, unit, args["formats"])
    prov = {k: v for k, v in args.items() if not k.startswith("_")}
    prov.update({"metric": metric, "groups": order, "unit": unit,
                 "versions": {"plaque_stats": __version__, "numpy": np.__version__,
                              "pandas": pd.__version__, "scipy": scipy.__version__}})
    with open(os.path.join(out, f"run_config_{mt}.json"), "w") as fh:
        json.dump(prov, fh, indent=2)
    for w in omni.get("warnings", []):
        print("[warn] " + w)
    print(f"[done] {metric}: {omni['test']} p={_fmt_p(omni['p'])} (unit={unit}) -> {os.path.abspath(out)}")


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in str(s))


def build_args():
    p = argparse.ArgumentParser(description="Publication-ready violin plots + stats for plaque data.")
    p.add_argument("data", nargs="?", help="input CSV/TSV/XLSX (tidy — see the header of this file)")
    p.add_argument("--config", help="JSON config file (overrides defaults; CLI flags override it)")
    p.add_argument("--make-example", action="store_true", help="write example + template CSVs and exit")
    p.add_argument("--group"); p.add_argument("--value"); p.add_argument("--replicate")
    p.add_argument("--metric"); p.add_argument("--out", default="plaque_stats_out")
    p.add_argument("--subgroup", help="second factor (e.g. host) — switches to grouped "
                                      "control-comparison mode (paired violins within each group)")
    p.add_argument("--control", help="the control level of --subgroup that the others are tested "
                                     "against (default: the first level seen)")
    p.add_argument("--unit", choices=["auto", "replicate", "plaque"])
    p.add_argument("--parametric", choices=["auto", "parametric", "nonparametric"])
    p.add_argument("--annotate", choices=["auto", "all", "adjacent", "none"])
    p.add_argument("--violin-fill", dest="violin_fill", choices=["auto", "group", "neutral"])
    p.add_argument("--order", help="comma-separated group order")
    p.add_argument("--palette", help="named theme (okabe, set2, tab10, warm, cool, grays) "
                                     "or comma-separated hex colours")
    p.add_argument("--title"); p.add_argument("--ylabel"); p.add_argument("--xlabel")
    p.add_argument("--formats", help="comma-separated: png,svg,pdf,tiff")
    p.add_argument("--width", type=float); p.add_argument("--height", type=float)
    p.add_argument("--dpi", type=int); p.add_argument("--seed", type=int)
    p.add_argument("--log-y", dest="log_y", action="store_true")
    p.add_argument("--no-points", dest="show_points", action="store_false")
    p.add_argument("--no-box", dest="show_box", action="store_false")
    p.add_argument("--theme", choices=["clean", "grid"])
    p.add_argument("--center", choices=["mean", "median"], help="group summary marker (default mean)")
    p.add_argument("--error", choices=["auto", "sd", "sem", "ci95", "iqr", "none"],
                   help="error bar on the centre marker (auto: sem for mean, iqr for median)")
    p.add_argument("--no-n", dest="show_n", action="store_false", help="hide the n-plaques labels")
    p.add_argument("--no-value", dest="show_value", action="store_false",
                   help="hide the mean/median value label on the grouped plot")
    p.add_argument("--frame", dest="frame", action="store_true", help="box the plot (all 4 spines)")
    p.add_argument("--no-stats-table", dest="stats_table", action="store_false",
                   help="skip the descriptive-stats table PNG")
    p.add_argument("--legend-key", dest="legend_key", action="store_true", default=None,
                   help="write <figure>_legend_key.<fmt> + <figure>_legend_text.txt beside the "
                        "figure (the default)")
    p.add_argument("--no-legend-key", dest="legend_key", action="store_false",
                   help="do not write the legend key files")
    p.add_argument("--no-legend", dest="legend", action="store_false", default=None,
                   help="do not place the key on the figure itself")
    return p


def main(argv=None):
    ns = build_args().parse_args(argv)
    if ns.make_example:
        make_example(os.path.dirname(os.path.abspath(__file__)))
        return
    if not ns.data:
        build_args().error("provide a DATA file (or --make-example). See the file header for the format.")

    args = dict(DEFAULTS)
    if ns.config:
        args.update(json.load(open(ns.config)))
    for k, v in vars(ns).items():
        if v is not None and k not in ("config", "make_example"):
            args[k] = v
    if isinstance(args.get("palette"), str) and args["palette"].strip().lower() in PALETTES:
        args["palette"] = list(PALETTES[args["palette"].strip().lower()])   # named theme
    for listy in ("order", "palette", "formats"):
        if isinstance(args.get(listy), str):
            args[listy] = [x.strip() for x in args[listy].split(",") if x.strip()]
    args["data"] = ns.data
    args["_stamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    run(args)


if __name__ == "__main__":
    main()
