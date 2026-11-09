"""legend_key.py -- the one helper behind every figure's *legend key*.

A legend key is a small stand-alone image that lists every plotted sample / group with the
exact colour, marker, fill and line type it has in the figure, next to its display name, in
the figure's own font -- plus a plain-text "legend text starter" ready to paste into a figure
legend, e.g. ``WT (orange, filled violin with dark orange outline); plate1 (blue, filled
circles with black outline)``.

How it stays honest (one source of truth):

* A plotting function builds its colour/marker mapping first (a dict such as
  ``{sample: "#E69F00"}``), draws the figure FROM that dict, and turns the same dict into a
  list of key *entries* with :func:`entry`. It then calls :func:`attach` so the figure carries
  its own key (``fig.legend_key``).
* The embedded key (:func:`embed`, drawn on the figure) and the stand-alone key
  (:func:`key_figure` / :func:`save_key`) are both drawn by :func:`legend_handles` from the
  SAME entries, so they list the same names with the same styles by construction.
* Callers never keep a copy: they read :func:`from_figure` on the figure they just drew, so
  a rename or a recolour shows up the next time the figure is drawn.

The module lives inside ``plaque_stats/`` so the stand-alone Plaque Stats package (flat
``py-modules`` wheel, frozen app) ships it; the desktop app and the root scripts import it as
``from plaque_stats import legend_key``. It only needs matplotlib, never pyplot (safe inside
Qt worker threads).
"""
from __future__ import annotations

import os

import matplotlib
from matplotlib import colors as mcolors

# --------------------------------------------------------------------------- colour words
# The shared spec's table: plain names for the text starter, matched in CIE Lab.
COLOUR_NAMES = [
    ("black", "#000000"), ("dark grey", "#595959"), ("grey", "#808080"),
    ("light grey", "#BFBFBF"), ("white", "#FFFFFF"), ("red", "#E41A1C"),
    ("dark red", "#8B0000"), ("orange", "#FF7F00"), ("yellow", "#FFD700"),
    ("green", "#4DAF4A"), ("dark green", "#006400"), ("teal", "#008080"),
    ("cyan", "#00BFFF"), ("blue", "#377EB8"), ("dark blue", "#00008B"), ("navy", "#000080"),
    ("purple", "#984EA3"), ("magenta", "#FF00FF"), ("pink", "#F781BF"), ("brown", "#A65628"),
    ("olive", "#808000"), ("gold", "#DAA520"), ("sky blue", "#56B4E9"),
    ("vermillion", "#D55E00"), ("bluish green", "#009E73"), ("reddish purple", "#CC79A7"),
    ("yellow-green", "#9ACD32"),
]

MARKER_WORDS = {
    "o": "circles", ".": "circles", "s": "squares", "^": "triangles (up)",
    "v": "triangles (down)", "D": "diamonds", "d": "diamonds", "+": "plus signs",
    "P": "plus signs", "x": "crosses", "X": "crosses", "*": "stars",
}
LINE_WORDS = {"-": "solid", "solid": "solid", "--": "dashed", "dashed": "dashed",
              ":": "dotted", "dotted": "dotted", "-.": "dot-dash", "dashdot": "dot-dash"}


def _srgb_to_lab(rgb):
    """sRGB (0-1 floats) -> CIE L*a*b* (D65)."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(c)) for c in rgb[:3])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 1.00000
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (24389.0 / 27.0 * t + 16.0) / 116.0
    fx, fy, fz = f(x), f(y), f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


_NAME_LAB = [(n, _srgb_to_lab(mcolors.to_rgb(h))) for n, h in COLOUR_NAMES]


def colour_name(colour):
    """Nearest plain colour name (CIE76 distance in Lab) for any matplotlib colour."""
    lab = _srgb_to_lab(mcolors.to_rgb(colour))
    return min(_NAME_LAB, key=lambda nl: sum((a - b) ** 2 for a, b in zip(lab, nl[1])))[0]


def to_hex(colour):
    """Literal hex of a matplotlib colour (``None``/``"none"`` stay ``None``)."""
    if colour is None or (isinstance(colour, str) and colour.lower() == "none"):
        return None
    return mcolors.to_hex(colour, keep_alpha=False).upper()


# --------------------------------------------------------------------------- entries
def entry(label, colour, kind="marker", marker="o", filled=True, edge=None, linestyle=None,
          linewidth=None, alpha=1.0, size=7.0, shape=None, section=None, extra_marker=None):
    """One row of a key.

    kind     -- "marker" (a scatter mark), "line" (a line), "patch" (a filled area such as a
                violin or histogram bar).
    colour   -- the fill colour (marker face / patch face) or the line colour, exactly as drawn.
    edge     -- outline colour as drawn (None = same as ``colour``; "none" = no outline).
    marker   -- matplotlib marker code for "marker" entries.
    filled   -- False draws an open marker (face "none", outline ``colour``).
    linestyle-- for "line" entries (and patch outlines when not solid).
    shape    -- the word used for a patch in the text starter ("violin", "bars", ...).
    extra_marker -- optional dict(marker=, colour=, edge=, alpha=, size=, filled=) drawn ON TOP
                of a patch, for a violin that also carries points of the same colour.
    """
    e = {"label": str(label), "kind": kind, "colour": to_hex(colour),
         "edge": ("none" if (isinstance(edge, str) and edge.lower() == "none") else to_hex(edge)),
         "marker": marker if kind == "marker" else None, "filled": bool(filled),
         "linestyle": linestyle, "linewidth": linewidth, "alpha": float(alpha),
         "size": float(size), "shape": shape, "section": section, "extra_marker": None}
    if extra_marker:
        em = dict(extra_marker)
        em["colour"] = to_hex(em.get("colour"))
        ed = em.get("edge")
        em["edge"] = "none" if (isinstance(ed, str) and ed.lower() == "none") else to_hex(ed)
        em.setdefault("marker", "o"); em.setdefault("alpha", 1.0); em.setdefault("size", 6.0)
        em.setdefault("filled", True)
        e["extra_marker"] = em
    return e


def make_key(entries, title=None, fontsize=9.0, title_fontsize=None, frameon=False,
             font_family=None):
    """Bundle a figure's entries with the legend styling both the embedded and the stand-alone
    key use. ``font_family`` defaults to the font matplotlib resolves right now (call this while
    the figure's own rcParams are in force)."""
    if font_family is None:
        font_family = resolved_font_family()
    return {"entries": list(entries), "title": title, "fontsize": float(fontsize),
            "title_fontsize": float(title_fontsize if title_fontsize is not None else fontsize),
            "frameon": bool(frameon), "font_family": font_family}


def resolved_font_family():
    """The concrete family name matplotlib uses for text under the current rcParams."""
    from matplotlib import font_manager as fm
    try:
        path = fm.findfont(fm.FontProperties(family=matplotlib.rcParams["font.family"]))
        return fm.get_font(path).family_name
    except Exception:                               # noqa: BLE001 -- never break a figure
        fam = matplotlib.rcParams.get("font.family") or ["sans-serif"]
        return fam[0] if isinstance(fam, (list, tuple)) else str(fam)


def attach(fig, key):
    """Store the key on the figure it describes (read back with :func:`from_figure`)."""
    fig.legend_key = key
    return key


def from_figure(fig):
    """The key a figure was drawn with, or None for a figure that encodes no sample/group."""
    return getattr(fig, "legend_key", None)


# --------------------------------------------------------------------------- drawing
def _marker_handle(m, colour, edge, alpha, size, filled):
    from matplotlib.lines import Line2D
    face = colour if filled else "none"
    if edge == "none":
        mec = colour if not filled else "none"
    else:
        mec = edge or colour
    return Line2D([0], [0], marker=m, linestyle="none", markerfacecolor=face,
                  markeredgecolor=mec, markersize=size, alpha=alpha,
                  markeredgewidth=1.0 if (not filled or edge not in (None, "none")) else 0.0)


def _handle(e):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    if e["kind"] == "header":
        return Line2D([], [], linestyle="none", marker=None)
    if e["kind"] == "line":
        return Line2D([0, 1], [0, 0], color=e["colour"], linestyle=e["linestyle"] or "-",
                      linewidth=e["linewidth"] or 1.5, alpha=e["alpha"])
    if e["kind"] == "patch":
        ec = None if e["edge"] == "none" else (e["edge"] or e["colour"])
        p = Patch(facecolor=e["colour"], edgecolor=ec if ec else "none", alpha=e["alpha"],
                  linewidth=e["linewidth"] if e["linewidth"] is not None else 0.9,
                  linestyle=e["linestyle"] or "-")
        em = e.get("extra_marker")
        if em:
            return (p, _marker_handle(em["marker"], em["colour"], em["edge"], em["alpha"],
                                      em["size"], em["filled"]))
        return p
    return _marker_handle(e["marker"] or "o", e["colour"], e["edge"], e["alpha"], e["size"],
                          e["filled"])


def rows(key):
    """The rows a key draws: the entries, with a bold section header in front of each section
    when a key mixes sections (e.g. samples and plates). A single-section key uses its section
    name as the legend title instead."""
    entries = key["entries"]
    sections = list(dict.fromkeys(e.get("section") for e in entries))
    if len(sections) <= 1:
        return [dict(e) for e in entries], (key.get("title") or (sections[0] if sections else None))
    out = []
    for s in sections:
        if s:
            out.append({"label": str(s), "kind": "header"})
        out.extend(dict(e) for e in entries if e.get("section") == s)
    return out, key.get("title")


def legend_handles(key):
    """(handles, labels, header_flags, title) for a key -- the ONE place both the embedded and
    the stand-alone key are drawn from."""
    rws, title = rows(key)
    return ([_handle(r) for r in rws], [r["label"] for r in rws],
            [r["kind"] == "header" for r in rws], title)


def _legend_kwargs(key):
    from matplotlib.font_manager import FontProperties
    from matplotlib.legend_handler import HandlerTuple
    return {"prop": FontProperties(family=key["font_family"], size=key["fontsize"]),
            "frameon": key["frameon"], "handler_map": {tuple: HandlerTuple(ndivide=1)}}


def _finish_legend(leg, headers, key):
    for t, h in zip(leg.get_texts(), headers):
        if h:
            t.set_fontweight("bold")
    title = leg.get_title()                    # title font set here: works on matplotlib < 3.6 too
    title.set_fontfamily(key["font_family"]); title.set_fontsize(key["title_fontsize"])
    return leg


def embed(target, key, **placement):
    """Draw the key ON a figure (``target`` = an Axes or a Figure). ``placement`` carries the
    figure's own legend conventions (loc, bbox_to_anchor, ...); default is just outside the
    top-right corner of the axes, which never covers data."""
    if not key or not key.get("entries"):
        return None
    handles, labels, headers, title = legend_handles(key)
    kw = _legend_kwargs(key)
    if not placement:
        placement = {"loc": "upper left", "bbox_to_anchor": (1.005, 1.0)}
    kw.update(placement)
    leg = target.legend(handles, labels, title=title, **kw)
    return _finish_legend(leg, headers, key)


def key_figure(key):
    """The stand-alone key: a bare matplotlib Figure (no pyplot) holding only the legend."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(3, 0.4 + 0.25 * max(1, len(key["entries"]))), facecolor="white")
    FigureCanvasAgg(fig)
    handles, labels, headers, title = legend_handles(key)
    kw = _legend_kwargs(key)
    leg = fig.legend(handles, labels, title=title, loc="center", **kw)
    _finish_legend(leg, headers, key)
    return fig


VECTOR_RC = {"svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42}


def save_key(key, path, dpi=300):
    """Write the stand-alone key to ``path``; the format follows the extension. Text stays text
    in SVG/PDF/EPS. Returns the path."""
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    with matplotlib.rc_context(VECTOR_RC):
        fig = key_figure(key)
        kw = {"dpi": dpi, "bbox_inches": "tight", "pad_inches": 0.05, "facecolor": "white"}
        if ext in ("tif", "tiff"):
            kw["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(path, **kw)
    return path


def key_path(figure_path, ext=None):
    """``<figure>_legend_key.<ext>`` beside a figure path (ext defaults to the figure's)."""
    base, fext = os.path.splitext(figure_path)
    return "%s_legend_key%s" % (base, ("." + ext.lstrip(".")) if ext else (fext or ".png"))


def text_path(figure_path):
    """``<figure>_legend_text.txt`` beside a figure path."""
    return "%s_legend_text.txt" % os.path.splitext(figure_path)[0]


def write_key_files(key, base, formats=("png",), dpi=300):
    """Write ``<base>_legend_key.<fmt>`` for every figure format plus ``<base>_legend_text.txt``.
    ``base`` is the figure path without its extension. Returns the paths written ([] when the
    figure has no sample/group encoding)."""
    if not key or not key.get("entries"):
        return []
    out = []
    for fmt in formats:
        out.append(save_key(key, "%s_legend_key.%s" % (base, str(fmt).lstrip(".")), dpi=dpi))
    tp = "%s_legend_text.txt" % base
    with open(tp, "w", encoding="utf-8") as fh:
        fh.write(text_starter(key) + "\n")
    out.append(tp)
    return out


# --------------------------------------------------------------------------- text starter
def _colour_words(entries):
    """Colour word per entry; when two entries with DIFFERENT colours would read the same,
    add 'light'/'dark' by lightness so the sentence still tells them apart."""
    words = [colour_name(e["colour"]) if e.get("colour") else "" for e in entries]
    by_word = {}
    for i, w in enumerate(words):
        by_word.setdefault(w, []).append(i)
    for w, idx in by_word.items():
        hexes = list(dict.fromkeys(entries[i]["colour"] for i in idx))
        if not w or len(hexes) < 2:
            continue
        light = {h: _srgb_to_lab(mcolors.to_rgb(h))[0] for h in hexes}
        ranked = sorted(hexes, key=lambda h: light[h])
        shade = {}
        for k, h in enumerate(ranked):
            if k == 0:
                shade[h] = "dark " + w
            elif k == len(ranked) - 1:
                shade[h] = "light " + w
            else:
                shade[h] = "medium " + w
        for i in idx:
            words[i] = shade[entries[i]["colour"]]
    return words


def _describe(e, word):
    edge = e.get("edge")
    outline = ""
    if edge and edge != "none" and edge != e["colour"] and colour_name(edge) not in word:
        outline = " with %s outline" % colour_name(edge)
    if e["kind"] == "line":
        return "%s, %s line" % (word, LINE_WORDS.get(e.get("linestyle") or "-", "solid"))
    if e["kind"] == "patch":
        s = "%s, filled %s%s" % (word, e.get("shape") or "area", outline)
        if e.get("linestyle") and LINE_WORDS.get(e["linestyle"], "solid") != "solid":
            s += " (%s outline)" % LINE_WORDS[e["linestyle"]]
        em = e.get("extra_marker")
        if em:
            s += " and %s %s" % ("filled" if em.get("filled", True) else "open",
                                 MARKER_WORDS.get(em.get("marker", "o"), "markers"))
        return s
    mk = MARKER_WORDS.get(e.get("marker") or "o", "markers")
    if not e.get("filled", True):
        return "%s, open %s" % (word, mk)
    return "%s, filled %s%s" % (word, mk, outline)


def text_starter(key):
    """``NAME (colour, marker/line); NAME (...); ...`` -- one clause per key entry, in key order."""
    if not key or not key.get("entries"):
        return ""
    entries = key["entries"]
    words = _colour_words(entries)
    return "; ".join("%s (%s)" % (e["label"], _describe(e, w)) for e, w in zip(entries, words)) + "."


def entries_signature(key):
    """Comparable (label, kind, colour, edge, marker, filled, linestyle) tuples -- for tests and
    for checking an embedded legend against the stand-alone key."""
    return [(e["label"], e["kind"], e.get("colour"), e.get("edge"), e.get("marker"),
             e.get("filled"), e.get("linestyle")) for e in (key or {}).get("entries", [])]
