// =====================================================================
//  Plaque Toolkit — hand-label plaques in Fiji / ImageJ
// ---------------------------------------------------------------------
//  INSTALL (once):  Plugins > Macros > Install...  -> pick this file.
//  Two commands then appear at the bottom of the  Plugins > Macros  menu:
//     "PT: set up plaque labelling"   (shortcut 1)
//     "PT: save plaque labels"        (shortcut 2)
//
//  WORKFLOW:
//   1. Open your plate photo (File > Open).
//   2. Run  "PT: set up plaque labelling".
//   3. Draw an OVAL over each plaque; press  t  after each to add it to the ROI Manager.
//   4. Run  "PT: save plaque labels"  ->  writes  plaque_labels_<image>.csv  next to the image.
//   5. File it into the training store:  labelling\Import Fiji labels.bat  (drop the CSV on it).
//
//  Measurements are taken in PIXELS (the scale is cleared) so the Plaque Toolkit importer can
//  apply the SAME mm-per-pixel the app uses. You supply that mm/px at import time.
// =====================================================================

macro "PT: set up plaque labelling [1]" {
    if (nImages == 0) {
        showMessage("Open a plate first",
            "Open your plate photo (File > Open), then run this again.");
        run("Open...");
    }
    run("Set Scale...", "distance=0 known=0 pixel=1 unit=pixel");     // clear scale -> pixels
    run("Set Measurements...", "area centroid bounding redirect=None decimal=3");
    roiManager("reset");
    setTool("oval");
    showMessage("Label the plaques",
        "Draw an OVAL over each plaque, and press  t  after each one to add it to the ROI Manager.\n \n"
        + "Tips: hold Shift while dragging for a circle; delete mistakes from the ROI Manager.\n \n"
        + "When you're done, run  'PT: save plaque labels'.");
}

macro "PT: save plaque labels [2]" {
    n = roiManager("count");
    if (n == 0) {
        showMessage("No plaques yet",
            "Draw plaque ovals and press  t  to add them to the ROI Manager first.");
    } else {
        roiManager("Deselect");
        run("Clear Results");
        roiManager("Measure");
        dir = getDirectory("image");
        if (dir == "") dir = getDirectory("Choose where to save the labels");
        title = getTitle();
        csv = dir + "plaque_labels_" + title + ".csv";
        saveAs("Results", csv);
        roiManager("Save", dir + "RoiSet_" + title + ".zip");
        showMessage("Saved " + n + " plaque labels",
            "Saved:\n" + csv + "\n \n"
            + "Now file them into the training store — run\n"
            + "   labelling\\Import Fiji labels.bat\n"
            + "and drop that CSV on it (it will ask for the image + mm/px).");
    }
}
