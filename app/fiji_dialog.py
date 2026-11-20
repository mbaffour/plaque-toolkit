"""app/fiji_dialog.py — compare the app's plaques against a Fiji Results CSV by position.

Opened from 'Compare vs Fiji…' next to the measurement table. The user picks the CSV they
exported from Fiji (with Centroid X/Y + Area); the app pairs each Fiji row to the nearest
app plaque and reports the per-plaque differences + agreement stats. No matching numbers
needed — correspondence is by location."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QFileDialog, QMessageBox)

from app import fiji_match
from app.agreement import _signed as _sg          # '+0.000', never '-0.000' (CT-R3 F7)
from app.widgets import PandasTableModel, NumericSortProxy, CopyableTableView


class FijiCompareDialog(QDialog):
    def __init__(self, app_df, calibrated=True, parent=None):
        super().__init__(parent)
        self.app_df = app_df
        self.result = None
        self.setWindowTitle("Compare app vs Fiji — the same plaques, by position")
        from PySide6.QtWidgets import QApplication
        _av = QApplication.primaryScreen().availableGeometry()   # never exceed the screen
        self.resize(min(760, _av.width() - 60), min(600, _av.height() - 100))
        lay = QVBoxLayout(self)

        intro = QLabel(
            "Pair each of your Fiji measurements to the app's plaques <b>by location</b>, so you "
            "compare the <b>same</b> plaque even though the two tools number them differently.<br>"
            "In Fiji: <i>Analyze › Set Measurements</i> must include <b>Centroid</b> (X, Y) and "
            "<b>Area</b>; Measure, then <i>File › Save As</i> a Results CSV.")
        intro.setWordWrap(True); intro.setObjectName("ModeHelp")
        lay.addWidget(intro)

        row = QHBoxLayout()
        row.addWidget(QLabel("How did you open the plate in Fiji?"))
        self.align = QComboBox()
        self.align.addItem("The crop I exported from the app (exact match)", "none")
        self.align.addItem("My own image / different scale (auto-align)", "auto")
        if not calibrated:
            self.align.setCurrentIndex(1)
        self.align.setToolTip("Exact match assumes Fiji opened the app's exported crop (shared mm "
                              "frame). Auto-align estimates scale/rotation/offset from your own image.")
        row.addWidget(self.align, 1)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.pick = QPushButton("Choose Fiji Results CSV…")
        self.pick.clicked.connect(self._choose)
        self.file_lbl = QLabel("No file chosen"); self.file_lbl.setObjectName("ModeHelp")
        row2.addWidget(self.pick); row2.addWidget(self.file_lbl, 1)
        lay.addLayout(row2)

        # CT-R3 F9: a failed second file must be said: the previous result stays on screen
        self.fail_note = QLabel(""); self.fail_note.setWordWrap(True); self.fail_note.setVisible(False)
        self.fail_note.setStyleSheet("color:#b91c1c;font-weight:600")
        lay.addWidget(self.fail_note)
        self.summary = QLabel(""); self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)

        self.table = CopyableTableView()
        self.model = PandasTableModel(); self.proxy = NumericSortProxy()
        self.proxy.setSourceModel(self.model); self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True); self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAccessibleName("App vs Fiji paired differences")
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout(); btns.addStretch()
        self.save_btn = QPushButton("Save paired CSV…"); self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        btns.addWidget(self.save_btn); btns.addWidget(close)
        lay.addLayout(btns)

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Fiji Results table", "",
            "Fiji Results (*.csv *.xls *.txt *.tsv);;All files (*)")
        if not path:
            return
        try:
            fiji_df = fiji_match.load_fiji_results(path)
        except Exception as e:
            self._failed(path, str(e))
            QMessageBox.warning(self, "Couldn't read that CSV", str(e))
            return
        try:
            res = fiji_match.match(self.app_df, fiji_df, align=self.align.currentData())
        except Exception as e:
            self._failed(path, str(e))
            QMessageBox.critical(self, "Match failed", str(e))
            return
        self.fail_note.setVisible(False); self.fail_note.clear()
        self.result = res
        self.file_lbl.setText(os.path.basename(path))
        self.model.set_dataframe(res["paired"])
        # CT-R1 DA-F8: never offer to save a pairing that is probably wrong
        self.save_btn.setEnabled(not res["paired"].empty and not res["summary"].get("low_match"))
        self._show_summary(res["summary"], res["unmatched_app"], res["unmatched_fiji"])

    def _failed(self, path, why):
        """CT-R3 F9: say that the new file failed and what the table below still is."""
        msg = "Could not use %s: %s" % (os.path.basename(path), why)
        if self.result is not None:
            msg += (" The table and summary below are still the result for %s, NOT for this file."
                    % self.file_lbl.text())
        self.fail_note.setText(msg); self.fail_note.setVisible(True)

    @staticmethod
    def _idx_text(idx, limit=10):
        """At most ``limit`` indices, then 'and N more' (CT-R3 F9: 41 indices were printed)."""
        idx = list(idx)
        shown = ", ".join(str(i) for i in idx[:limit])
        return shown + (" and %d more" % (len(idx) - limit) if len(idx) > limit else "")

    def _show_summary(self, s, ua, uf):
        parts = [f"<b>Matched {s['n_matched']}</b> of {s['n_app']} app plaques "
                 f"to {s['n_fiji']} Fiji rows."]
        if s.get("aligned"):
            flip = " + mirror-flip" if s.get("reflected") else ""
            parts.append(f"Auto-aligned (scale ×{s['scale']:.3f}{flip}).")
            if s.get("reflected"):
                parts.append("<span style='color:#b45309'>Heads-up: your Fiji image is "
                             "mirror-flipped relative to the app (matched anyway). Use the app's "
                             "Orient ▾ to keep them the same way up.</span>")
        if s["bias_mean_mm"] is not None:
            parts.append(f"Mean difference (app − Fiji): <b>{_sg(s['bias_mean_mm'])} mm</b>.")
        if s["loa_low_mm"] is not None:
            parts.append(f"95% limits of agreement {_sg(s['loa_low_mm'])} … {_sg(s['loa_high_mm'])} mm.")
        if s["rmse_mm"] is not None:
            parts.append(f"RMSE {s['rmse_mm']:.3f} mm.")
        if s["pearson_r"] is not None:
            parts.append(f"r = {s['pearson_r']:.3f}.")
        if s["bias_mean_mm"] is not None and s.get("bias_sd_mm") is not None:
            # CT-R3 F9: the SAME few-pairs caveat as the agreement sentence (below 20 pairs)
            from app import agreement
            cav = agreement.prediction_clause(s["bias_mean_mm"], s["bias_sd_mm"], s["n_matched"], "mm")
            if cav:
                parts.append(cav.strip())
        if ua:
            parts.append(f"<br><span style='color:#b45309'>App plaques with no Fiji match: "
                         f"{self._idx_text(ua)}.</span>")
        if uf:
            parts.append(f"<span style='color:#b45309'>Fiji rows with no app match: "
                         f"{self._idx_text(uf)}.</span>")
        if s.get("low_match") and s["n_matched"] > 0:
            parts.insert(0, "<span style='color:#b91c1c'><b>Only %d of %d plaques matched, so this "
                            "pairing is probably wrong and cannot be saved.</b> If Fiji measured your "
                            "own image, choose 'auto-align'; check that the Fiji table is from this "
                            "plate and has Centroid X/Y.</span><br>"
                            % (s["n_matched"], min(s["n_app"], s["n_fiji"])))
        if s["n_matched"] == 0:
            parts.append("<br><b>No matches</b> — if you used your own image, switch to "
                         "'auto-align'; otherwise check you exported Centroid X/Y from Fiji.")
        self.summary.setText(" ".join(parts))

    def _save(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save paired CSV", "app_vs_fiji.csv", "CSV (*.csv)")
        if not path:
            return
        self.result["paired"].to_csv(path, index=False)
        QMessageBox.information(self, "Saved", f"Paired comparison saved to:\n{path}")
