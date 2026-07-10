Your figures and tables land here
---------------------------------
Each analysis run writes these (suffixed by the measurement, e.g. _diameter_mm):
  violin_<metric>.png / .svg / .pdf      the Violin SuperPlot figure
  summary_by_group.csv                   n, mean, SD, SEM, 95% CI, median, IQR ...
  summary_by_replicate.csv               the per-plate means the statistics use
  stats_table_<metric>.png/.svg/.pdf     slide-ready descriptive-stats table
  pairwise_table_<metric>.*              every pairwise comparison (+ CSV)
  report_<metric>.md                     plain-language + paste-ready sentence
  run_config.json                        every setting + package versions
SVG and PDF keep text EDITABLE in Inkscape / Illustrator.
(The browser app also lets you download PNG / SVG / PDF straight from the Plot tab.)
