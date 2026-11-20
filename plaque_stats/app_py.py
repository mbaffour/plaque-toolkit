# app_py.py — Plaque Stats & Violins as a Shiny for Python web app.
# ---------------------------------------------------------------------------------------------
# A browser-based (HTML) app that reuses plaque_stats.py DIRECTLY — the same normalize(),
# group_summary(), run_stats() and plot_violin() the CLI and R app use — so the figures and
# statistics are byte-for-byte identical. No re-implementation.
#
# Run:   shiny run --reload plaque_stats/app_py.py     (opens http://127.0.0.1:8000)
#   first time only:  pip install shiny openpyxl        (plus plaque_stats' deps)
#
# Same tidy data format as the CLI / R app (see README.md):
#   WIDE: group,replicate,diameter_mm,area_mm2,turbidity   |   LONG: group,replicate,metric,value
# ---------------------------------------------------------------------------------------------
import base64
import io
import json
import os
import re
import sys
import tempfile
import zipfile

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from shiny import App, ui, render, reactive, req
from shiny.types import SilentException

import plaque_stats as ps          # the shared engine (same code as the CLI)
import legend_key                  # the figure's legend key (image + text starter), shared helper

HERE = os.path.dirname(os.path.abspath(__file__))


def _example_wide_path():
    """Locate example_data_wide.csv, regenerating it if necessary.

    Search order (robust across source / editable / wheel / frozen installs):
      1. next to this module (source & editable installs),
      2. a dir advertised by the launcher via PLAQUE_STATS_EXAMPLE_DIR,
      3. the install prefix's share/plaque_stats (data-files from the wheel),
      4. as a last resort, generate it fresh with ps.make_example() into a
         temp dir and read from there.
    """
    candidates = [HERE]
    env_dir = os.environ.get("PLAQUE_STATS_EXAMPLE_DIR")
    if env_dir:
        candidates.append(env_dir)
    candidates.append(os.path.join(sys.prefix, "share", "plaque_stats"))
    if getattr(sys, "_MEIPASS", None):
        candidates.append(sys._MEIPASS)
    for d in candidates:
        p = os.path.join(d, "example_data_wide.csv")
        if os.path.exists(p):
            return p
    # Fallback: generate on the fly into a stable temp dir.
    tmp = os.path.join(tempfile.gettempdir(), "plaque_stats_example")
    os.makedirs(tmp, exist_ok=True)
    p = os.path.join(tmp, "example_data_wide.csv")
    if not os.path.exists(p):
        ps.make_example(tmp)
    return p


FORMAT_HELP = """
<h4>Input data format (one row per plaque)</h4>
<p><b>WIDE</b> (matches the app export — add <code>group</code> + <code>replicate</code>):</p>
<pre>group,replicate,diameter_mm,area_mm2,turbidity
T4,plate1,2.34,4.30,0.12
T7,plate1,1.80,2.54,0.62</pre>
<p><b>LONG</b> (one file, many metrics):</p>
<pre>group,replicate,metric,value
T4,plate1,diameter_mm,2.34</pre>
<ul><li><b>group</b> (required): the sample/condition/phage compared.</li>
<li><b>replicate</b> (recommended): the plate / experimental unit — makes stats per-plate.</li>
<li><b>value</b> / numeric columns: the measurement(s).</li></ul>
<p>This app calls the same <code>plaque_stats.py</code> engine as the command-line tool and the
R-Shiny app, so the violin figure and every statistic are identical.</p>
"""

LEARN = """
<div style="max-width:840px;line-height:1.5">
<h4>What a SuperPlot violin shows</h4>
<p>Three layers at once: the <b>violin</b> is the shape of the plaque-size distribution; each
<b>dot</b> is one plaque, coloured by the <b>plate</b> it came from; and the <b>error bar</b> marks the
summary that is actually tested — the <b>mean ± SEM of the per-plate means</b>. Colouring by plate
lets you see at a glance whether a “difference” is real or driven by one odd plate
(Lord et&nbsp;al. 2020; Kenny &amp; Schoen 2021).</p>

<h4>The experimental unit is the PLATE, not the plaque</h4>
<p>Plaques on the same plate share the plate, the lawn and the incubation — they are <b>not
independent</b>. Counting each plaque as its own data point (“pseudoreplication”) inflates n from a
handful of plates to hundreds of plaques and manufactures <b>falsely tiny p-values</b>. By default
this tool collapses each plate to its mean and compares <b>plate means</b> across groups, so
<b>n = number of plates</b>. You <i>can</i> switch to per-plaque in the sidebar — but only if a single
plaque genuinely is your unit of replication.</p>

<h4>Which test is run</h4>
<ul>
<li><b>Omnibus first</b> (all groups together): one-way ANOVA (parametric) or Kruskal–Wallis
(non-parametric).</li>
<li><b>Then pairwise</b> group-vs-group comparisons, computed on the plate means.</li>
<li><b>auto</b> chooses parametric (t&nbsp;/ ANOVA) at the small replicate counts typical of plaque
assays; pick <b>non-parametric</b> (Mann–Whitney&nbsp;/ Kruskal–Wallis) to assume nothing about the
distribution.</li>
</ul>

<h4>The summary tables</h4>
<ul>
<li><b>Per group</b> — n, mean/median, SD, SEM and 95&nbsp;% CI across your plates.</li>
<li><b>Per plate</b> — each plate’s mean: the exact numbers the test uses.</li>
</ul>

<h4>Significance brackets</h4>
<p>Brackets mark pairwise comparisons; stars are the usual thresholds (* p&lt;0.05, ** p&lt;0.01,
*** p&lt;0.001, ns = not significant). With only a few plates, read a lone star as “worth another
replicate,” not proof.</p>

<div style="border-left:4px solid #0e7d5b;background:#f0f7f4;padding:.7em 1em;border-radius:6px;margin-top:1em">
<b>The one habit that matters:</b> report the number of <b>plates</b> (experimental replicates) — not
the number of plaques — as your n, and keep the per-plate points visible so readers can judge the
spread themselves.
</div>

<p style="margin-top:1em">Open the <b>Interactive guide</b> tab for a live pseudoreplication demo:
watch the p-value flip from “significant” to “not” when you count plates instead of plaques.</p>
</div>
"""

# --------------------------------------------------------------------------- server logic, as plain
# functions (CT-R1 web): everything the server does with the data is here, so it is tested without
# a browser (tests/test_ct_r1_web.py) and the reactive code below only wires inputs to it.
NONE = "(none)"
NO_REPLICATE = "__no_replicate__"     # CT-R1 F5: a name no column has, so "(none)" really is none
# every refusal or failure of an analysis becomes a message, never a dead session (CT-R1 F1);
# Shiny's own SilentException (from req) is re-raised before these are caught
STAT_ERRORS = (Exception, SystemExit)


class Stale(Exception):
    """The pickers still name columns of the PREVIOUS file (they are being rebuilt): wait."""


# The engine words its messages for the command line; the app names its own controls instead.
# CT-R2 N5/N13: ONE mapping, applied to everything the app shows or writes that came from the
# engine (messages, notes, warnings, status line, figure sentence, key text, the report on screen
# and the report in the ZIP). First whole engine phrases, longest first; then every remaining
# `--option [value]` through the control tables below, so no `--word` can reach the user.
PHRASES = [
    ("(the statistical unit chosen: --unit plaque)", "(Statistical unit = per plaque)"),
    ("choose --equal-var no (Welch)", "set Variances to unequal (Welch)"),
    ("pass --log-y-drop-nonpositive", "tick “Hide values ≤ 0 on the log axis”"),
    ("--log-y-drop-nonpositive", "“Hide values ≤ 0 on the log axis”"),
]
# option -> the app control that sets it; option -> {value: the choice's name in that control}
OPTION_CONTROLS = {
    "unit": "Statistical unit", "parametric": "Test type", "equal-var": "Variances",
    "posthoc": "Compare to", "control": "Compare to", "center": "Centre marker",
    "error": "Error bar", "palette": "Colour theme", "order": "Samples", "value": "Value column",
    "annotate": "Brackets", "log-y": "Log y-axis", "height": "Height", "width": "Width",
    "group": "Group column", "replicate": "Replicate column", "subgroup": "Subgroup",
    "title": "Title", "ylabel": "Y-axis label", "legend": "Place key on figure",
    "equivalence-margin": "equivalence margin", "metric": "Metric to plot",
    "detect": "Difference to detect",
}
OPTION_VALUES = {
    "unit": {"replicate": "per plate", "plaque": "per plaque", "auto": "auto"},
    "parametric": {"nonparametric": "non-parametric", "parametric": "parametric", "auto": "auto"},
    "equal-var": {"yes": "equal", "no": "unequal", "auto": "auto"},
    "posthoc": {"dunnett": "each sample vs a control (Dunnett)", "auto": "all pairs"},
    "annotate": {"letters": "letters", "all": "all pairs", "auto": "significant pairs",
                 "adjacent": "neighbours", "none": "none"},
    "center": {"mean": "mean", "median": "median"},
    "error": {"sd": "SD", "sem": "SEM", "ci95": "95% CI", "iqr": "IQR", "none": "none", "auto": "auto"},
}
_OPTION = re.compile(r"`?--([a-z][a-z0-9-]*)(?: ([A-Za-z0-9-]+))?`?")


def _option_words(m):
    opt, val = m.group(1), m.group(2)
    ctl = OPTION_CONTROLS.get(opt, opt.replace("-", " "))
    shown = OPTION_VALUES.get(opt, {}).get(val) if val else None
    if shown is not None:
        return "%s = %s" % (ctl, shown)
    return ctl + (" " + val if val else "")


def app_words(msg):
    """Engine text in the app's words (CT-R2 N5/N13): no `--option` survives."""
    msg = str(msg)
    for cli, app in PHRASES:
        msg = msg.replace(cli, app)
    return _OPTION.sub(_option_words, msg)


SPREAD_ADVICE = "Welch ANOVA + Games-Howell is the safer analysis"


def with_advice(warnings, equal_var):
    """CT-R2 N13: the engine's spread warning recommends Welch; the app says where to set it."""
    out = []
    for w in warnings:
        w = app_words(w)
        if SPREAD_ADVICE in w and equal_var != "no":
            w += " Set Variances to unequal to follow this advice."
        out.append(w)
    return out


def message_of(e, path=None, name=None):
    """Plain message of an engine refusal, without the CLI's '[error] ' prefix, in the app's
    words; the server's temporary upload name is replaced by the user's file name."""
    m = getattr(e, "message", None) if isinstance(e, ps.StatsError) else None
    m = m or str(e) or e.__class__.__name__
    m = m[len("[error] "):] if m.startswith("[error] ") else m
    if path and name:
        m = m.replace(os.path.basename(str(path)), name)
    return app_words(m)


_PANDAS_TEXT = re.compile(r"tokenizing|C error|Expected \d+ fields|ParserError|codec can't|UnicodeDecodeError",
                          re.I)


def read_upload(path, name=None):
    """(DataFrame, parse info) with the engine's reader: delimiter sniffed (comma, semicolon,
    tab), decimal commas, labels kept as typed; a file that parses to ONE column is refused
    (CT-R1 F4). Raises StatsError with a plain message."""
    name = name or os.path.basename(str(path))
    not_csv = ("could not read %s: this does not look like a CSV table (is it an Excel or binary file "
               "saved with a .csv name?)" % name)
    try:
        return ps.read_table(path, return_info=True)
    except ps.StatsError as e:
        # the engine's own plain message is shown as it is, unless it carries raw pandas text
        if _PANDAS_TEXT.search(getattr(e, "message", "") or str(e)):
            raise ps.StatsError(not_csv)
        raise
    except Exception:                                       # noqa: BLE001 -- never raw pandas text
        # CT-R2 N12: an Excel / binary file saved as .csv used to show "Error tokenizing data..."
        if str(name).lower().endswith((".xlsx", ".xls")):
            raise ps.StatsError("could not read %s as a spreadsheet (is it really an Excel file?)." % name)
        raise ps.StatsError(not_csv)


def layout_of(df):
    """LONG (a value column AND a metric column, any case) or WIDE (CT-R1 F2, F18).
    A file with `value` but no `metric` is WIDE: `value` is then an ordinary column."""
    cols = [str(c) for c in df.columns]
    vcol, mcol = ps._resolve_col(cols, "value"), ps._resolve_col(cols, "metric")
    if vcol is not None and mcol is not None:
        mets = [str(m) for m in dict.fromkeys(ps._labels(df[mcol]).dropna())]
        return {"long": True, "value_col": vcol, "metric_col": mcol, "metrics": mets}
    return {"long": False, "value_col": None, "metric_col": None, "metrics": []}


def _pick(cands, pool, default=None):
    low = {str(c).lower(): c for c in pool}                 # case-insensitive (REPLICATE, PHAGE, ...)
    for cand in cands:
        if str(cand).lower() in low:
            return low[str(cand).lower()]
    return default


def value_choices(df, exclude=()):
    """WIDE: the numeric columns that are not labels; LONG: the metric names. CT-R2 N14: the
    columns chosen as Group or Replicate are never offered as the value (a numeric sample
    name or plate number is a label here, not a measurement)."""
    lay = layout_of(df)
    if lay["long"]:
        return lay["metrics"]
    skip = {str(x) for x in exclude if x}
    return [str(c) for c in ps.numeric_columns(df) if str(c) not in skip]


def picker_defaults(df):
    cols = [str(c) for c in df.columns]
    group = _pick(["group", "sample", "phage", "strain", "condition"], cols, cols[0] if cols else None)
    rep = _pick(["replicate", "plate"], cols, NONE)
    vals = value_choices(df, (group, rep))
    if layout_of(df)["long"]:
        value = vals[0] if vals else None
    else:
        value = _pick(["diameter_mm", "value"], vals, vals[0] if vals else None)
    return {"group": group, "replicate": rep, "value": value}


def replicate_arg(rep_in):
    """The replicate column handed to the engine: NO_REPLICATE for '(none)' (CT-R1 F5)."""
    return rep_in if (rep_in and rep_in != NONE) else NO_REPLICATE


def group_levels(df, group):
    """The sample names of a column, as typed, in order of appearance."""
    if group not in [str(c) for c in df.columns]:
        return []
    return [str(g) for g in dict.fromkeys(ps._labels(df[group]).dropna())]


def check_selection(df, sel):
    """CT-R1 F1: every picker must name a column of the CURRENT frame. A new file used to be
    analysed with the previous file's column names and the engine's SystemExit killed the
    session. Raises Stale while the pickers catch up."""
    cols = [str(c) for c in df.columns]
    if not len(df):
        raise ps.StatsError("the file has a header (%s) but no data rows." % ", ".join(cols))
    if not value_choices(df):
        raise ps.StatsError("the file has no numeric column to analyse (columns: %s). Add a "
                            "measurement column such as diameter_mm." % ", ".join(cols))
    if not sel.get("group") or sel["group"] not in cols:
        raise Stale()
    skip = (sel["group"], sel.get("replicate"))
    if not value_choices(df, skip):
        raise ps.StatsError("every numeric column is also chosen as Group or Replicate (columns: %s), "
                            "so there is no measurement left to analyse. Pick other Group / Replicate "
                            "columns, or add a measurement column such as diameter_mm." % ", ".join(cols))
    if sel.get("value") not in value_choices(df, skip):
        raise Stale()
    for k in ("replicate", "subgroup"):
        v = sel.get(k)
        if v and v != NONE and v not in cols:
            raise Stale()
    if sel.get("order"):
        lv = set(group_levels(df, sel["group"]))
        if not set(sel["order"]) <= lv:
            raise Stale()


ERROR_CHOICES = {"mean": {"auto": "auto (SEM)", "sd": "SD", "sem": "SEM", "ci95": "95% CI",
                          "iqr": "IQR", "none": "none"},
                 # CT-R1: SD / SEM describe a mean, so a median offers only IQR, CI or none
                 "median": {"auto": "auto (IQR)", "iqr": "IQR", "ci95": "95% CI (bootstrap)",
                            "none": "none"}}


def palette_choice(name, custom, needed):
    """(palette, hint). A named theme wins; a custom list is checked with the engine's
    clean_palette (hex with or without #, commas, semicolons or spaces) and a bad entry is
    named in a StatsError (CT-R1 F13). `hint` says when the custom box is being ignored."""
    custom = (custom or "").strip()
    if custom and not [x for x in re.split(r"[,;\s]+", custom) if x]:
        # CT-R2 N10: ",,," holds no colour: it is "no custom palette", and it must not stand in
        # for one (the engine's cleaner returns its default list, which switched coloured violins on)
        note = ("The custom palette box holds no colours (only separators), so it is ignored; "
                "type hex codes such as #0072B2, #D55E00.")
        if name and name in ps.PALETTES:
            return list(ps.PALETTES[name]), ""
        return None, note
    if name and name in ps.PALETTES:
        hint = ("The custom palette is not used while a colour theme is chosen; set the theme "
                "to “(custom below)” to use it." if custom else "")
        return list(ps.PALETTES[name]), hint
    if custom:
        return ps.clean_palette(custom, needed=needed), ""
    return None, ""


def literal_text(x):
    """CT-R2 N7: a Title / axis label is drawn exactly as typed: every `$` is escaped, so a
    `$...$` pair is never turned into mathtext (and a lone `$` never raises)."""
    return x if x is None else re.sub(r"\$", r"\\$", str(x))


def build_opts(sel, n_colours):
    """The engine options for the current inputs (ps.DEFAULTS + the app's controls)."""
    opts = dict(ps.DEFAULTS)
    opts.update(unit=sel["unit"], parametric=sel["parametric"], center=sel["center"],
                error=sel["error"], violin_fill=sel["violin_fill"], frame=bool(sel["frame"]),
                show_n=bool(sel["show_n"]), show_value=bool(sel["show_value"]),
                show_points=bool(sel["show_points"]), annotate=sel["brackets"],
                equal_var=sel["equal_var"], log_y=bool(sel["log_y"]),
                log_y_drop_nonpositive=bool(sel["log_y"] and sel["log_drop"]),
                width=float(sel["width"]), height=float(sel["height"]),
                legend=bool(sel["place_key"]),
                detect=sel.get("detect"),
                title=literal_text(sel["title"]) or None, ylabel=literal_text(sel["ylabel"]) or None)
    pal, hint = palette_choice(sel["palette_name"], sel["palette_custom"], n_colours)
    if pal is not None:
        opts["palette"] = pal
        if sel["violin_fill"] == "auto":
            opts["violin_fill"] = "group"
    return opts, hint


def check_subgroup(df, sel):
    """CT-R2 N11: a Subgroup that cannot work is refused with a plain message (it used to give
    "0 of 0 comparisons tested" and an empty table). Judged on the selected samples."""
    sg, g, rep = sel.get("subgroup"), sel["group"], sel.get("replicate")
    if not sg or sg == NONE:
        return
    if sg == g:
        raise ps.StatsError("Subgroup is the same column as Group (%s). Pick a different column for the "
                            "second factor, or set Subgroup to (none)." % sg)
    if rep and rep != NONE and sg == rep:
        raise ps.StatsError("Subgroup is the Replicate (plate) column (%s): every plate would become "
                            "its own subgroup. Pick a different column for the second factor, or set "
                            "Subgroup to (none)." % sg)
    lab = pd.DataFrame({"g": ps._labels(df[g]), "s": ps._labels(df[sg])})
    lab = lab[lab["g"].isin(sel.get("order") or lab["g"].unique())].dropna()
    levels = list(dict.fromkeys(lab["s"]))
    if len(levels) < 2:
        raise ps.StatsError("The Subgroup column %s has only one level (%s) in the selected samples, so "
                            "there is nothing to compare. Pick another column, or set Subgroup to (none)."
                            % (sg, levels[0] if levels else "no values"))
    if not (lab.groupby("g")["s"].nunique() >= 2).any():
        raise ps.StatsError("In none of the selected samples does the Subgroup column %s have two or "
                            "more levels, so no subgroup can be compared with a control within a "
                            "sample. Pick another column, or set Subgroup to (none)." % sg)


def in_app_words(a, sel):
    """CT-R2 N5/N13: every engine text of the analysis, in the app's words, once."""
    for k in ("sentence", "fig_sentence"):
        a[k] = app_words(a[k])
    a["notes"] = [app_words(n) for n in a["notes"]]
    a["warnings"] = with_advice(a["warnings"], sel.get("equal_var"))
    return a


def compute(df, sel, info=None):
    """The whole analysis of the current inputs (CT-R1 F1-F3, F5, F8, F10, F11, F13, F25 and the
    new Variances / Compare to / Letters / log-y options). Returns a plain dict; every refusal is
    a StatsError (or Stale while the pickers catch up)."""
    check_selection(df, sel)
    lay = layout_of(df)
    rep = replicate_arg(sel["replicate"])
    sg = sel.get("subgroup")
    grouped = bool(sg and sg != NONE)
    mcol = ps._resolve_col([str(c) for c in df.columns], "metric")
    if not lay["long"] and mcol is not None:
        # CT-R1 F2: a metric column with several levels next to a WIDE value column would pool
        # different measurements (diameter + area ...) into one sample
        mets = group_levels(df, mcol)
        if len(mets) > 1:
            raise ps.StatsError(
                "this file has a %r column with %d metrics (%s) but no 'value' column, so %r would "
                "pool them into one sample. Rename the number column to 'value' (LONG layout: then "
                "pick the metric), or keep one metric per file." % (mcol, len(mets), ", ".join(mets),
                                                                   sel["value"]))
    if not sel.get("order"):
        raise ps.StatsError("No sample is selected under “Samples (in this order)”. Pick at least one.")
    if grouped:
        check_subgroup(df, sel)
        d, metric = ps.normalize_grouped(df, sel["group"], sg, sel["value"], rep, "metric")
    else:
        d, metric = ps.normalize(df, sel["group"], sel["value"], rep, "metric")
    notes = ps.data_notes(d)
    present = list(dict.fromkeys(d["group"]))
    order = ps.resolve_order([g for g in sel["order"] if g in present], present, "Samples")
    gone = [g for g in present if g not in order]
    if gone:
        notes.append("%d rows not analysed: %s not selected." % (int(d["group"].isin(gone).sum()),
                                                                 ", ".join(gone)))
    d = d[d["group"].isin(order)].reset_index(drop=True)
    if grouped:
        subs = list(dict.fromkeys(d["subgroup"]))
        ctrl = sel.get("control")
        control = ctrl if ctrl in subs else (subs[0] if subs else None)
        sub_order = [control] + [s for s in subs if s != control]
        opts, hint = build_opts(sel, len(sub_order))
        opts.update(order=order, _sublabel=sg, control=None, detect=None)   # no power sentence in grouped mode
    else:
        opts, hint = build_opts(sel, len(order))
        opts["order"] = order
        ctl = sel.get("compare")
        if ctl and ctl != "all" and ctl not in order:
            # CT-R2 N14: a control that is no longer among the samples is not an error: back to all
            # pairs, and say so
            notes.append("Compare to was “%s”, which is not among the selected samples, so all pairs "
                         "are compared." % ctl)
            ctl = None
        opts["posthoc"], opts["control"] = ("dunnett", ctl) if (ctl and ctl != "all") else ("auto", None)
    o = ps._plot_opts(opts)                       # centre / error / palette refusals, before any test
    _mask, log_note = ps._log_guard(d["value"].values, o)
    if log_note:
        notes.append(log_note[0].upper() + log_note[1:] + ".")
    base = dict(d=d, metric=metric, order=order, opts=opts, palette_hint=hint, notes=notes,
                parse_note=(info or {}).get("note", ""), layout="LONG" if lay["long"] else "WIDE",
                rows_read=int(d.attrs.get("rows_read", len(df))))
    if grouped:
        summ, comp, unit, ginfo = ps.grouped_stats(d, order, sub_order, control, sel["parametric"],
                                                    unit=sel["unit"], return_info=True)
        have_rep = unit == "replicate"
        base.update(mode="grouped", group_order=order, sub_order=sub_order, control=control,
                    summ=summ, comp=comp, unit=unit, have_rep=have_rep,
                    warnings=list(ginfo["warnings"]), notes=notes + list(ginfo["notes"]),
                    sentence=ps.paste_sentence(metric, comp=comp, unit=unit, control=control, opts=opts),
                    fig_sentence=ps.figure_sentence(o, have_rep, list(summ["n_units"]), grouped=True))
        return in_app_words(base, sel)
    omni, posthoc, unit, have_rep = ps.run_stats(
        d, order, sel["unit"], sel["parametric"], equal_var=sel["equal_var"],
        posthoc=opts["posthoc"], control=opts["control"], detect=opts.get("detect"))
    summ = ps.group_summary(d, order, unit=unit)
    centers = ps.center_table(d, order, o)
    rm = ps.replicate_means(d)
    src = rm if (unit == "replicate" and rm is not None) else d
    base.update(mode="single", omni=omni, posthoc=posthoc, unit=unit, have_rep=have_rep, summ=summ,
                unit_means=src.groupby("group")["value"].mean().to_dict(),
                warnings=list(omni.get("warnings", [])), notes=notes + list(omni.get("notes", [])),
                sentence=ps.paste_sentence(metric, summ, omni, unit, have_rep, opts, centers=centers),
                fig_sentence=ps.figure_sentence(o, have_rep, list(summ["n_units"])))
    return in_app_words(base, sel)


def make_figure(a):
    if a["mode"] == "grouped":
        return ps.plot_grouped(a["d"], a["group_order"], a["sub_order"], a["control"],
                               a["opts"], a["metric"], a["comp"])
    return ps.plot_violin(a["d"], a["order"], a["opts"], a["metric"], a["posthoc"])


def fig_bytes(fig, fmt, dpi=300):
    buf = io.BytesIO()
    with matplotlib.rc_context(ps._FIG_RC):
        fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight", facecolor="white")
    return buf.getvalue()


def file_base(a):
    """Figure file name stem, the same in single downloads and in the ZIP (CT-R1 F23)."""
    return ("grouped_%s" if a["mode"] == "grouped" else "violin_%s") % ps._safe(a["metric"])


def figure_size_in(fig, png, dpi=300):
    """(width, height) in inches of the figure as saved: the engine's final size when it exposes
    one (fig.final_size_in / fig.figure_size_in_final), else the PNG's pixels / dpi (CT-R2 N6)."""
    for name in ("final_size_in", "figure_size_in_final"):
        v = getattr(fig, name, None)
        try:
            v = v() if callable(v) else v
            if v is not None and len(v) == 2 and float(v[0]) > 0 and float(v[1]) > 0:
                return float(v[0]), float(v[1])
        except Exception:                                   # noqa: BLE001 -- fall through
            pass
    import struct
    w, h = struct.unpack(">II", png[16:24])
    return w / float(dpi), h / float(dpi)


def size_line(size, sel):
    """CT-R2 N6: the size the figure really has, and why when it is not the slider size."""
    w, h = size
    sw, sh = float(sel["width"]), float(sel["height"])
    line = "figure: %.1f x %.1f in" % (w, h)
    why = []
    if h > sh + 0.15:
        why.append("the key is below the plot, so it is taller than the Height slider" if sel["place_key"]
                   else "it is taller than the Height slider (long labels or notes need room)")
    if w > sw + 0.15:
        why.append("it is wider than the Width slider (long labels need room)")
    return line + (": " + "; ".join(why) if why else "")


def status_line(a):
    """CT-R1 F25: under the figure, what was tested on what, n, and what bar and whisker are."""
    if a["mode"] == "grouped":
        c = a["comp"]
        n_ok = int(c["p"].notna().sum()) if len(c) else 0
        head = ("Each subgroup vs the control %s within its group (%s on %s): %d of %d comparisons "
                "tested." % (a["control"], ", ".join(sorted(set(map(str, c["test"])))) if len(c) else "no test",
                             "plate means" if a["unit"] == "replicate" else "plaques", n_ok, len(c)))
    else:
        o = a["omni"]
        n = o.get("n_per_group") or {}
        nn = ", ".join("%s %s" % (g, n[g]) for g in a["order"] if g in n)
        head = "%s, %s, on %s (%s per sample: %s)." % (
            o.get("test", "n/a"), ps.p_text(o.get("p", float("nan"))),
            "plate means" if a["unit"] == "replicate" else "single plaques",
            "N plates" if a["unit"] == "replicate" else "n plaques", nn or "n/a")
    return app_words(head + " " + a["fig_sentence"])


def summary_lines(a):
    """Parse line + data notes + engine warnings, for the message box above the results."""
    lines = []
    if a.get("parse_note"):
        lines.append("File: %s %s layout. %d rows used." % (a["parse_note"], a["layout"], len(a["d"])))
    lines += ["Note: " + app_words(n) for n in a.get("notes", [])]
    lines += ["⚠ " + w for w in a.get("warnings", [])]
    if a.get("palette_hint"):
        lines.append("Note: " + a["palette_hint"])
    return lines


def table_image(df, base, title, formats=("png", "svg", "pdf")):
    """A plain table image (used for the grouped tables in the ZIP, CT-R1 F23)."""
    disp = df.copy()
    for c in disp.columns:
        if pd.api.types.is_float_dtype(disp[c]):
            disp[c] = disp[c].map(lambda x: "" if x != x else "%.3g" % x)
    with matplotlib.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(figsize=(min(16, 1.6 + 1.05 * len(disp.columns)), 0.6 + 0.32 * (len(disp) + 1)))
        ax.axis("off")
        ax.set_title(legend_key.safe_text(title), fontsize=11, fontweight="bold", loc="left")
        t = ax.table(cellText=[[legend_key.safe_text(str(v)) for v in r] for r in disp.values.tolist()],
                     colLabels=[str(c) for c in disp.columns], loc="center", cellLoc="center")
        t.auto_set_font_size(False); t.set_fontsize(8.5); t.scale(1, 1.3)
        t.auto_set_column_width(range(len(disp.columns)))
        for fmt in formats:
            fig.savefig("%s.%s" % (base, fmt), dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)


def report_words(txt, equal_var, src_name=None):
    """CT-R2 N5/N13: a text file of the engine's output in the app's words, with the same
    'set Variances' advice the screen gives (a line at a time). CT-R2 N14: the report names the
    uploaded file where the engine can only say "in-memory table"."""
    if src_name:
        txt = txt.replace("in-memory table", src_name)
    out = []
    for ln in txt.split("\n"):
        out.append(with_advice([ln], equal_var)[0] if SPREAD_ADVICE in ln else app_words(ln))
    return "\n".join(out)


def zip_bytes(df, a, sel, src_name=None, src_bytes=None):
    """CT-R1 F23: the ZIP is the engine's full output set for EXACTLY the analysis on screen
    (same frame, columns, samples and order, options), plus the input file, the grouped table
    images, and a run_config without any server temp path."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = os.path.join(tmp, "out")
        args = dict(a["opts"])
        args.update(data=df, group=sel["group"], value=sel["value"],
                    replicate=replicate_arg(sel["replicate"]), metric="metric", out=outdir,
                    formats=["png", "svg", "pdf"], order=list(a["order"]), legend_key=True)
        args.pop("_stamp", None)
        if a["mode"] == "grouped":
            args.update(subgroup=sel["subgroup"], control=a["control"], sub_order=list(a["sub_order"]),
                        unit=sel["unit"])
        res = ps.run(args)
        if a["mode"] == "grouped":
            mt = ps._safe(res["metric"])
            table_image(res["summary"], os.path.join(outdir, "grouped_table_%s" % mt),
                        "Summary per sample and %s — %s" % (sel["subgroup"], res["metric"]))
            if len(res["comparisons"]):
                cmp_ = res["comparisons"][["group", "subgroup", "control", "mean_control", "mean_subgroup",
                                           "change_pct", "n_control", "n_subgroup", "test", "p", "signif"]]
                table_image(cmp_, os.path.join(outdir, "control_comparisons_table_%s" % mt),
                            "Each %s vs the control %s — %s" % (sel["subgroup"], a["control"], res["metric"]))
        for fn in os.listdir(outdir):                 # no server temp path in run_config (F23)
            if fn.startswith("run_config") and fn.endswith(".json"):
                p = os.path.join(outdir, fn)
                with open(p, encoding="utf-8") as fh:
                    cfg = json.load(fh)
                cfg.pop("out", None)
                cfg["data"] = src_name or "example data"
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, indent=2, default=str)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(outdir)):
                if fn.endswith((".md", ".txt")):          # the report in the app's words (N5/N13)
                    with open(os.path.join(outdir, fn), encoding="utf-8") as fh:
                        z.writestr(fn, report_words(fh.read(), sel.get("equal_var"), src_name))
                else:
                    z.write(os.path.join(outdir, fn), fn)
            if src_bytes is not None:                 # the input data itself (F23)
                z.writestr("input_" + os.path.basename(src_name or "data.csv"), src_bytes)
        return buf.getvalue()


def key_zip_bytes(fig, base):
    """The stand-alone legend key (PNG + SVG + PDF) + its text starter, named like the ZIP's."""
    key = legend_key.from_figure(fig)
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        paths = legend_key.write_key_files(key, os.path.join(tmp, base), ["png", "svg", "pdf"]) if key else []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fp in paths:
                if fp.endswith(".txt"):                   # the text starter in the app's words (N5)
                    with open(fp, encoding="utf-8") as fh:
                        z.writestr(os.path.basename(fp), app_words(fh.read()))
                else:
                    z.write(fp, os.path.basename(fp))
    return buf.getvalue()


# --------------------------------------------------------------------------- UI
CSS = """
/* CT-R1 F20: text outputs wrap instead of running off the page */
pre.shiny-text-output, .shiny-text-output { white-space: pre-wrap; word-break: break-word; }
#fig_preview img { width: 100%; height: auto; display: block; }
.ct-msg { white-space: pre-wrap; }
.ct-status { font-size: .9em; color: #33413c; margin: .4em 0 .6em; }
a.shiny-download-link.ct-off { pointer-events: none; opacity: .45; }
/* CT-R1 F20: on a phone the data controls come first, above the results */
@media (max-width: 575.98px) {
  h1.bslib-page-title { white-space: normal; font-size: 1.15rem; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout { display: flex !important; flex-direction: column;
                                                        height: auto !important; min-height: 0; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > * { flex: 0 0 auto; }
  html body div.bslib-sidebar-layout.bslib-sidebar-layout > .sidebar { order: -1; }
}
"""
JS = """
/* CT-R1 F24: downloads are disabled until there is an analysis to download */
/* CT-R2 N14: "Load example data" empties the file box (it kept the old file's name) */
Shiny.addCustomMessageHandler('ct_clear_file', function(m) {
  var f = document.getElementById(m.id); if (!f) return;
  f.value = '';
  var g = f.closest('.input-group'); var t = g && g.querySelector('input[type=text]'); if (t) t.value = '';
  var pr = document.getElementById(m.id + '_progress');
  if (pr) { pr.style.visibility = 'hidden'; var b = pr.querySelector('.progress-bar');
            if (b) { b.style.width = '0%'; b.textContent = ''; } }
  Shiny.setInputValue(m.id, null);
});
Shiny.addCustomMessageHandler('ct_downloads', function(ok) {
  document.querySelectorAll('a.shiny-download-link').forEach(function(a) {
    a.classList.toggle('ct-off', !ok); a.setAttribute('aria-disabled', ok ? 'false' : 'true');
  });
});
"""

app_ui = ui.page_sidebar(
    ui.sidebar(
        # data controls first (CT-R1 F20: on a phone the sidebar is shown above the results)
        ui.input_file("file", "Data file (CSV / TSV / XLSX)",
                      accept=[".csv", ".tsv", ".txt", ".xlsx", ".xls"]),
        ui.input_action_button("load_example", "Load example data", class_="btn-sm"),
        ui.hr(),
        ui.output_ui("col_pickers"),
        ui.output_ui("value_picker"),             # CT-R2 N14: follows Group / Replicate
        ui.output_ui("subgroup_picker"),
        ui.output_ui("order_picker"),
        ui.output_ui("control_picker"),
        ui.hr(),
        ui.input_select("unit", "Statistical unit",
                        {"auto": "auto (plate if replicates)", "replicate": "per plate",
                         "plaque": "per plaque"}),
        ui.input_select("parametric", "Test type",
                        {"auto": "auto", "parametric": "parametric", "nonparametric": "non-parametric"}),
        # CT-R1 F11: controls with no effect in the grouped (two-factor) mode are hidden there
        ui.panel_conditional(
            "!input.subgroup || input.subgroup === '(none)'",
            ui.input_select("equal_var", "Variances",
                            {"auto": "auto (Welch when Levene rejects equal spread; "
                                     "needs 8+ plates per sample to detect it)",
                             "yes": "equal (ANOVA + Tukey)",
                             "no": "unequal (Welch ANOVA + Games-Howell)"}),
            ui.output_ui("compare_picker"),
            ui.input_numeric("detect", "Difference to detect (optional, in the unit of the measurement)",
                             None, min=0),
            ui.input_select("violin_fill", "Violin fill",
                            {"auto": "auto (grey when plates)", "neutral": "neutral grey",
                             "group": "coloured by sample"})),
        ui.panel_conditional(
            "input.subgroup && input.subgroup !== '(none)'",
            ui.p("Two-factor mode: Variances, Compare to and Violin fill do not apply (each subgroup "
                 "is compared with the control within its group).", class_="text-muted small")),
        ui.input_select("center", "Centre marker", {"mean": "mean", "median": "median"}),
        ui.input_select("error", "Error bar", ERROR_CHOICES["mean"]),
        ui.input_select("brackets", "Brackets",
                        {"auto": "significant pairs", "all": "all pairs", "adjacent": "neighbours",
                         "letters": "letters (compact letter display)", "none": "none"}),
        ui.input_select("palette_name", "Colour theme",
                        {"": "(custom below)", "okabe": "Okabe-Ito", "set2": "Set2",
                         "tab10": "Tab10", "warm": "Warm", "cool": "Cool", "grays": "Grays"}),
        ui.input_text("palette_custom", "Custom palette (hex, comma-separated)", ""),
        ui.input_checkbox("show_points", "Show plaque points", True),
        ui.input_checkbox("show_n", "Show n on top", True),
        ui.input_checkbox("show_value", "Show value (mean/median)", True),
        ui.input_checkbox("frame", "Box the plot (frame)", False),
        ui.input_checkbox("log_y", "Log y-axis", False),
        ui.panel_conditional("input.log_y",
                             ui.input_checkbox("log_drop", "Hide values ≤ 0 on the log axis "
                                               "(they stay in the statistics)", False)),
        ui.input_text("title", "Title", ""),
        ui.input_text("ylabel", "Y-axis label", ""),
        ui.input_slider("width", "Width (in)", 4, 16, 9, step=0.5),
        ui.input_slider("height", "Height (in)", 3, 12, 5.4, step=0.2),
        width=330, open="always",
    ),
    ui.tags.style(CSS),
    ui.tags.script(JS),
    ui.output_ui("messages"),
    ui.navset_tab(
        ui.nav_panel("Plot",
                     ui.output_ui("fig_preview"),
                     ui.div(ui.output_text("size_text"), class_="ct-status", id="size_line"),
                     ui.div(ui.output_text("status"), class_="ct-status"),
                     ui.div(ui.download_button("dl_png", "PNG"),
                            ui.download_button("dl_svg", "SVG (editable)"),
                            ui.download_button("dl_pdf", "PDF (editable)"),
                            ui.download_button("dl_key", "Legend key (PNG + SVG + PDF)"),
                            ui.input_checkbox("place_key", "Place key on figure", True)),
                     ui.h6("Legend text starter"),
                     ui.output_text_verbatim("key_text"),
                     ui.tags.button("Copy", class_="btn btn-sm btn-outline-secondary",
                                    onclick="navigator.clipboard.writeText("
                                            "document.getElementById('key_text').innerText)")),
        ui.nav_panel("Statistics",
                     ui.h5("Omnibus test"), ui.output_text_verbatim("omni"),
                     ui.h5("Pairwise comparisons (on the statistical unit)"),
                     ui.output_data_frame("pairwise"),
                     ui.download_button("dl_pairwise", "Download pairwise CSV"),
                     ui.h5("Paste-ready sentence"), ui.output_text_verbatim("sentence")),
        ui.nav_panel("Summaries",
                     ui.h5("Per group"), ui.output_data_frame("summary_group"),
                     ui.download_button("dl_sumg", "Download group summary CSV"),
                     ui.h5("Per plate (replicate means)"), ui.output_data_frame("summary_rep"),
                     ui.download_button("dl_sumr", "Download per-plate CSV"),
                     ui.hr(),
                     ui.markdown("**Everything in one file** — the figure (PNG/SVG/PDF) with its "
                                 "legend key and text starter, the summary and test tables (CSV and "
                                 "images), the report, your input file and `run_config.json`:"),
                     ui.download_button("dl_all", "⬇  Download EVERYTHING (ZIP)", class_="btn-primary")),
        ui.nav_panel("Learn", ui.HTML(LEARN)),
        ui.nav_panel("Interactive guide",
                     ui.tags.iframe(src="guide/GUIDE.html",
                                    style="width:100%;height:80vh;border:1px solid #dde3e0;border-radius:8px;")),
        ui.nav_panel("Data format", ui.HTML(FORMAT_HELP)),
    ),
    title="Plaque Stats & Violins  ·  Python / Shiny",
)


def server(input, output, session):
    raw = reactive.value(None)            # the current frame (None = nothing loaded)
    info = reactive.value(None)           # its parse info
    load_error = reactive.value("")       # CT-R1 F19: a failed upload stays visible
    source = reactive.value((None, None))  # (file name, bytes) for the ZIP
    compare_note = reactive.value("")     # CT-R2 N14: "Compare to" fell back to all pairs
    seen = {}                             # the frame the value picker last started from

    def _set_data(df, inf, name, data):
        raw.set(df); info.set(inf); source.set((name, data)); load_error.set(""); compare_note.set("")

    @reactive.effect
    @reactive.event(input.file)
    def _load_file():
        f = input.file()
        if not f:
            return
        name, path = f[0]["name"], f[0]["datapath"]
        try:
            df, inf = read_upload(path, name)
            with open(path, "rb") as fh:
                data = fh.read()
        except STAT_ERRORS as e:
            raw.set(None); info.set(None); source.set((None, None))       # clear the old results
            load_error.set("Could not use %s: %s" % (name, message_of(e, path, name)))
            return
        _set_data(df, inf, name, data)

    @reactive.effect
    @reactive.event(input.load_example)
    async def _load_example():
        await session.send_custom_message("ct_clear_file", {"id": "file"})
        try:
            p = _example_wide_path()
            df, inf = read_upload(p)
            with open(p, "rb") as fh:
                data = fh.read()
        except STAT_ERRORS as e:
            load_error.set("Could not load the example data: %s" % message_of(e))
            return
        _set_data(df, inf, "example_data_wide.csv", data)

    def _in(name, default=None):
        """An input that may not exist yet (dynamic pickers)."""
        try:
            return input[name]()
        except Exception:                                   # noqa: BLE001 -- SilentException / missing
            return default

    @render.ui
    def col_pickers():
        df = raw.get()
        if df is None:
            return ui.p("Upload a file or click “Load example data”.")
        cols = [str(c) for c in df.columns]
        dflt = picker_defaults(df)
        return ui.TagList(
            ui.input_select("group", "Group column", {c: c for c in cols}, selected=dflt["group"]),
            ui.input_select("replicate", "Replicate (plate) column",
                            {NONE: NONE, **{c: c for c in cols}}, selected=dflt["replicate"]))

    @render.ui
    def value_picker():
        # CT-R2 N14: a separate output so that choosing Group / Replicate refreshes the value
        # choices without rebuilding the Group and Replicate selects themselves
        df = raw.get()
        if df is None:
            return ui.HTML("")
        lay = layout_of(df)
        vals = value_choices(df, (_in("group"), _in("replicate")))
        with reactive.isolate():
            cur = _in("value") if seen.get("df") is df else None   # a new file starts from the defaults
        seen["df"] = df
        dflt = picker_defaults(df)["value"]
        pick = cur if cur in vals else (dflt if dflt in vals else (vals[0] if vals else None))
        if lay["long"]:
            return ui.input_select("value", "Metric to plot (LONG file: column %s)" % lay["metric_col"],
                                   {m: m for m in vals}, selected=pick)
        return ui.input_select("value", "Value column", {c: c for c in vals}, selected=pick)

    @render.ui
    def subgroup_picker():
        df = raw.get()
        if df is None:
            return ui.HTML("")
        cols = [str(c) for c in df.columns]
        return ui.input_select("subgroup", "Subgroup — 2nd factor (optional, e.g. host)",
                               {NONE: NONE, **{c: c for c in cols}}, selected=NONE)

    @render.ui
    def order_picker():
        # CT-R1 F8: the samples are picked from the names in the data, in the order clicked;
        # rebuilt (all samples, file order) whenever the file or the group column changes.
        df = raw.get()
        g = _in("group")
        if df is None or not g:
            return ui.HTML("")
        lv = group_levels(df, g)
        return ui.input_selectize("order", "Samples (in this order)", {x: x for x in lv}, selected=lv,
                                  multiple=True, remove_button=True)

    @render.ui
    def compare_picker():
        df = raw.get()
        g = _in("group")
        lv = group_levels(df, g) if (df is not None and g) else []
        picked = _in("order")                       # CT-R2 N14: only the samples still selected
        if picked is not None:
            lv = [x for x in lv if x in picked]
        with reactive.isolate():
            cur = _in("compare", "all")
        ch = {"all": "all pairs", **{x: "each sample vs %s (Dunnett)" % x for x in lv}}
        return ui.input_select("compare", "Compare to", ch, selected=cur if cur in ch else "all")

    @reactive.effect
    def _compare_fallback():
        """CT-R2 N14: removing the Compare-to control from the samples puts Compare to back on
        'all pairs' and says so (the note stays until the user picks another control)."""
        order = _in("order")
        if order is None:
            return
        with reactive.isolate():
            cur = _in("compare", "all")
        df, g = raw.get(), _in("group")
        levels = group_levels(df, g) if (df is not None and g) else []
        if cur and cur != "all" and cur in levels and cur not in order:   # removed by the user
            compare_note.set("Compare to was “%s”, which is no longer among the samples, so it is back "
                             "on “all pairs”." % cur)
            ui.update_select("compare", selected="all")

    @reactive.effect
    @reactive.event(input.compare)
    def _compare_changed():
        if input.compare() != "all":
            compare_note.set("")

    @render.ui
    def control_picker():
        df = raw.get()
        sg = _in("subgroup")
        if df is None or not sg or sg == NONE or sg not in [str(c) for c in df.columns]:
            return ui.HTML("")
        levels = group_levels(df, sg)
        return ui.input_select("control", "Control level (of %s)" % sg, {c: c for c in levels},
                               selected=levels[0] if levels else None)

    @reactive.effect
    @reactive.event(input.center)
    def _error_choices():
        ch = ERROR_CHOICES.get(input.center(), ERROR_CHOICES["mean"])
        with reactive.isolate():
            cur = input.error()
        ui.update_select("error", choices=ch, selected=cur if cur in ch else "auto")

    def _detect():
        """CT-R2: the optional 'Difference to detect' (None when the box is empty)."""
        try:
            v = input.detect()
        except Exception:                                   # noqa: BLE001
            return None
        return None if v is None or v != v else float(v)

    def _sel():
        return {"group": _in("group"), "value": _in("value"), "replicate": _in("replicate", NONE),
                "subgroup": _in("subgroup", NONE), "control": _in("control"),
                "order": list(_in("order", ()) or ()), "compare": _in("compare", "all"),
                "unit": input.unit(), "parametric": input.parametric(), "equal_var": input.equal_var(),
                "center": input.center(), "error": input.error(), "violin_fill": input.violin_fill(),
                "brackets": input.brackets(), "palette_name": input.palette_name(),
                "palette_custom": input.palette_custom(), "show_points": input.show_points(),
                "show_n": input.show_n(), "show_value": input.show_value(), "frame": input.frame(),
                "log_y": input.log_y(), "log_drop": input.log_drop(), "title": input.title(),
                "ylabel": input.ylabel(), "width": input.width(), "height": input.height(),
                "place_key": input.place_key(), "detect": _detect()}

    @reactive.calc
    def result():
        """{'ok': analysis} | {'error': message} | {'wait': True}. Never raises (CT-R1 F1)."""
        df = raw.get()
        if df is None:
            return {"wait": True}
        sel = _sel()
        try:
            return {"ok": compute(df, sel, info.get()), "sel": sel}
        except Stale:
            return {"wait": True}
        except SilentException:
            raise
        except STAT_ERRORS as e:
            return {"error": message_of(e)}

    def analysis():
        r = result()
        req("ok" in r)
        return r["ok"]

    @reactive.calc
    def figure_png():
        """CT-R1 F12: the preview and the PNG download are the SAME bytes."""
        a = analysis()
        fig = make_figure(a)
        try:
            png = fig_bytes(fig, "png")
            return {"png": png, "key": legend_key.from_figure(fig),
                    "note": getattr(fig, "annotation_note", ""), "size": figure_size_in(fig, png)}
        finally:
            plt.close(fig)

    @reactive.effect
    async def _downloads_enabled():
        r = result()
        await session.send_custom_message("ct_downloads", bool("ok" in r))

    @render.ui
    def messages():
        r = result()
        out = []
        if load_error.get():
            out.append(ui.div(load_error.get(), class_="alert alert-danger ct-msg"))
        if compare_note.get():
            out.append(ui.div(compare_note.get(), class_="alert alert-info ct-msg small"))
        if "error" in r:
            out.append(ui.div("Cannot analyse with these settings: " + r["error"],
                              class_="alert alert-warning ct-msg"))
        elif "ok" in r:
            lines = summary_lines(r["ok"])
            if lines:
                out.append(ui.div("\n".join(lines), class_="alert alert-light ct-msg small"))
        return ui.TagList(*out)

    @render.ui
    def fig_preview():
        try:
            png = figure_png()["png"]
        except SilentException:
            raise
        except STAT_ERRORS as e:                          # a refusal made while drawing
            return ui.div("Cannot draw the figure: " + message_of(e), class_="alert alert-warning")
        src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        return ui.img(src=src, alt="figure preview (the same image as the PNG download)")

    @render.text
    def size_text():
        r = result()
        req("ok" in r)
        return size_line(figure_png()["size"], r["sel"])

    @render.text
    def status():
        return status_line(analysis())

    @render.data_frame
    def summary_group():
        a = analysis()
        return a["summ"].round(4)

    @render.data_frame
    def summary_rep():
        a = analysis()
        rm = ps._plate_means_gs(a["d"]) if a["mode"] == "grouped" else ps.replicate_means(a["d"])
        return (rm.round(4) if rm is not None else pd.DataFrame({"note": ["no replicate column"]}))

    def _pairwise_df(a):
        if a["mode"] == "grouped":
            c = a["comp"]
            if not len(c):
                return pd.DataFrame({"note": ["no non-control subgroups to compare"]})
            return c[["group", "subgroup", "control", "mean_control", "mean_subgroup",
                      "change_pct", "cohens_d", "test", "p", "signif"]].copy()
        pw = a["omni"].get("pairwise") or []
        if not pw:
            return pd.DataFrame({"note": ["need ≥2 samples"]})
        return pd.DataFrame(pw)

    @render.data_frame
    def pairwise():
        df = _pairwise_df(analysis()).copy()
        for c in ("p", "p_adj"):
            if c in df.columns:
                df[c] = df[c].map(ps.fmt_p)
        return df.round(4)

    @render.text
    def omni():
        a = analysis()
        if a["mode"] == "grouped":
            c = a["comp"]
            nsig = int((c["p"] < 0.05).sum()) if len(c) else 0
            msg = ("Grouped control comparison vs '%s' (unit: %s). %d of %d subgroup-vs-control "
                   "tests significant at p < 0.05 (table below)." % (a["control"], a["unit"], nsig, len(c)))
        else:
            o = a["omni"]
            msg = "%s: %s  (unit: %s, parametric = %s, min n = %d per sample)" % (
                o["test"], ps.p_text(o["p"]), a["unit"], o["parametric_used"], o.get("min_n", 0))
            if o.get("posthoc"):
                msg += "\nPairwise: %s" % o["posthoc"]
        for w in a.get("warnings", []):
            msg += "\n\n⚠ " + w
        return app_words(msg)

    @render.text
    def sentence():
        return analysis()["sentence"]          # CT-R1 F10: the engine's paste_sentence(), app words

    @render.download(filename=lambda: file_base(analysis()) + ".png")
    def dl_png():
        yield figure_png()["png"]

    def _vector(fmt):
        fig = make_figure(analysis())
        try:
            return fig_bytes(fig, fmt)
        finally:
            plt.close(fig)

    @render.download(filename=lambda: file_base(analysis()) + ".svg")
    def dl_svg():
        yield _vector("svg")

    @render.download(filename=lambda: file_base(analysis()) + ".pdf")
    def dl_pdf():
        yield _vector("pdf")

    @render.text
    def key_text():
        key = figure_png()["key"]               # the key of the figure as it is drawn right now
        return app_words(legend_key.text_starter(key) or "(no sample colours to key)")

    @render.download(filename=lambda: file_base(analysis()) + "_legend_key.zip")
    def dl_key():
        fig = make_figure(analysis())
        try:
            yield key_zip_bytes(fig, file_base(analysis()))
        finally:
            plt.close(fig)

    @render.download(filename=lambda: "summary_by_group_%s.csv" % ps._safe(analysis()["metric"]))
    def dl_sumg():
        yield analysis()["summ"].to_csv(index=False)

    @render.download(filename=lambda: "summary_by_replicate_%s.csv" % ps._safe(analysis()["metric"]))
    def dl_sumr():
        a = analysis()
        rm = ps._plate_means_gs(a["d"]) if a["mode"] == "grouped" else ps.replicate_means(a["d"])
        yield (rm.to_csv(index=False) if rm is not None else "note,no replicate column\n")

    @render.download(filename=lambda: "pairwise_tests_%s.csv" % ps._safe(analysis()["metric"]))
    def dl_pairwise():
        yield _pairwise_df(analysis()).to_csv(index=False)

    @render.download(filename=lambda: "plaque_stats_all.zip")
    def dl_all():
        r = result()
        req("ok" in r)
        name, data = source.get()
        yield zip_bytes(raw.get(), r["ok"], r["sel"], name, data)


app = App(app_ui, server, static_assets={"/guide": HERE})   # serves GUIDE.html + its assets at /guide/
