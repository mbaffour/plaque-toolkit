"""Click-through round 4 (targeted re-check): the three polish findings.

N1  the plate figures' dotted "size not used" outline (drawn (0, 230, 230)) was named "bluish green"
    in the legend text starter; it must be named as drawn ("cyan").
N2  the desktop rewrote the engine's "`--annotate letters` gives ..." sentence to one starting with a
    lowercase "choose" after a full stop.
N3  (R app, pinned in tests/r_ct_r1_check.R as R4_N3_*): "1 plates".
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "plaque_stats"))

import legend_key as lk  # noqa: E402


def test_n1_size_not_used_outline_is_named_as_drawn():
    import plaque_gui as pg
    rgb = pg.PLAQUE_CLASSES["nosize"][1]
    assert lk.colour_name("#%02X%02X%02X" % rgb) == "cyan"


def test_n1_true_cyan_changes_no_word_of_a_shipped_palette():
    # every colour a shipped palette or a plate class uses keeps the word it had before the
    # true-cyan reference was added (only the dotted outline moved from "bluish green" to "cyan")
    import matplotlib.colors as mc
    import plaque_gui as pg
    import plaque_stats as ps
    cols = {mc.to_hex(c).upper() for pal in ps.PALETTES.values() for c in pal}
    cols |= {"#%02X%02X%02X" % v[1] for v in pg.PLAQUE_CLASSES.values()}
    without = [e for e in lk.COLOUR_NAMES if e != ("cyan", "#00E5E5")]
    assert len(without) == len(lk.COLOUR_NAMES) - 1
    ref = [(n, lk._srgb_to_lab(mc.to_rgb(h))) for n, h in without]
    saved = list(lk._NAME_LAB)
    try:
        lk._NAME_LAB[:] = ref
        before = {c: lk.colour_name(c) for c in cols}
    finally:
        lk._NAME_LAB[:] = saved
    after = {c: lk.colour_name(c) for c in cols}
    changed = {c: (before[c], after[c]) for c in cols if before[c] != after[c]}
    assert changed == {"#00E6E6": ("bluish green", "cyan")}


def test_n2_annotate_sentence_starts_with_a_capital():
    from app import study_tab
    engine = ("Every pair is in the pairwise table. `--annotate letters` gives a compact letter "
              "display, `--annotate all` every bracket.")
    out = study_tab._ui_words(engine)
    assert "table. Choose Brackets: Letters" in out, out
    assert "--" not in out
