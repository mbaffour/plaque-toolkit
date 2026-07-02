==================================================================
  PLAQUE TOOLKIT  -  INSTALL & RUN  (read me first)
==================================================================

WHAT THIS IS
  Plaque Toolkit (nicknamed "Frankenstein's Plaque Lab" - it stitches
  several tools into one) is a desktop app to measure bacteriophage
  plaques from Petri-dish photos: size (mm), count, and turbidity. It
  detects plaques automatically, lets you correct them by hand, and
  exports CSV + annotated figures. iPhone HEIC photos work directly.

  Windows 10 / 11, 64-bit. No Python, no setup, nothing else needed
  - the detection engine (incl. the "Precise" AI model) is built in.


HOW TO INSTALL  (about a minute)

  1. Double-click   PlaqueToolkitFullSetup.exe

  2. Windows may show a blue "Windows protected your PC" box
     (because the app is not code-signed - this is normal, it is
     not a virus). Click:
            More info  ->  Run anyway

  3. Follow the installer. It does NOT need administrator rights.

  4. When it finishes, launch "Plaque Toolkit (full)" from the
     Start menu (or the desktop shortcut if you ticked that box).


HOW TO MEASURE  (about 30 seconds)

  1. On the "Measure" tab, set the dish size in mm (default 100).
  2. Click "Open image..." (or drag a photo onto the window).
  3. Pick an engine in the dropdown - "Precise" is best for hard
     or dense plates; "Published (validated)" for paper numbers.
  4. The plaques are detected and outlined, numbered 1..N from the
     top. Review them in the editor: click to add/erase, drag to
     draw, zoom with the wheel.
  5. Click the green  "Export all"  button - one click writes the
     CSV table + the annotated figure to an "out" folder next to
     your image, and opens that folder. ("More" has individual
     options: CSV only, side-by-side, Fiji crop, labels.)

  More tabs:
    * Batch    - measure a whole folder of plates at once
    * Compare  - turbidity comparison across phages
    * Validate - score the engines against your own corrections
    * Help menu (top bar) - full guides, incl. the interactive
                            guide.html


CALIBRATE FOR YOUR OWN SETUP  (important - do this once)

  The tool works with ANY camera, phone, height, or zoom. You do NOT
  enter camera settings - the mm scale is measured from each photo
  using a real object of known size in the frame. So different setups
  are fine; each just needs its own calibration.

  Do this:
   * Use the "Set plate" tool: click 3 points on the real agar rim
     (where the plaques are), then type that circle's DIAMETER in mm.
   * IMPORTANT: the "90 mm / 100 mm" printed on the dish box is the
     LID diameter. Your plaques sit on the smaller AGAR base (often
     ~85 mm). Measure and enter the AGAR diameter, not the lid - using
     the lid size makes every measurement wrong by the same factor.
   * No ruler needed, but a ruler laid in the plane of the agar is an
     even more direct way to set the scale, and a good one-time check.

  Why setup doesn't matter: moving the camera closer/farther or
  zooming only changes how many PIXELS the dish spans; because you
  tell the tool the dish's real mm, it computes the correct mm/pixel
  automatically for that photo. Just shoot straight-on (a tilted,
  elliptical dish biases the scale - the app warns you when it does).

  VALIDATE ON YOUR OWN PLATES: any accuracy numbers in the docs were
  measured on one specific setup. For your own paper, validate on a
  few of your plates (Validate tab + your hand-corrected labels)
  before reporting counts or sizes.


GOOD TO KNOW

  * "Precise" takes ~1 minute on its FIRST run (it loads the AI
    model); after that it is quick.
  * "Precise" and "Sensitive" are in-house extensions and are NOT
    independently validated - use "Published (validated)" for any
    measurement you will report in a paper.

  Built on the peer-reviewed Plaque Size Tool:
  Trofimova E, Jaschke PR. Virology 2021;561:1-5.
  doi:10.1016/j.virol.2021.05.011
==================================================================
