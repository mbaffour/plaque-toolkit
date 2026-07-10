Drop your data file here   (.csv, .tsv, or .xlsx)
-------------------------------------------------
Use ONE ROW PER PLAQUE, with these columns:
  group      = the sample / phage / condition you are comparing   (required)
  replicate  = the plate a plaque came from  (recommended - stats run per-plate)
  <measurements> = your numeric columns, e.g. diameter_mm, area_mm2, turbidity
Example:   group,replicate,diameter_mm
           T4,plate1,2.34
Then double-click "Run Analysis App.bat" (upload this file), or use the CLI launcher.
