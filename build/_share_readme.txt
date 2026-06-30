==================================================================
  PLAQUE TOOLKIT  -  INSTALL & RUN  (read me first)
==================================================================

WHAT THIS IS
  A desktop app to measure bacteriophage plaques from Petri-dish
  photos: size (mm), count, and turbidity. Detects plaques
  automatically, lets you correct them by hand, and exports CSV +
  annotated figures. iPhone HEIC photos work directly.

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
  4. The plaques are detected and outlined. Review them in the
     editor: click to add/erase, drag to draw, zoom with the wheel.
  5. Click the green  Export  button (or "Save results") to write
     the CSV + annotated image.

  More tabs:
    * Batch    - measure a whole folder of plates at once
    * Compare  - turbidity comparison across phages
    * Validate - score the engines against your own corrections
    * Help menu (top bar) - full guides, incl. the interactive
                            guide.html


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
