# app.R — Plaque Stats & Violins (R-Shiny)
# ---------------------------------------------------------------------------------------------
# Interactive companion to plaque_stats.py: upload a tidy CSV of grouped plaque measurements,
# get publication-ready, customizable violin plots + statistics + data summaries, and download
# the figure (PNG/SVG/PDF) and tables. Uses the SAME data format as the Python script.
#
# Run:   R -e "shiny::runApp('plaque_stats', launch.browser=TRUE)"
#   or open app.R in RStudio and click "Run App".
# First time only, install packages:
#   install.packages(c("shiny","ggplot2","dplyr","tidyr","readr","DT","ggpubr","scales","svglite","jsonlite"))
#
# PAPER STYLE: a paper_style.json beside app.R (or wherever CFU_PAPER_STYLE points), as written by
#   CFU Plot Studio's "Save as paper style", is applied at every start: sample colours BY NAME,
#   font family, base font size, axis colour and axis line width. See README "One style for the
#   whole paper".
#
# DATA FORMAT (one row per plaque) — see README.md:
#   WIDE:  group,replicate,diameter_mm,area_mm2,turbidity   (pick the value column in the app)
#   LONG:  group,replicate,metric,value                     (pick the metric in the app)
#   group     = the sample/condition/phage you compare (required)
#   replicate = the plate / experimental unit (recommended; makes the stats per-plate)
#
# STATISTICS: plaque_run_stats() below is a port of run_stats() in plaque_stats.py -- the Python
#   engine is the reference; tests/r_ct_r1_check.R pins the two against each other.
# ---------------------------------------------------------------------------------------------

library(shiny)
library(ggplot2)
library(dplyr)
library(tidyr)
library(readr)
library(DT)
library(ggpubr)
library(jsonlite)

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0 || (length(a) == 1 && is.na(a))) b else a

OKABE_ITO <- c("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
               "#D55E00", "#F0E442", "#999999", "#000000")
# muted palette for REPLICATES (plates): points + plate means are coloured by plate (SuperPlot)
REP_PALETTE <- c("#4C6E9C", "#E0A458", "#6AAA64", "#B65C5C", "#8A78B0",
                 "#4FA3A5", "#C77CB5", "#9A8C6B", "#6C6C6C")
# CT-R1 F18: when the violins carry the SAMPLE colours, plates are drawn in greys so no plate
# marker can be mistaken for a sample colour (REP_PALETTE shares three hues with Okabe-Ito).
PLATE_GREYS <- c("#1A1A1A", "#858585", "#C2C2C2", "#525252")
# fillable marker shapes for the plate means and the matching solid shapes for the plaque
# points: a plate past the end of its palette takes the next shape, not a repeated colour.
PLATE_SHAPES <- c(21L, 22L, 24L, 23L, 25L)
POINT_SHAPES <- c(19L, 15L, 17L, 18L, 25L)
SHAPE_WORDS <- c("21" = "circles", "19" = "circles", "16" = "circles", "22" = "squares",
                 "15" = "squares", "24" = "triangles (up)", "17" = "triangles (up)",
                 "23" = "diamonds", "18" = "diamonds", "25" = "triangles (down)")
med_iqr <- function(x) data.frame(y = median(x), ymin = quantile(x, .25, names = FALSE),
                                  ymax = quantile(x, .75, names = FALSE))
PALETTES <- list(
  okabe = OKABE_ITO,
  set2  = c("#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"),
  tab10 = c("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"),
  warm  = c("#B4451F", "#D98032", "#E9B44C", "#9B2226", "#CA6702", "#BB3E03", "#AE2012", "#EE9B00"),
  cool  = c("#3D5A80", "#5E8B9E", "#98C1D9", "#293241", "#4C6E9C", "#6AAA9E", "#5C7AA0", "#7FB3C9"),
  grays = c("#4d4d4d", "#7f7f7f", "#a6a6a6", "#c9c9c9", "#2b2b2b", "#8f8f8f", "#606060", "#b8b8b8"))
THEME_CHOICES <- c("(custom hex below)" = "", "Okabe-Ito" = "okabe", "Set2" = "set2",
                   "Tab10" = "tab10", "Warm" = "warm", "Cool" = "cool", "Grays" = "grays")
# the ranges the look inputs accept (typed values and paper-style values are clamped to them)
BASE_SIZE_RANGE <- c(4, 40)
AXIS_LW_RANGE <- c(0.1, 5)

# ---------------------------------------------------------------------------------------------
# One style for the whole paper (the same semantics as CFU Plot Studio 0.4.0, whose
# paper_style.json this app reads): colours keyed by sample NAME, one font family for every
# text the figure and its key draw, and the shared look (base size, axis colour, line width).
# ---------------------------------------------------------------------------------------------
# The app folder, captured when app.R is sourced (shiny::runApp('plaque_stats') and
# source("app.R", chdir = TRUE) both make it the working directory), so the paper style is
# looked for beside app.R whatever the working directory is later.
APP_DIR <- normalizePath(getwd())
# Where the paper style lives: CFU_PAPER_STYLE if set (read at call time, so it can be set
# after the app is sourced), else paper_style.json beside app.R.
paper_style_path <- function() {
  env <- Sys.getenv("CFU_PAPER_STYLE", "")
  if (nzchar(env)) path.expand(env) else file.path(APP_DIR, "paper_style.json")
}

hex_to_lab <- function(hex) grDevices::convertColor(t(grDevices::col2rgb(hex)) / 255,
                                                    from = "sRGB", to = "Lab")
to_hex <- function(col) toupper(grDevices::rgb(t(grDevices::col2rgb(col)), maxColorValue = 255))
valid_colour <- function(x) is.character(x) && length(x) == 1 && !is.na(x) && nzchar(x) &&
  !inherits(try(grDevices::col2rgb(x), silent = TRUE), "try-error")
# smallest Lab distance from one colour to a set (Inf for an empty set)
colour_distance <- function(hex, others) {
  if (!length(others)) return(Inf)
  a <- as.numeric(hex_to_lab(hex)[1, ]); b <- hex_to_lab(others)
  min(sqrt(rowSums((b - matrix(a, nrow(b), 3, byrow = TRUE))^2)))
}
shade_colour <- function(hex, f) {             # f < 1 darkens, f > 1 lightens towards white
  m <- grDevices::col2rgb(hex)[, 1] / 255
  m <- if (f <= 1) m * f else m + (1 - m) * (1 - 1 / f)
  grDevices::rgb(m[1], m[2], m[3])
}
# CT-R1 F18: `n` colours no two of which are the same -- the pool itself first, then darker and
# lighter shades of it that are visibly different from everything already taken -- so two
# plotted samples never share a colour, however short the palette is.
distinct_colours <- function(pool, n, taken = character(0)) {
  pool <- unique(as.character(pool)); out <- character(0)
  if (n <= 0 || !length(pool)) return(out)
  used <- function() toupper(vapply(c(taken, out), to_hex, ""))
  for (p in pool) {
    if (length(out) >= n) return(out)
    if (!to_hex(p) %in% used()) out <- c(out, p)
  }
  shades <- unlist(lapply(c(0.62, 2, 0.38, 3.5), function(f) vapply(pool, shade_colour, "", f = f)))
  for (s in shades) {
    if (length(out) >= n) return(out)
    if (colour_distance(s, c(used(), "#FFFFFF")) > 12) out <- c(out, toupper(s))
  }
  if (length(out) < n) {                       # last resort: evenly spaced hues
    extra <- grDevices::hcl.colors(n - length(out) + 8, "Dark 3")
    extra <- extra[!toupper(extra) %in% used()]
    out <- c(out, utils::head(extra, n - length(out)))
  }
  if (length(out) < n) out <- c(out, rep(pool, length.out = n - length(out)))
  out
}

# The registry with every name in `names` present, existing names untouched: a new name takes
# the first colour of `pool` no other name uses; once every colour of the pool is taken it gets
# a darker / lighter shade no other name uses (CT-R1 F18: it used to recycle the pool, so two
# plotted samples could share a colour). Accepts a named list (as JSON reads back) or a vector.
extend_colour_registry <- function(registry, names, pool = OKABE_ITO) {
  reg <- unlist(registry)
  if (is.null(reg) || is.null(names(reg))) reg <- setNames(character(0), character(0))
  reg <- setNames(as.character(reg), names(reg))
  for (nm in unique(as.character(names))) {
    if (is.na(nm) || nm %in% names(reg)) next
    free <- pool[!toupper(pool) %in% toupper(reg)]
    reg[[nm]] <- if (length(free)) free[1] else distinct_colours(pool, 1, taken = unname(reg))
  }
  reg
}
# Colours for the given levels, in level order, from the registry by name. Two levels that the
# registry gives the same colour (a paper style can do that) are told apart: the later one
# takes a shade no plotted level uses; attr "changed" names them (CT-R1 F18).
registry_colours <- function(registry, levels_vec, pool = OKABE_ITO) {
  levels_vec <- as.character(levels_vec)
  reg <- extend_colour_registry(registry, levels_vec, pool)
  out <- setNames(unname(reg[levels_vec]), levels_vec)
  changed <- character(0)
  if (length(out) > 1) {
    hx <- vapply(out, to_hex, "")
    for (i in seq_along(out)[-1]) {
      if (hx[i] %in% hx[seq_len(i - 1)]) {
        out[i] <- distinct_colours(pool, 1, taken = unname(out)); hx[i] <- to_hex(out[i])
        changed <- c(changed, levels_vec[i])
      }
    }
  }
  attr(out, "changed") <- changed
  out
}

# CT-R1 F20: the typed palette, read leniently on every keystroke -- colours separated by
# commas, semicolons or spaces, with or without '#'; anything that is not a colour is left out
# and returned in `rejected` (the app names those once typing stops), never a raw R error.
parse_palette <- function(txt) {
  txt <- if (is.null(txt) || !length(txt) || is.na(txt[1])) "" else as.character(txt[1])
  tok <- trimws(strsplit(txt, "[,;[:space:]]+")[[1]]); tok <- tok[nzchar(tok)]
  if (!length(tok)) return(list(colours = character(0), rejected = character(0)))
  fixed <- ifelse(grepl("^[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$", tok), paste0("#", tok), tok)
  ok <- vapply(fixed, valid_colour, TRUE)
  cols <- fixed[ok]
  cols <- ifelse(grepl("^#[0-9A-Fa-f]{8}$", cols), substr(cols, 1, 7), cols)   # no alpha
  list(colours = unname(cols), rejected = unname(tok[!ok]))
}

# The family the figure asks for: the menu choice, or the typed name when the menu says
# Custom (blank custom falls back to the default sans).
font_family_request <- function(choice, custom = "") {
  choice <- if (is.null(choice) || !length(choice)) "sans" else as.character(choice)[1]
  if (is.na(choice)) choice <- "sans"
  if (identical(choice, "custom")) {
    custom <- if (is.null(custom) || !length(custom)) "" else trimws(as.character(custom)[1])
    if (!is.na(custom) && nzchar(custom)) custom else "sans"
  } else if (nzchar(choice)) choice else "sans"
}
# Whether this machine can draw the requested family. R's generic families are always there;
# a named font is looked up with systemfonts, which silently substitutes another family when
# the name is unknown -- so the match only counts when it comes back with the family that was
# asked for. Without systemfonts every named font is treated as unavailable.
resolve_font_family <- function(requested) {
  requested <- if (is.null(requested) || !length(requested)) "sans" else as.character(requested)[1]
  if (is.na(requested) || !nzchar(trimws(requested))) requested <- "sans"
  if (tolower(requested) %in% c("sans", "serif", "mono"))
    return(list(family = tolower(requested), available = TRUE, requested = requested))
  matched <- if (requireNamespace("systemfonts", quietly = TRUE)) {
    tryCatch(as.character(systemfonts::font_info(family = requested)$family[1]),
             error = function(e) NA_character_)
  } else NA_character_
  ok <- length(matched) == 1 && !is.na(matched) && identical(tolower(matched), tolower(requested))
  if (ok) list(family = requested, available = TRUE, requested = requested)
  else list(family = "sans", available = FALSE, requested = requested)
}
# What ggplot is handed: the default sans is "" -- exactly what theme_classic(), theme_void()
# and geom_text() use on their own -- so the default figure is drawn as it always was.
drawn_family <- function(resolved) if (identical(resolved, "sans")) "" else resolved

# CT-R1 F14: one numeric look value, clamped to its range; the note says what was done.
clamp_look <- function(x, range, default, what) {
  v <- suppressWarnings(as.numeric(x))
  if (length(v) != 1 || !is.finite(v))
    return(list(value = default, note = NULL, ok = FALSE))
  if (v < range[1] || v > range[2]) {
    cl <- min(max(v, range[1]), range[2])
    return(list(value = cl, ok = TRUE,
                note = sprintf("%s %s is outside %s-%s, so %s was used", what, format(v), format(range[1]),
                               format(range[2]), format(cl))))
  }
  list(value = v, note = NULL, ok = TRUE)
}

# combined centre + error-bar summary for the plate means: mean|median with sd|sem|ci95|iqr|none
summary_fun <- function(center, error) {
  if (error == "auto") error <- if (center == "median") "iqr" else "sem"
  function(x) {
    n <- length(x); cen <- if (center == "median") median(x) else mean(x)
    if (error == "iqr")
      return(data.frame(y = cen, ymin = quantile(x, .25, names = FALSE), ymax = quantile(x, .75, names = FALSE)))
    if (error == "none" || n < 2) return(data.frame(y = cen, ymin = cen, ymax = cen))
    s <- sd(x); sem <- s / sqrt(n); half <- switch(error, sd = s, ci95 = sem * qt(.975, n - 1), sem)
    data.frame(y = cen, ymin = cen - half, ymax = cen + half)
  }
}

# ---------------------------------------------------------------------------------------------
# Reading a data file (CT-R1 F3, F9, F10, F12). Everything is read as TEXT and converted here,
# so a comma is never taken for a thousands separator, and every file this cannot use ends in
# a plain message (a "plaque_data_problem" condition), never a raw R error or a dead session.
# ---------------------------------------------------------------------------------------------
stop_data <- function(...) stop(structure(class = c("plaque_data_problem", "error", "condition"),
                                          list(message = paste0(...), call = NULL)))
NUM_RE <- "^[+-]?([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?$"
COMMA_NUM_RE <- "^[+-]?[0-9]+,[0-9]+$"

read_plaque_table <- function(path, name = basename(path)) {
  size <- suppressWarnings(file.size(path))
  if (is.na(size)) stop_data("'", name, "' could not be opened. Choose the file again.")
  if (size == 0) stop_data("'", name, "' is empty (0 bytes). Export your measurements as CSV again and upload that file.")
  bytes <- readBin(path, "raw", n = size)
  notes <- character(0)
  utf16 <- length(bytes) >= 2 && ((bytes[1] == as.raw(0xff) && bytes[2] == as.raw(0xfe)) ||
                                  (bytes[1] == as.raw(0xfe) && bytes[2] == as.raw(0xff)))
  if (utf16) {
    txt <- tryCatch(iconv(list(bytes), "UTF-16", "UTF-8")[[1]], error = function(e) NA_character_)
    if (is.na(txt)) stop_data("'", name, "' could not be read as text. Save it as CSV (comma delimited) and upload that file.")
    notes <- c(notes, "read as UTF-16 text")
  } else {
    head_bytes <- bytes[seq_len(min(length(bytes), 20000))]
    ctrl <- sum(head_bytes < as.raw(9) | (head_bytes > as.raw(13) & head_bytes < as.raw(32)))
    if (any(head_bytes == as.raw(0)) || ctrl > 0.02 * length(head_bytes)) {
      what <- if (length(bytes) >= 2 && identical(bytes[1:2], charToRaw("PK"))) "an Excel workbook (.xlsx) or another zipped file"
              else "a binary file, not a text table"
      stop_data("'", name, "' looks like ", what, ". This app reads plain text tables: in Excel use ",
                "File > Save As > CSV (comma delimited), then upload the .csv file.")
    }
    txt <- rawToChar(bytes)
    if (!validUTF8(txt)) {                      # Excel "CSV" on Windows: Windows-1252 (µ, ±, °)
      txt <- iconv(txt, "windows-1252", "UTF-8", sub = "?")
      notes <- c(notes, "read as Windows-1252 text (an Excel CSV)")
    }
  }
  Encoding(txt) <- "UTF-8"
  txt <- sub("^﻿", "", txt)
  lines <- strsplit(txt, "\r\n|\n|\r")[[1]]
  lines <- lines[!grepl("^\\s*(#.*)?$", lines)]              # blank lines and # comment lines
  if (!length(lines))
    stop_data("'", name, "' has no data: every line is blank or a # comment.")
  # the delimiter is the one the header line uses most (outside quotes): comma, semicolon or tab
  header <- gsub('"[^"]*"', "", lines[1])
  cnt <- vapply(c(",", ";", "\t"), function(ch) lengths(regmatches(header, gregexpr(ch, header, fixed = TRUE))), 0L)
  delim <- if (max(cnt) == 0) "," else names(cnt)[which.max(cnt)]
  ext <- tolower(tools::file_ext(name))
  ext_delim <- if (ext == "tsv") "\t" else if (ext == "csv") "," else delim   # what the name promises
  delim_name <- c("," = "comma", ";" = "semicolon", "\t" = "tab")[[delim]]
  if (max(cnt) > 0 && delim != ext_delim) notes <- c(notes, paste0("columns are separated by ", delim_name, "s"))
  df <- tryCatch(suppressMessages(suppressWarnings(
    readr::read_delim(I(paste(lines, collapse = "\n")), delim = delim, quote = "\"", comment = "",
                      col_types = readr::cols(.default = readr::col_character()), na = character(),
                      trim_ws = TRUE, progress = FALSE, show_col_types = FALSE, name_repair = "unique"))),
    error = function(e) NULL)
  if (is.null(df))
    stop_data("'", name, "' could not be read as a table. Save it as CSV (comma delimited) and upload that file.")
  df <- as.data.frame(df, stringsAsFactors = FALSE, check.names = FALSE)
  names(df) <- trimws(names(df))
  for (j in seq_along(df)) { df[[j]][is.na(df[[j]])] <- ""; df[[j]] <- trimws(df[[j]]) }
  empty_col <- vapply(df, function(x) all(!nzchar(x)), TRUE) & grepl("^\\.\\.\\.[0-9]+$", names(df))
  df <- df[, !empty_col, drop = FALSE]                         # trailing delimiters from Excel
  if (ncol(df)) df <- df[rowSums(as.data.frame(lapply(df, nzchar))) > 0, , drop = FALSE]
  if (!nrow(df))
    stop_data("'", name, "' has a header row (", paste(names(df), collapse = ", "),
              ") but no data rows. Add one row per plaque and upload it again.")
  # numbers written with a decimal comma
  for (nm in names(df)) {
    x <- df[[nm]]; filled <- nzchar(x)
    comma <- grepl(COMMA_NUM_RE, x); dot <- grepl(NUM_RE, x)
    if (!any(comma) || sum(comma | dot) < 0.5 * sum(filled)) next
    if (delim == ",") {
      # CT-R1 F3: "1,932" in a comma-separated file is 1.932 to a European and 1932 to an
      # American. readr used to read it as 1932 without a word; this app will not guess.
      stop_data("Column '", nm, "' of '", name, "' has numbers written with a comma (for example \"",
                x[comma][1], "\"). In a comma-separated file that could mean ",
                sub(",", ".", x[comma][1], fixed = TRUE), " or ", sub(",", "", x[comma][1], fixed = TRUE),
                ", so nothing was loaded. Write the numbers with a decimal point (1.932), or save the ",
                "sheet as a semicolon-separated CSV, and upload it again.")
    }
    df[[nm]][comma] <- sub(",", ".", x[comma], fixed = TRUE)
    notes <- c(notes, paste0("decimal commas in '", nm, "' were read as decimal points (",
                             x[comma][1], " = ", sub(",", ".", x[comma][1], fixed = TRUE), ")"))
  }
  list(df = df, notes = notes, delim = delim)
}

# share of the filled cells of a column that are numbers; numeric columns count fully
numeric_share <- function(x) {
  if (is.numeric(x)) return(if (any(is.finite(x))) 1 else 0)
  x <- trimws(as.character(x)); x <- x[!is.na(x) & nzchar(x)]
  if (!length(x)) return(0)
  mean(is.finite(suppressWarnings(as.numeric(x))))
}
# CT-R1 F9: every column that is MOSTLY numbers is offered as a value column (one "n/a" or
# "2.5mm" cell used to make the whole column vanish from the menu).
numeric_cols <- function(df) names(df)[vapply(df, function(x) numeric_share(x) >= 0.5, TRUE)]
# CT-R1 F12: column names are matched without regard to case (GROUP, Plate, Replicate ...)
pick_col <- function(cols, candidates) {
  m <- match(candidates, tolower(trimws(cols))); m <- m[!is.na(m)]
  if (length(m)) cols[m[1]] else NA_character_
}
GROUP_NAMES <- c("group", "sample", "phage", "strain", "condition")
REPLICATE_NAMES <- c("replicate", "plate", "rep")
# LONG layout needs BOTH a `value` and a `metric` column (CT-R1 F9: `value` alone is a plain
# value column, as in plaque_stats.py)
long_cols <- function(df) {
  v <- pick_col(names(df), "value"); m <- pick_col(names(df), "metric")
  if (is.na(v) || is.na(m)) NULL else list(value = v, metric = m)
}
check_plaque_table <- function(df, name = "the file") {
  if (ncol(df) < 2)
    stop_data("Only one column was found in '", name, "' (", paste(names(df), collapse = ", "),
              "). The table needs a sample (group) column and a column of numbers, separated by ",
              "commas, semicolons or tabs.")
  if (!length(numeric_cols(df)))
    stop_data("No column of numbers was found in '", name, "' (columns: ", paste(names(df), collapse = ", "),
              "). The value column must hold numbers such as 2.34, one row per plaque.")
  invisible(TRUE)
}

# tidy frame (group factor, replicate, value) from a raw table; attr "info" says what was left
# out and why, so the app can tell the user instead of dropping rows silently
tidy_plaque_data <- function(df, group, replicate = NULL, value = NULL, metric = NULL, order = "") {
  lc <- long_cols(df)
  d <- data.frame(group = as.character(df[[group]]), stringsAsFactors = FALSE)
  d$replicate <- if (!is.null(replicate) && !identical(replicate, "(none)") && replicate %in% names(df))
    as.character(df[[replicate]]) else NA_character_
  vcol <- if (!is.null(lc)) lc$value else value
  raw_val <- trimws(as.character(df[[vcol]])); raw_val[is.na(raw_val)] <- ""
  # a numeric column is used as it is (no round trip through text); a text column is parsed
  d$value <- if (is.numeric(df[[vcol]])) as.numeric(df[[vcol]]) else suppressWarnings(as.numeric(raw_val))
  keep <- rep(TRUE, nrow(d))
  if (!is.null(lc)) keep <- as.character(df[[lc$metric]]) == metric
  keep[is.na(keep)] <- FALSE
  d <- d[keep, , drop = FALSE]; raw_val <- raw_val[keep]
  n_read <- nrow(d)
  not_num <- !is.finite(d$value) & nzchar(raw_val) & !tolower(raw_val) %in% c("na", "nan")
  blank <- !is.finite(d$value) & !not_num
  bad_examples <- utils::head(unique(raw_val[not_num]), 3)
  ok <- is.finite(d$value)
  d <- d[ok, , drop = FALSE]
  # drop blank/NA groups; treat blank/"nan" replicate labels as missing (robust to Excel gaps);
  # "1.0" labels read back from a spreadsheet are "1", as in plaque_stats.py
  d$group <- sub("\\.0$", "", trimws(d$group))
  no_group <- is.na(d$group) | tolower(d$group) %in% c("", "na", "nan", "nat", "none")
  d <- d[!no_group, , drop = FALSE]
  d$replicate <- sub("\\.0$", "", trimws(as.character(d$replicate)))
  d$replicate[tolower(d$replicate) %in% c("", "na", "nan", "nat", "none")] <- NA
  # CT-R1 F13: the order box matches names without regard to case and says what it ignored
  present <- unique(d$group)
  ord <- trimws(strsplit(if (is.null(order) || is.na(order)) "" else order, ",")[[1]]); ord <- ord[ord != ""]
  hit <- present[match(tolower(ord), tolower(present))]
  ignored <- ord[is.na(hit)]; hit <- unique(hit[!is.na(hit)])
  lev <- if (length(hit)) hit else present
  d$group <- factor(d$group, levels = lev)
  d <- d[!is.na(d$group), , drop = FALSE]
  rownames(d) <- NULL
  notes <- character(0)
  if (sum(not_num))
    notes <- c(notes, sprintf("%d of %d rows were left out because '%s' is not a number there (for example %s).",
                              sum(not_num), n_read, vcol, paste0("\"", bad_examples, "\"", collapse = ", ")))
  if (sum(blank))
    notes <- c(notes, sprintf("%d of %d rows were left out because '%s' is blank there.", sum(blank), n_read, vcol))
  if (sum(no_group))
    notes <- c(notes, sprintf("%d rows were left out because the sample (group) cell is blank.", sum(no_group)))
  if (length(ignored))
    notes <- c(notes, sprintf("Group order: %s %s not a sample in this data and %s ignored.",
                              paste0("'", ignored, "'", collapse = ", "),
                              if (length(ignored) > 1) "are" else "is", if (length(ignored) > 1) "were" else "was"))
  attr(d, "info") <- list(n_read = n_read, n_not_number = sum(not_num), n_blank = sum(blank),
                          n_no_group = sum(no_group), order_ignored = ignored, value_col = vcol, notes = notes)
  d
}

# ---------------------------------------------------------------------------------------------
# Statistics: a port of run_stats() in plaque_stats.py (the reference). Where the two could
# differ the Python rule is followed and named here with the finding it answers.
# ---------------------------------------------------------------------------------------------
fmt_p <- function(p) {                          # as _fmt_p(): "n/a", "< 0.001" or 3 decimals
  vapply(p, function(v) if (is.na(v)) "n/a" else if (v < 1e-3) "< 0.001" else formatC(v, format = "f", digits = 3), "")
}
p_eq <- function(p) {                           # "p < 0.001" / "p = 0.004" / "p = n/a" (never "p = < 0.001")
  f <- fmt_p(p); if (startsWith(f, "<")) paste("p", f) else paste("p =", f)
}
fmt_p3 <- function(p) {                         # CT-R1 F19: tables, 3 significant digits
  vapply(p, function(v) if (is.na(v)) "n/a" else if (v < 1e-3) "< 0.001"
         else formatC(signif(v, 3), digits = 3, format = "g", flag = "#"), "")
}
p_stars <- function(p) {                        # CT-R1 F11: three stars at most, as stars()
  vapply(p, function(v) if (is.na(v)) "n/a" else if (v < 1e-3) "***" else if (v < 1e-2) "**"
         else if (v < 5e-2) "*" else "ns", "")
}
# Brown-Forsythe (median-centred) Levene test on the groups with >= 2 values = scipy.stats.levene
levene_p <- function(vals) {
  vals <- vals[lengths(vals) >= 2]; k <- length(vals)
  if (k < 2) return(NA_real_)
  z <- lapply(vals, function(v) abs(v - stats::median(v)))
  n <- lengths(z); N <- sum(n); zi <- vapply(z, mean, 0); zbar <- sum(unlist(z)) / N
  W <- ((N - k) * sum(n * (zi - zbar)^2)) /
       ((k - 1) * sum(unlist(Map(function(zz, m) (zz - m)^2, z, zi))))
  if (is.nan(W)) NA_real_ else stats::pf(W, k - 1, N - k, lower.tail = FALSE)
}
anova_p <- function(gv) {                       # classic one-way ANOVA = scipy.stats.f_oneway
  gv <- gv[lengths(gv) > 0]; k <- length(gv); N <- sum(lengths(gv))
  if (k < 2 || N - k < 1) return(NA_real_)
  grand <- mean(unlist(gv)); m <- vapply(gv, mean, 0)
  ssb <- sum(lengths(gv) * (m - grand)^2)
  ssw <- sum(unlist(Map(function(v, mm) (v - mm)^2, gv, m)))
  Fs <- (ssb / (k - 1)) / (ssw / (N - k))
  if (is.nan(Fs)) NA_real_ else stats::pf(Fs, k - 1, N - k, lower.tail = FALSE)
}
# Welch's one-way ANOVA; the same number as oneway.test(var.equal = FALSE) and welch_anova_p()
welch_anova_p <- function(gv) {
  gv <- gv[lengths(gv) >= 2]; k <- length(gv)
  if (k < 2) return(NA_real_)
  n <- lengths(gv); m <- vapply(gv, mean, 0); s2 <- vapply(gv, stats::var, 0)
  if (any(s2 == 0)) return(NA_real_)
  w <- n / s2; mw <- sum(w * m) / sum(w)
  num <- sum(w * (m - mw)^2) / (k - 1)
  lam <- (3 / (k * k - 1)) * sum((1 - w / sum(w))^2 / (n - 1))
  Fs <- num / (1 + 2 * (k - 2) / 3 * lam)
  stats::pf(Fs, k - 1, if (lam > 0) 1 / lam else Inf, lower.tail = FALSE)
}
# Upper tail of the studentized range, P(Q > q) for k groups and df degrees of freedom, by
# direct numerical integration (the normal-range tail integrated over the distribution of the
# pooled SD). stats::ptukey is NOT used: its fixed quadrature is off by up to 1e-3 at the small
# df a few plates give (k = 2, df = 4: 0.0014072 where the exact pooled t-test and SciPy give
# 0.0014053; CT-R1 F11), which made Tukey and Games-Howell disagree with plaque_stats.py.
# This agrees with scipy.stats.studentized_range.sf to 1e-11.
srange_upper <- function(q, k, df) {
  if (!is.finite(q) || !is.finite(df) || df <= 0 || k < 2) return(NA_real_)
  if (q <= 0) return(1)
  res <- tryCatch({
    inner <- function(w) vapply(w, function(wi) stats::integrate(function(z) {
      hi <- stats::pnorm(z)
      k * stats::dnorm(z) * (hi^(k - 1) - (hi - stats::pnorm(z - wi))^(k - 1))
    }, -8.5, 8.5 + wi, rel.tol = 1e-10, subdivisions = 300L, stop.on.error = FALSE)$value, 0)
    lo <- sqrt(stats::qchisq(1e-13, df) / df)
    up <- sqrt(stats::qchisq(1e-13, df, lower.tail = FALSE) / df)
    stats::integrate(function(s) 2 * df * s * stats::dchisq(df * s^2, df) * inner(q * s), lo, up,
                     rel.tol = 1e-9, subdivisions = 300L, stop.on.error = FALSE)$value
  }, error = function(e) NA_real_)
  if (!is.finite(res)) res <- stats::ptukey(q, k, df, lower.tail = FALSE)   # never leave a gap
  min(1, max(0, res))
}
pair_key <- function(a, b) paste(a, b, sep = "\r")
all_pairs <- function(labels) {
  if (length(labels) < 2) return(data.frame(group1 = character(0), group2 = character(0), stringsAsFactors = FALSE))
  cb <- utils::combn(labels, 2)
  data.frame(group1 = cb[1, ], group2 = cb[2, ], stringsAsFactors = FALSE)
}
# Tukey HSD (Tukey-Kramer) among the groups with >= 2 values; the others get NA (n/a)
tukey_p <- function(groups) {
  out <- list(); ok <- names(groups)[lengths(groups) >= 2]
  if (length(ok) >= 2) {
    gv <- groups[ok]; n <- lengths(gv); m <- vapply(gv, mean, 0)
    dfw <- sum(n) - length(ok)
    mse <- sum(unlist(Map(function(v, mm) (v - mm)^2, gv, m))) / dfw
    pr <- all_pairs(ok)
    for (i in seq_len(nrow(pr))) {
      a <- pr$group1[i]; b <- pr$group2[i]
      q <- abs(m[[a]] - m[[b]]) / sqrt(mse / 2 * (1 / n[[a]] + 1 / n[[b]]))
      out[[pair_key(a, b)]] <- if (is.nan(q)) NA_real_ else if (is.infinite(q)) 0 else srange_upper(q, length(ok), dfw)
    }
  }
  out
}
# Games-Howell: studentized range with Welch-Satterthwaite df, exactly as games_howell()
games_howell_p <- function(groups) {
  out <- list(); ok <- names(groups)[lengths(groups) >= 2]; k <- length(ok)
  pr <- all_pairs(ok)
  for (i in seq_len(nrow(pr))) {
    a <- pr$group1[i]; b <- pr$group2[i]; x <- groups[[a]]; y <- groups[[b]]
    va <- stats::var(x) / length(x); vb <- stats::var(y) / length(y); se <- sqrt(va + vb)
    if (se == 0) { out[[pair_key(a, b)]] <- NA_real_; next }
    tt <- abs(mean(x) - mean(y)) / se
    df <- (va + vb)^2 / (va^2 / (length(x) - 1) + vb^2 / (length(y) - 1))
    out[[pair_key(a, b)]] <- srange_upper(tt * sqrt(2), k, df)
  }
  out
}
# Dunn's test after Kruskal-Wallis, tie-corrected, Holm-adjusted, as dunn()
dunn_holm_p <- function(groups) {
  labels <- names(groups)[lengths(groups) > 0]; out <- list()
  if (length(labels) < 2) return(out)
  gv <- groups[labels]; allv <- unlist(gv, use.names = FALSE); N <- length(allv)
  r <- rank(allv); n <- lengths(gv); idx <- rep(seq_along(gv), n)
  rbar <- vapply(seq_along(gv), function(i) mean(r[idx == i]), 0)
  ties <- as.numeric(table(allv))
  sigma2 <- N * (N + 1) / 12 - sum(ties^3 - ties) / (12 * (N - 1))
  pr <- all_pairs(labels); raw <- numeric(nrow(pr))
  for (i in seq_len(nrow(pr))) {
    a <- match(pr$group1[i], labels); b <- match(pr$group2[i], labels)
    se <- sqrt(sigma2 * (1 / n[a] + 1 / n[b]))
    z <- if (is.finite(se) && se > 0) (rbar[a] - rbar[b]) / se else 0
    raw[i] <- 2 * stats::pnorm(-abs(z))
  }
  adj <- raw; okp <- !is.na(raw); adj[okp] <- stats::p.adjust(raw[okp], "holm")
  for (i in seq_len(nrow(pr))) out[[pair_key(pr$group1[i], pr$group2[i])]] <- adj[i]
  out
}
# CT-R1 F11: Mann-Whitney with scipy's method="auto" rule -- the exact distribution when the
# smaller sample has <= 8 values and there are no ties, otherwise the normal approximation
# with continuity (and tie) correction. R's own default is exact below 50, which gave 0.00133
# where the Python engine gives 0.00221 for 12 vs 14 plates.
mann_whitney <- function(a, b) {
  if (length(a) < 1 || length(b) < 1) return(list(p = NA_real_, method = NA_character_))
  exact <- min(length(a), length(b)) <= 8 && !anyDuplicated(c(a, b))
  p <- tryCatch(suppressWarnings(stats::wilcox.test(a, b, exact = exact, correct = TRUE)$p.value),
                error = function(e) NA_real_)
  list(p = if (is.nan(p)) NA_real_ else p,
       method = if (exact) "exact" else "normal approximation with continuity correction")
}
cohens_d <- function(a, b) {
  na <- length(a); nb <- length(b)
  if (na < 2 || nb < 2) return(NA_real_)
  sp <- sqrt(((na - 1) * stats::var(a) + (nb - 1) * stats::var(b)) / (na + nb - 2))
  if (is.finite(sp) && sp > 0) (mean(a) - mean(b)) / sp else NA_real_
}
# The SD-ratio rule of the "Variances" choice: Levene cannot see unequal variances with ~3
# plates per group, so a largest/smallest group SD ratio above 3 is flagged whatever Levene says.
SD_RATIO_LIMIT <- 3
sd_ratio_warning <- function(ratio, lev_p) {
  sprintf(paste0("The largest group SD is %s times the smallest%s. Levene's test cannot reliably ",
                 "detect unequal variances with this few values per group, so consider Variances = ",
                 "'unequal' (Welch's ANOVA + Games-Howell)."),
          if (is.finite(ratio)) formatC(ratio, format = "f", digits = 1) else "many",
          if (is.na(lev_p)) "" else sprintf(" although Levene p = %s", fmt_p(lev_p)))
}

# d: group (factor, levels = plotting order), replicate (NA = none), value.
# unit: auto | replicate | plaque; parametric: auto | parametric | nonparametric;
# equal_var: auto (Welch ANOVA + Games-Howell when Levene p < 0.05) | yes (classic ANOVA +
# Tukey always) | no (Welch + Games-Howell always). Returns the unit that was ACTUALLY tested.
plaque_run_stats <- function(d, unit = "auto", parametric = "auto", equal_var = "auto") {
  lev <- levels(d$group); k <- length(lev)
  rm <- if (all(is.na(d$replicate))) NULL else
    as.data.frame(d %>% filter(!is.na(replicate)) %>% group_by(group, replicate) %>%
                    summarise(value = mean(value), n_plaques = n(), .groups = "drop"))
  plates <- vapply(lev, function(g) if (is.null(rm)) 0L else sum(rm$group == g), 0L)
  have_rep <- !is.null(rm) && min(plates) >= 2
  requested <- unit
  if (unit == "auto") unit <- if (have_rep) "replicate" else "plaque"
  warns <- character(0)
  # CT-R1 F2: the unit REPORTED is the unit TESTED. plaque_stats.py keeps the label
  # "replicate" when --unit replicate is forced on a file without a plate column although it
  # then tests plaques; here that case is called what it is.
  if (unit == "replicate" && is.null(rm)) unit <- "plaque"
  src <- if (unit == "replicate") rm else d
  groups <- setNames(lapply(lev, function(g) src$value[src$group == g]), lev)
  ns <- lengths(groups); min_n <- if (length(ns)) min(ns) else 0L

  normal <- vapply(groups, function(v) if (length(v) >= 3 && length(v) <= 5000)
    tryCatch(stats::shapiro.test(v)$p.value, error = function(e) NA_real_) else NA_real_, 0)
  lev_p <- levene_p(groups)
  all_normal <- all(is.na(normal) | normal > 0.05)
  # few replicates -> parametric on the plate means (Shapiro is uninformative and rank tests
  # cannot reach p < 0.05 at 3 vs 3): SuperPlots, Lord 2020; Kenny & Schoen 2021
  use_param <- if (parametric == "auto") { if (min_n < 8) TRUE else all_normal && (is.na(lev_p) || lev_p > 0.05) }
               else parametric == "parametric"

  if (unit == "plaque") {
    one <- lev[plates < 2]
    why <- if (requested == "plaque") "The statistical unit was set to 'per plaque'."
      else if (is.null(rm)) "No plate (replicate) column is in use, so the test ran on individual plaques."
      else sprintf("The test ran on individual plaques because %s %s fewer than 2 plates (the automatic unit needs at least 2 plates for every sample; choose 'per plate' to test the plate means, where %s n/a).",
                   paste(one, collapse = ", "), if (length(one) > 1) "have" else "has",
                   if (length(one) > 1) "those samples get" else "that sample gets")
    warns <- c(warns, paste(why, "Plaques from the same plate are not independent (pseudoreplication),",
                            "so these p-values are too small. Add a plate (replicate) column for a valid test."))
  } else if (any(plates < 2)) {
    one <- lev[plates < 2]
    warns <- c(warns, sprintf("%s %s fewer than 2 plates, so %s cannot be compared on plate means: %s n/a.",
                              paste(one, collapse = ", "), if (length(one) > 1) "have" else "has",
                              if (length(one) > 1) "they" else "it",
                              if (length(one) > 1) "their comparisons are" else "its comparisons are"))
  }
  if (!use_param && min_n < 4)
    warns <- c(warns, paste("Non-parametric test with fewer than 4 values per group: significance can be",
                            "unreachable (Mann-Whitney cannot go below p = 0.10 at 3 vs 3) or only approximate",
                            "(Kruskal-Wallis). With few plates prefer a parametric test on the plate means."))

  out <- list(unit = unit, unit_requested = requested, have_rep = have_rep, rm = rm, src = src,
              groups = groups, n_per_group = ns, min_n = as.integer(min_n), plates = plates,
              levene_p = lev_p, normality_p = normal, parametric_used = use_param,
              equal_var = equal_var, posthoc = NA_character_, method_note = NULL, cohens_d = NA_real_,
              sd_ratio = NA_real_)
  pw <- all_pairs(lev); padj <- list()
  if (k == 2) {
    a <- groups[[1]]; b <- groups[[2]]
    if (use_param) {
      out$test <- "Welch t-test"
      out$p <- if (length(a) >= 2 && length(b) >= 2)
        tryCatch(stats::t.test(a, b)$p.value, error = function(e) NA_real_) else NA_real_
    } else {
      mw <- mann_whitney(a, b)
      out$test <- "Mann–Whitney U"; out$p <- mw$p
      if (!is.na(mw$method))
        out$method_note <- paste0("Mann-Whitney p: ", mw$method, " (exact when the smaller group has 8 or ",
                                  "fewer values and there are no ties, otherwise the normal approximation ",
                                  "with continuity correction; the rule SciPy uses).")
    }
    if (is.nan(out$p)) out$p <- NA_real_
    out$cohens_d <- cohens_d(a, b)
    padj[[pair_key(lev[1], lev[2])]] <- out$p
  } else if (k > 2) {
    if (use_param) {
      sds <- vapply(groups[ns >= 2], stats::sd, 0)
      ratio <- if (length(sds) >= 2) { if (min(sds) > 0) max(sds) / min(sds) else if (max(sds) > 0) Inf else NA_real_ } else NA_real_
      out$sd_ratio <- ratio
      # CT-R1 F1: classic ANOVA + Tukey assume equal variances; when Levene rejects that (or
      # the user says the variances differ) use Welch's ANOVA + Games-Howell, as the Python
      # engine does. "yes" keeps the classic pair whatever Levene says.
      unequal <- if (equal_var == "no") TRUE else if (equal_var == "yes") FALSE
                 else !is.na(lev_p) && lev_p < 0.05 && min_n >= 2
      if (unequal) {
        out$test <- "Welch ANOVA"; out$p <- welch_anova_p(groups); out$posthoc <- "Games-Howell"
        padj <- games_howell_p(groups)
        warns <- c(warns, if (equal_var == "no")
          "Variances were set to 'unequal': Welch's ANOVA and Games-Howell (no equal-variance assumption) were used."
          else sprintf("Levene p = %.3f: group variances differ, so Welch's ANOVA and Games-Howell (no equal-variance assumption) were used.", lev_p))
      } else {
        out$test <- "one-way ANOVA"; out$p <- anova_p(groups); out$posthoc <- "Tukey HSD"
        padj <- tukey_p(groups)
        if (equal_var == "yes" && !is.na(lev_p) && lev_p < 0.05)
          warns <- c(warns, sprintf("Levene p = %.3f suggests the group variances differ, but Variances was set to 'equal', so the classic ANOVA and Tukey HSD were used.", lev_p))
        if (equal_var == "auto" && !is.na(ratio) && ratio > SD_RATIO_LIMIT)
          warns <- c(warns, sd_ratio_warning(ratio, lev_p))
      }
    } else {
      out$test <- "Kruskal–Wallis"; out$posthoc <- "Dunn (Holm-adjusted)"
      gv <- groups[ns > 0]
      out$p <- tryCatch(stats::kruskal.test(gv)$p.value, error = function(e) NA_real_)
      padj <- dunn_holm_p(groups)
    }
    if (is.nan(out$p)) out$p <- NA_real_
  } else {
    out$test <- "n/a (need ≥2 groups)"; out$p <- NA_real_
    warns <- c(warns, sprintf("Only one sample (%s) has data, so there is nothing to compare.",
                              paste(lev, collapse = ", ")))
  }
  gm <- vapply(groups, function(v) if (length(v)) mean(v) else NA_real_, 0)
  pw$mean_a <- unname(gm[pw$group1]); pw$mean_b <- unname(gm[pw$group2])
  pw$mean_diff <- pw$mean_a - pw$mean_b
  pw$n_a <- unname(ns[pw$group1]); pw$n_b <- unname(ns[pw$group2])
  pw$p_adj <- vapply(seq_len(nrow(pw)), function(i) {
    v <- padj[[pair_key(pw$group1[i], pw$group2[i])]]; if (is.null(v) || is.nan(v)) NA_real_ else v }, 0)
  pw$signif <- p_stars(pw$p_adj)
  out$pairwise <- pw
  # descriptives of the values the test used (plate means when the unit is the plate)
  out$unit_stats <- data.frame(
    group = lev, n = as.integer(ns),
    mean = unname(gm),
    sd = unname(vapply(groups, function(v) if (length(v) > 1) stats::sd(v) else NA_real_, 0)),
    stringsAsFactors = FALSE)
  out$unit_stats$sem <- out$unit_stats$sd / sqrt(out$unit_stats$n)
  out$warnings <- warns
  out
}

# the omnibus box of the Statistics tab
omnibus_text <- function(st) {
  unit_words <- if (st$unit == "replicate") "replicate = plate means" else "plaque = individual plaques"
  msg <- sprintf("%s: %s  (unit: %s, parametric = %s, min n = %d/group, Levene %s)",
                 st$test, p_eq(st$p), unit_words, isTRUE(st$parametric_used), st$min_n, p_eq(st$levene_p))
  if (!is.na(st$posthoc)) msg <- paste0(msg, "\nPairwise: ", st$posthoc)
  if (!is.null(st$method_note)) msg <- paste0(msg, "\n", st$method_note)
  if (length(st$warnings)) msg <- paste0(msg, "\n\nWARNINGS:\n- ", paste(st$warnings, collapse = "\n- "))
  msg
}
# CT-R1 F5: the paste-ready sentence, worded as write_report() in plaque_stats.py words it:
# with the plate as unit it quotes the plate means +/- SEM that were tested (n = plates,
# plaques in brackets), never per-plaque mean +/- SD beside a plate-level p.
# summ: one row per group with group, n (plaques), n_plates, mean, sd (per plaque).
stats_sentence <- function(metric, summ, st) {
  k <- nrow(summ)
  f2 <- function(x) if (is.na(x)) "n/a" else sprintf("%.2f", x)     # one value has no SD / SEM
  if (k < 2)
    return(sprintf("%s: only one sample (%s) has data, so nothing was compared.", metric,
                   paste(summ$group, collapse = ", ")))
  if (k == 2) {
    us <- st$unit_stats; d_txt <- ""
    if (is.finite(st$cohens_d)) {
      d_txt <- sprintf(", Cohen's d = %.2f", st$cohens_d)
      if (st$min_n < 5)
        d_txt <- paste0(d_txt, sprintf(" (a %d-vs-%d %s estimate; treat as rough)", us$n[1], us$n[2],
                                       if (st$unit == "replicate") "plate" else "plaque"))
    }
    if (st$unit == "replicate")
      return(sprintf("%s in %s was %s ± %s (mean ± SEM of %d plate means; %d plaques) vs %s %s ± %s (%d plates; %d plaques); %s on plate means, %s%s.",
                     metric, summ$group[1], f2(us$mean[1]), f2(us$sem[1]), us$n[1], summ$n[1],
                     summ$group[2], f2(us$mean[2]), f2(us$sem[2]), us$n[2], summ$n[2],
                     st$test, p_eq(st$p), d_txt))
    nfmt <- function(i) paste0(sprintf("n=%d", summ$n[i]),
                               if (st$have_rep) sprintf(", %d plates", summ$n_plates[i]) else " plaques")
    return(sprintf("%s in %s was %s ± %s (%s) vs %s %s ± %s (%s); %s, %s%s.",
                   metric, summ$group[1], f2(summ$mean[1]), f2(summ$sd[1]), nfmt(1),
                   summ$group[2], f2(summ$mean[2]), f2(summ$sd[2]), nfmt(2), st$test, p_eq(st$p), d_txt))
  }
  # three or more samples: each sample's numbers for the unit that was tested, then the test
  us <- st$unit_stats
  post <- if (is.na(st$posthoc)) "" else paste0("; pairwise comparisons: ", st$posthoc)
  if (st$unit == "replicate") {
    items <- sprintf("%s %s ± %s (%d plates; %d plaques)", summ$group, vapply(us$mean, f2, ""), vapply(us$sem, f2, ""),
                     us$n, summ$n)
    return(sprintf("%s (mean ± SEM of plate means; n = plates, plaques in brackets): %s. %s on plate means across %d groups, %s%s.",
                   metric, paste(items, collapse = "; "), st$test, k, p_eq(st$p), post))
  }
  items <- sprintf("%s %s ± %s (n=%d plaques)", summ$group, vapply(summ$mean, f2, ""), vapply(summ$sd, f2, ""), summ$n)
  sprintf("%s (mean ± SD per plaque): %s. %s across %d groups, %s%s. NOTE: the unit tested was the plaque (pseudoreplication; plaques from one plate are not independent), so add plate replicates.",
          metric, paste(items, collapse = "; "), st$test, k, p_eq(st$p), post)
}

# CT-R1 F7: which comparisons get a bracket. auto = the significant ones; with more than 5
# samples only the significant ones against the FIRST sample (33 brackets on 12 violins took
# 80 % of the panel). "all" draws every tested pair.
BRACKET_AUTO_MAX_GROUPS <- 5
pairs_to_draw <- function(pw, lev, mode = "auto", posthoc = NA_character_) {
  empty <- list(pairs = data.frame(i = integer(0), j = integer(0), label = character(0),
                                   stringsAsFactors = FALSE), note = NULL, caption = NULL)
  k <- length(lev)
  if (is.null(pw) || !nrow(pw) || k < 2) return(empty)
  pw <- pw[!is.na(pw$p_adj), , drop = FALSE]
  if (!nrow(pw)) return(empty)
  note <- NULL; caption <- NULL
  if (k == 2) {
    lab <- if (pw$p_adj < 1e-3) "p < 0.001" else paste0("p = ", fmt_p(pw$p_adj))
  } else {
    if (!identical(mode, "all")) {
      pw <- pw[pw$p_adj < 0.05, , drop = FALSE]
      if (k > BRACKET_AUTO_MAX_GROUPS) {
        pw <- pw[pw$group1 == lev[1] | pw$group2 == lev[1], , drop = FALSE]
        caption <- sprintf("Brackets: significant comparisons against %s only%s.", lev[1],
                           if (is.na(posthoc)) "" else paste0(" (", posthoc, ")"))
        note <- sprintf("More than %d samples: the brackets show only the significant comparisons against the first sample (%s). Choose 'all pairs' under Comparisons shown to draw every comparison; the Statistics tab lists them all.",
                        BRACKET_AUTO_MAX_GROUPS, lev[1])
      }
      if (!nrow(pw)) {
        empty$note <- c(note, "No comparison shown here is significant (p < 0.05), so no bracket is drawn.")
        empty$caption <- caption
        return(empty)
      }
    }
    lab <- pw$signif
  }
  list(pairs = data.frame(i = match(pw$group1, lev), j = match(pw$group2, lev), label = lab,
                          stringsAsFactors = FALSE), note = note, caption = caption)
}
# Bracket heights: every bracket sits ABOVE `top`, the tallest drawn element (violin top,
# points, error bars), packed into as few levels as possible; `scale` grows the spacing with
# the font. Works in the plotting space (log10 on a log axis; the caller transforms back).
bracket_layout <- function(pairs, top, bottom, scale = 1) {
  span <- top - bottom
  if (!is.finite(span) || span <= 0) span <- max(abs(top), 1) * 0.1
  step <- span * 0.085 * scale
  pairs$x1 <- pmin(pairs$i, pairs$j); pairs$x2 <- pmax(pairs$i, pairs$j)
  pairs$level <- NA_integer_
  for (r in order(pairs$x2 - pairs$x1, pairs$x1)) {
    L <- 0L
    repeat {
      on <- which(pairs$level == L)
      if (!any(pairs$x1[r] <= pairs$x2[on] & pairs$x1[on] <= pairs$x2[r])) break
      L <- L + 1L
    }
    pairs$level[r] <- L
  }
  pairs$y <- top + step * (0.9 + pairs$level)
  pairs$ytip <- pairs$y - step * 0.22
  pairs$ylab <- pairs$y + step * 0.06
  list(pairs = pairs, step = step, top = max(pairs$y) + step * 0.75)
}

# ---------------------------------------------------------------------------------------------
# Legend key (the owner's rule: every figure ships one). The R twin of plaque_stats/legend_key.py:
# style_map() is THE colour mapping -- the violin is drawn from it and the key is built from it.
# key_entries() -> key_plot() (stand-alone key AND the key placed on the figure: same ggplot)
# and text_starter() (the paste-ready sentence). Same wording rules as the Python helper.
# ---------------------------------------------------------------------------------------------
KEY_COLOUR_NAMES <- c(
  "black" = "#000000", "dark grey" = "#595959", "grey" = "#808080", "light grey" = "#BFBFBF",
  "white" = "#FFFFFF", "red" = "#E41A1C", "dark red" = "#8B0000", "orange" = "#FF7F00",
  "yellow" = "#FFD700", "green" = "#4DAF4A", "dark green" = "#006400", "teal" = "#008080",
  "cyan" = "#00BFFF", "blue" = "#377EB8", "dark blue" = "#00008B", "navy" = "#000080",
  "purple" = "#984EA3", "magenta" = "#FF00FF", "pink" = "#F781BF", "brown" = "#A65628",
  "olive" = "#808000", "gold" = "#DAA520", "sky blue" = "#56B4E9", "vermillion" = "#D55E00",
  "bluish green" = "#009E73", "reddish purple" = "#CC79A7", "yellow-green" = "#9ACD32")

colour_name <- function(hex) {
  lab <- hex_to_lab(hex); ref <- hex_to_lab(KEY_COLOUR_NAMES)
  names(KEY_COLOUR_NAMES)[which.min(colSums((t(ref) - as.numeric(lab[1, ]))^2))]
}

# the plate colours and marker shapes: REP_PALETTE under grey violins (the plate colour is the
# only hue on the figure, as it always was); greys that stay clear of every sample colour when
# the violins are coloured by sample (CT-R1 F18). Past the end of the palette the SHAPE changes,
# so no two plates share a colour + shape pair until palette x 5 shapes are used up.
plate_style <- function(reps, neutral, sample_cols = character(0)) {
  pal <- REP_PALETTE
  if (!neutral) {
    far <- function(p) p[vapply(p, function(x) colour_distance(x, sample_cols) > 18, TRUE)]
    pal <- far(PLATE_GREYS)
    if (length(pal) < 2) pal <- far(REP_PALETTE)
    if (length(pal) < 2) pal <- PLATE_GREYS
  }
  idx <- seq_along(reps) - 1L
  sh <- (idx %/% length(pal)) %% length(PLATE_SHAPES) + 1L
  list(col = setNames(pal[idx %% length(pal) + 1L], reps),
       shape = setNames(PLATE_SHAPES[sh], reps), pshape = setNames(POINT_SHAPES[sh], reps))
}

# the ONE mapping of the violin: sample -> colour, plate -> colour + marker shape, grey violins?
# Sample colours come from the registry BY NAME (a name the registry lacks takes the first
# colour of `pool` no other name uses), so a sample keeps its colour across files and apps.
style_map <- function(d, registry, vfill, chose_theme, superplot, pool = OKABE_ITO, show_points = TRUE) {
  levs <- levels(d$group)
  gcol <- registry_colours(registry, levs, pool)
  changed <- attr(gcol, "changed"); attr(gcol, "changed") <- NULL
  reps <- if (superplot) sort(unique(d$replicate[!is.na(d$replicate)])) else character(0)
  group_fill <- identical(vfill, "group") || (chose_theme && identical(vfill, "auto"))
  neutral <- identical(vfill, "neutral") || (!group_fill && superplot)
  ps <- plate_style(reps, neutral, unname(gcol))
  list(gcol = gcol, rcol = ps$col, rshape = ps$shape, pshape = ps$pshape, neutral = neutral,
       superplot = superplot,
       # CT-R1 F8: without plates the plaque points carry the SAMPLE colour and are keyed
       pts_by_group = !superplot && isTRUE(show_points), recoloured = changed)
}

# one row per keyed sample/plate, styled as drawn: coloured violins (alpha .25, no outline),
# with the sample's points on top when the points carry the sample colour; plate means are
# filled markers with the dark #12211d outline
key_entries <- function(sm) {
  rows <- list()
  row <- function(label, section, kind, colour, edge = NA_character_, alpha = 1, shape = NA_integer_,
                  extra = FALSE)
    data.frame(label = label, section = section, kind = kind, colour = to_hex(colour), edge = edge,
               alpha = alpha, shape = shape, extra = extra, stringsAsFactors = FALSE)
  pts <- isTRUE(sm$pts_by_group)
  if (!sm$neutral)
    for (g in names(sm$gcol))
      rows[[length(rows) + 1]] <- row(g, "sample", "patch", sm$gcol[[g]], alpha = 0.25, extra = pts)
  else if (pts)
    for (g in names(sm$gcol))
      rows[[length(rows) + 1]] <- row(g, "sample", "point", sm$gcol[[g]], alpha = 0.45, shape = 19L)
  if (sm$superplot)
    for (r in names(sm$rcol))
      rows[[length(rows) + 1]] <- row(r, "plate", "marker", sm$rcol[[r]], edge = "#12211D",
                                      shape = if (is.null(sm$rshape)) 21L else sm$rshape[[r]])
  if (!length(rows)) return(data.frame(label = character(0), section = character(0),
                                       kind = character(0), colour = character(0),
                                       edge = character(0), alpha = numeric(0),
                                       shape = integer(0), extra = logical(0), stringsAsFactors = FALSE))
  do.call(rbind, rows)
}

text_starter <- function(e) {
  if (!nrow(e)) return("")
  words <- vapply(e$colour, colour_name, "")
  for (w in unique(words)) {                 # same word, different colours -> light/dark
    idx <- which(words == w); hx <- unique(e$colour[idx])
    if (length(hx) < 2) next
    L <- hex_to_lab(hx)[, 1]; ranked <- hx[order(L)]
    shade <- setNames(ifelse(seq_along(ranked) == 1, paste("dark", w),
                      ifelse(seq_along(ranked) == length(ranked), paste("light", w),
                             paste("medium", w))), ranked)
    # CT-R1 F18: "light"/"dark" only when the lightness really differs; two colours of the
    # same word and much the same lightness are told apart by their hex code instead
    if (min(diff(sort(L))) < 5) shade <- setNames(paste0(w, " ", ranked), ranked)
    words[idx] <- shade[e$colour[idx]]
  }
  shape_word <- function(s) { w <- SHAPE_WORDS[as.character(s)]; if (is.na(w)) "markers" else unname(w) }
  desc <- vapply(seq_len(nrow(e)), function(i) {
    if (e$kind[i] == "patch")
      return(paste0(words[i], ", filled violin", if (isTRUE(e$extra[i])) " and filled circles" else ""))
    out <- paste0(words[i], ", filled ", shape_word(e$shape[i]))
    if (!is.na(e$edge[i]) && e$edge[i] != e$colour[i] && !grepl(colour_name(e$edge[i]), words[i], fixed = TRUE))
      out <- paste0(out, " with ", colour_name(e$edge[i]), " outline")
    out
  }, "")
  paste0(paste0(e$label, " (", desc, ")", collapse = "; "), ".")
}

# CT-R1 F17: where every key row goes. One column up to KEY_ROWS_PER_COL rows, then balanced
# columns (each as wide as its own longest name); the row pitch grows with the font so rows
# never print on top of each other. Used by the stand-alone key and the placed key alike.
KEY_ROWS_PER_COL <- 12
key_geometry <- function(e, base_size = 14) {
  hdr <- function(s) data.frame(label = s, section = s, kind = "header", colour = NA, edge = NA,
                                alpha = NA, shape = NA, extra = FALSE, stringsAsFactors = FALSE)
  if (is.null(e$extra)) e$extra <- rep(FALSE, nrow(e))
  rows <- do.call(rbind, lapply(unique(e$section), function(s) rbind(hdr(s), e[e$section == s, ])))
  n <- nrow(rows); ncols <- ceiling(n / KEY_ROWS_PER_COL); per <- ceiling(n / ncols)
  col <- integer(n); pos <- integer(n); cc <- 1L; rr <- 0L
  for (i in seq_len(n)) {
    # a section header never sits alone at the foot of a column
    if (rr >= per || (rows$kind[i] == "header" && rr == per - 1L && rr > 0L)) { cc <- cc + 1L; rr <- 0L }
    rr <- rr + 1L; col[i] <- cc; pos[i] <- rr
  }
  rows$col <- col; rows$pos <- pos
  nrows <- max(pos)
  colw <- vapply(seq_len(max(col)), function(j) 0.6 + 0.105 * max(nchar(rows$label[col == j])) * base_size / 14, 0)
  pitch <- 0.24 * max(1, base_size / 14)
  rows$x0 <- c(0, cumsum(colw))[col]; rows$y <- nrows - pos + 1
  list(rows = rows, colw = colw, nrows = nrows, pitch = pitch,
       width = sum(colw), height = 0.25 + pitch * nrows)
}
key_size <- function(e, base_size = 14) {
  g <- key_geometry(e, base_size)
  c(width = g$width, height = g$height)
}
# the key as a ggplot: section headers in bold, the figure's font (theme_classic base_size and
# family) -- used stand-alone and placed beside the figure alike
key_plot <- function(e, base_size = 14, family = "") {
  geo <- key_geometry(e, base_size); rows <- geo$rows
  tsize <- base_size * 0.8 / ggplot2::.pt
  hdr <- rows[rows$kind == "header", ]; pat <- rows[rows$kind == "patch", ]
  mk <- rows[rows$kind == "marker", ]; ent <- rows[rows$kind != "header", ]
  pt <- rows[rows$kind == "point" | (rows$kind == "patch" & rows$extra), ]
  p <- ggplot() +
    geom_text(data = hdr, aes(x = x0 + 0.05, y = y, label = label), hjust = 0, fontface = "bold",
              size = tsize, family = family) +
    geom_text(data = ent, aes(x = x0 + 0.45, y = y, label = label), hjust = 0, size = tsize,
              family = family)
  if (nrow(pat)) p <- p + geom_tile(data = pat, aes(x = x0 + 0.22, y = y), width = 0.3, height = 0.55,
                                    fill = pat$colour, alpha = pat$alpha, colour = NA)
  if (nrow(pt)) p <- p + geom_point(data = pt, aes(x = x0 + 0.22, y = y), shape = 19, size = 1.5,
                                    alpha = 0.45, colour = pt$colour)
  if (nrow(mk)) p <- p + geom_point(data = mk, aes(x = x0 + 0.22, y = y), shape = mk$shape, size = 4.2,
                                    stroke = 0.9, fill = mk$colour, colour = mk$edge)
  # x is in inches of the saved key (key_size), so the names never clip
  p + scale_x_continuous(limits = c(0, geo$width), expand = c(0, 0)) +
    scale_y_continuous(limits = c(0.4, geo$nrows + 0.6)) +
    theme_void(base_size = base_size, base_family = family) +
    theme(plot.background = element_rect(fill = "white", colour = NA))
}

# CT-R1 F4: PDFs. cairo_pdf keeps text as text and draws any installed font (the pdf() device
# only knows the PostScript base fonts, so Arial, Times New Roman and every custom font made
# the download fail). Without Cairo the plot is drawn again in the nearest base family and
# the returned note says so. `plot_for(family)` returns the ggplot in a given family.
pdf_base_family <- function(family) {
  f <- tolower(trimws(family))
  if (f %in% c("", "sans", "arial", "helvetica", "helvetica neue")) "Helvetica"
  else if (f %in% c("serif", "times", "times new roman")) "Times"
  else if (f %in% c("mono", "courier", "courier new")) "Courier"
  else NA_character_
}
# capabilities("cairo") can say TRUE where the Cairo library cannot be loaded (a Mac without
# XQuartz: "failed to load cairo DLL"); a failed cairo_pdf() then leaves ggsave() to draw on R's
# default device, a stray Rplots.pdf. So Cairo is tried ONCE on an empty file and remembered.
cairo_pdf_usable <- local({
  probed <- NULL
  function() {
    if (isTRUE(getOption("plaque_stats.no_cairo_pdf", FALSE))) return(FALSE)
    if (is.null(probed)) probed <<- isTRUE(capabilities("cairo")) && tryCatch({
      f <- tempfile(fileext = ".pdf"); before <- grDevices::dev.list()
      withCallingHandlers(grDevices::cairo_pdf(f), warning = function(w) stop(conditionMessage(w)))
      while (length(grDevices::dev.list()) > length(before)) grDevices::dev.off()
      unlink(f); TRUE }, error = function(e) FALSE)
    probed
  }
})
save_pdf <- function(file, plot_for, family, width, height) {
  filled <- function() file.exists(file) && isTRUE(file.size(file) > 0)
  if (cairo_pdf_usable()) {
    ok <- tryCatch({ suppressWarnings(ggsave(file, plot_for(family), width = width, height = height,
                                             device = grDevices::cairo_pdf)); TRUE },
                   error = function(e) FALSE)
    if (ok && filled()) return(NULL)
  }
  base <- pdf_base_family(family); exact <- !is.na(base)
  if (!exact) base <- "Helvetica"
  ggsave(file, plot_for(base), width = width, height = height, device = "pdf")
  shown <- if (nzchar(family)) family else "the default sans"
  if (exact && tolower(family) %in% c("", "sans", "serif", "mono", "helvetica", "times", "courier")) NULL
  else sprintf("PDF: font substituted. This R cannot embed %s in a PDF (no Cairo PDF support), so the PDF was drawn with the built-in %s font. The PNG and SVG use %s.",
               shown, base, shown)
}
# the stand-alone key in every format + the text starter. One format that fails does not lose
# the others; attr "notes" says what happened.
write_key_files <- function(e, base, dpi = 300, base_size = 14, family = "") {
  sz <- key_size(e, base_size); kp <- key_plot(e, base_size, family)
  out <- c(png = paste0(base, "_legend_key.png"), svg = paste0(base, "_legend_key.svg"),
           pdf = paste0(base, "_legend_key.pdf"), txt = paste0(base, "_legend_text.txt"))
  notes <- character(0)
  attempt <- function(what, expr) tryCatch(expr, error = function(err) {
    notes <<- c(notes, sprintf("The %s key could not be written (%s).", what, conditionMessage(err))); NULL })
  attempt("PNG", ggsave(out[["png"]], kp, width = sz[["width"]], height = sz[["height"]], dpi = dpi))
  attempt("SVG", ggsave(out[["svg"]], kp, width = sz[["width"]], height = sz[["height"]], device = svglite::svglite))
  pdf_note <- attempt("PDF", save_pdf(out[["pdf"]], function(fam) key_plot(e, base_size, fam), family,
                                      sz[["width"]], sz[["height"]]))
  notes <- c(notes, pdf_note)
  writeLines(text_starter(e), out[["txt"]])
  out <- unname(out[file.exists(out)])
  attr(out, "notes") <- notes
  out
}

format_help <- function() {
  HTML(paste0(
    "<h4>Input data format (one row per plaque)</h4>",
    "<p><b>WIDE</b> (matches the app export — add <code>group</code> + <code>replicate</code>):</p>",
    "<pre>group,replicate,diameter_mm,area_mm2,turbidity\nT4,plate1,2.34,4.30,0.12\nT4,plate1,2.51,4.95,0.08\nT7,plate1,1.80,2.54,0.62</pre>",
    "<p><b>LONG</b> (one file, many metrics):</p>",
    "<pre>group,replicate,metric,value\nT4,plate1,diameter_mm,2.34\nT7,plate1,diameter_mm,1.80</pre>",
    "<ul><li><b>group</b> (required): the sample/condition/phage compared.</li>",
    "<li><b>replicate</b> (recommended): the plate / experimental unit &mdash; makes stats per-plate ",
    "(avoids pseudoreplication).</li>",
    "<li><b>value</b> / numeric columns: the measurement(s).</li></ul>",
    "<p>Comma-, semicolon- and tab-separated files are read; the separator is detected. Numbers ",
    "use a decimal point (2.34); decimal commas (2,34) are read in semicolon- or tab-separated files. ",
    "Column names are matched without regard to case.</p>"))
}

# CT-R1 F22: a paste-ready text is a multi-line box with a Copy button
copy_box <- function(id, rows = 3) {
  tagList(
    tags$textarea(id = id, class = "shiny-text-output form-control", rows = rows, readonly = NA,
                  style = "width: 100%; font-family: monospace; font-size: 12px; resize: vertical;"),
    tags$button("Copy", type = "button", class = "btn btn-sm btn-default", style = "margin-top: 4px;",
                onclick = sprintf("var t = document.getElementById('%s'); navigator.clipboard.writeText(t.value || t.textContent);", id)))
}
scroll_box <- function(...) div(style = "overflow-x: auto; max-width: 100%;", ...)   # CT-R1 F22

ui <- fluidPage(
  titlePanel("Plaque Stats & Violins"),
  sidebarLayout(
    sidebarPanel(
      width = 3,
      fileInput("file", "Data file (CSV/TSV)", accept = c(".csv", ".tsv", ".txt")),
      actionButton("load_example", "Load example data", class = "btn-sm"),
      tags$hr(),
      uiOutput("col_pickers"),
      tags$hr(),
      selectInput("unit", "Statistical unit",
                  c("auto (plate if replicates)" = "auto", "per plate (replicate)" = "replicate",
                    "per plaque" = "plaque")),
      selectInput("param", "Test type",
                  c("auto (from normality)" = "auto", "parametric" = "parametric",
                    "non-parametric" = "nonparametric")),
      selectInput("equal_var", "Variances (3+ samples, parametric)",
                  c("auto (Welch ANOVA if Levene p < 0.05)" = "auto",
                    "equal (ANOVA + Tukey)" = "yes",
                    "unequal (Welch ANOVA + Games-Howell)" = "no")),
      checkboxInput("show_points", "Show plaque points", TRUE),
      selectInput("vfill", "Violin fill",
                  c("auto (grey when plates)" = "auto", "neutral grey" = "neutral",
                    "coloured by sample" = "group")),
      selectInput("center", "Centre marker", c("mean" = "mean", "median" = "median")),
      selectInput("error", "Error bar", c("auto" = "auto", "SD" = "sd", "SEM" = "sem",
                                          "95% CI" = "ci95", "IQR" = "iqr", "none" = "none")),
      checkboxInput("show_n", "Show n on top", TRUE),
      checkboxInput("frame", "Box the plot (frame)", FALSE),
      checkboxInput("show_sig", "Significance brackets", TRUE),
      selectInput("annotate", "Comparisons shown",
                  c("auto (significant; vs first sample when more than 5)" = "auto",
                    "all pairs" = "all")),
      checkboxInput("log_y", "Log y-axis", FALSE),
      tags$hr(),
      textInput("title", "Title", ""),
      textInput("ylab", "Y-axis label", ""),
      textInput("xlab", "X-axis label", ""),
      textInput("order", "Group order (comma-sep, optional)", ""),
      selectInput("palette_name", "Colour theme", THEME_CHOICES),
      textInput("palette", "Custom palette (comma-sep hex)", ""),
      tags$small(textOutput("palette_status")),
      selectInput("font_family", "Font",
                  c("Default sans" = "sans", "Arial", "Helvetica", "Times New Roman",
                    "Serif" = "serif", "Custom…" = "custom")),
      conditionalPanel("input.font_family == 'custom'",
                       textInput("font_family_custom", "Custom font name", "")),
      numericInput("base_size", "Base font size (pt)", 14, BASE_SIZE_RANGE[1], BASE_SIZE_RANGE[2], 1),
      textInput("axis_color", "Axis colour (hex)", "#33413c"),
      numericInput("axis_line_width", "Axis line width", 0.6, AXIS_LW_RANGE[1], AXIS_LW_RANGE[2], 0.1),
      tags$small(textOutput("paper_style_status"), textOutput("font_status")),
      sliderInput("width", "Figure width (in)", 4, 16, 8, 0.5),
      sliderInput("height", "Figure height (in)", 3, 12, 5.2, 0.2),
      numericInput("dpi", "PNG dpi", 300, 72, 1200, 50)
    ),
    mainPanel(
      width = 9,
      uiOutput("data_status"),
      tabsetPanel(
        tabPanel("Plot",
          br(),
          imageOutput("violin", height = "auto"),
          uiOutput("plot_notes"),
          br(),
          conditionalPanel("output.has_figure",
            downloadButton("dl_png", "PNG"), downloadButton("dl_svg", "SVG (editable)"),
            downloadButton("dl_pdf", "PDF (editable)")),
          # CT-R1 F20: no key to download -> the button is replaced by a sentence, not a failed download
          conditionalPanel("output.has_figure && output.has_key", downloadButton("dl_key", "Legend key (PNG + SVG + PDF)")),
          conditionalPanel("output.has_figure && !output.has_key",
                           tags$small("No sample or plate colours to key in this view (neutral violins, no plates, no points).")),
          checkboxInput("place_key", "Place key on figure", TRUE),
          h5("Legend text starter"), copy_box("key_text", 3)),
        tabPanel("Statistics",
          br(), h4("Omnibus test"), verbatimTextOutput("omni"),
          h4("Pairwise (adjusted)"), scroll_box(DTOutput("pairwise")),
          conditionalPanel("output.has_figure", br(),
                           downloadButton("dl_stats", "Download statistics (CSV)")),
          h4("Paste-ready sentence"), copy_box("sentence", 4)),
        tabPanel("Summaries",
          br(), h4("Per group"), scroll_box(DTOutput("summary_group")),
          downloadButton("dl_sumg", "Download group summary CSV"),
          h4("Per plate (replicate means)"), scroll_box(DTOutput("summary_rep")),
          downloadButton("dl_sumr", "Download replicate summary CSV")),
        tabPanel("Data format",
          br(), format_help())
      )
    )
  )
)

server <- function(input, output, session) {

  raw <- reactiveVal(NULL)
  data_msg <- reactiveVal(NULL)               # list(type = "error" | "info", text = ...)
  notify <- function(text, type = "warning", duration = 10)
    tryCatch(showNotification(text, type = type, duration = duration, session = session),
             error = function(e) NULL)

  # CT-R1 F9/F10: every file goes through one reader; whatever it cannot use becomes a plain
  # message at the top of the page (and a notification), never a blank page or a raw R error
  load_table <- function(path, name) {
    res <- tryCatch({ r <- read_plaque_table(path, name); check_plaque_table(r$df, name); r },
                    plaque_data_problem = function(e) e,
                    error = function(e) structure(class = c("plaque_data_problem", "error", "condition"),
                      list(message = paste0("'", name, "' could not be read as a table. Save it as CSV ",
                                            "(comma delimited) and upload that file."), call = NULL)))
    if (inherits(res, "plaque_data_problem")) {
      raw(NULL)
      data_msg(list(type = "error", text = conditionMessage(res)))
      notify(conditionMessage(res), type = "error", duration = 15)
      return(invisible(FALSE))
    }
    raw(res$df)
    data_msg(list(type = "info", text = paste0(
      "Loaded '", name, "': ", nrow(res$df), " rows, ", ncol(res$df), " columns",
      if (length(res$notes)) paste0(" (", paste(res$notes, collapse = "; "), ")") else "", ".")))
    invisible(TRUE)
  }
  observeEvent(input$file, {
    load_table(input$file$datapath, input$file$name)
  })
  observeEvent(input$load_example, {
    cand <- c("example_data_wide.csv",
              file.path("plaque_stats", "example_data_wide.csv"))
    p <- cand[file.exists(cand)][1]
    if (!is.na(p)) load_table(p, "example_data_wide.csv")
    else showNotification("example_data_wide.csv not found — run: python plaque_stats.py --make-example",
                          type = "warning")
  })
  output$data_status <- renderUI({
    m <- data_msg(); if (is.null(m)) return(NULL)
    div(class = if (m$type == "error") "alert alert-danger" else "alert alert-info",
        style = "margin-top: 8px; padding: 8px 12px;", role = "alert", m$text)
  })

  output$col_pickers <- renderUI({
    df <- raw(); req(df)
    cols <- names(df)
    nums <- numeric_cols(df)
    lc <- long_cols(df)
    g0 <- pick_col(cols, GROUP_NAMES)
    if (is.na(g0)) g0 <- (setdiff(cols, nums)[1]) %||% cols[1]
    r0 <- pick_col(cols, REPLICATE_NAMES) %||% "(none)"
    v_choices <- setdiff(nums, g0)
    v0 <- pick_col(v_choices, c("diameter_mm", "value")) %||% (setdiff(v_choices, r0)[1] %||% v_choices[1])
    tagList(
      selectInput("group", "Group column", cols, selected = g0),
      selectInput("replicate", "Replicate column (plate)", c("(none)", cols), selected = r0),
      if (!is.null(lc))
        selectInput("metric", "Metric to plot",
                    unique(as.character(df[[lc$metric]])), selected = unique(as.character(df[[lc$metric]]))[1])
      else
        selectInput("value", "Value column", v_choices, selected = v0)
    )
  })

  # tidy long frame: group, replicate, value
  dat <- reactive({
    df <- raw()
    shiny::validate(shiny::need(!is.null(df), "No data loaded yet. Choose a CSV/TSV file on the left, or click 'Load example data'."))
    req(input$group, input$group %in% names(df))
    lc <- long_cols(df)
    if (!is.null(lc)) req(input$metric) else req(input$value, input$value %in% names(df))
    d <- tidy_plaque_data(df, input$group, input$replicate, input$value, input$metric, input$order %||% "")
    info <- attr(d, "info")
    shiny::validate(shiny::need(nrow(d) > 0, paste0(
      "No usable rows: column '", info$value_col, "' has no numbers for the chosen sample column '",
      input$group, "'. Pick another value column on the left, or check the file.")))
    d
  })

  metric_name <- reactive({
    df <- raw()
    if (!is.null(long_cols(df))) input$metric else input$value
  })

  # CT-R1 F1/F2/F11: every statistic comes from plaque_run_stats(), the port of the Python
  # engine's run_stats(); the unit it returns is the unit that was actually tested
  stats <- reactive({
    plaque_run_stats(dat(), input$unit %||% "auto", input$param %||% "auto", input$equal_var %||% "auto")
  })
  has_rep <- reactive(isTRUE(stats()$have_rep))
  rep_means <- reactive({
    rm <- stats()$rm; req(!is.null(rm))
    rm
  })
  use_unit <- reactive(stats()$unit)
  # the figure is a SuperPlot (plate-coloured points, plate means, mean +/- error of the plate
  # means) when every sample has >= 2 plates, and also when plate means were tested anyway
  superplot <- reactive({
    st <- stats()
    !is.null(st$rm) && (isTRUE(st$have_rep) || identical(st$unit, "replicate"))
  })

  # CT-R1 F20: the typed palette never raises; what it rejected is said once typing stops
  palette_parsed <- reactive(parse_palette(input$palette))
  palette_vec <- reactive({
    pn <- input$palette_name %||% ""
    if (!identical(pn, "") && !is.null(PALETTES[[pn]])) return(PALETTES[[pn]])
    if (identical(pn, "paper")) return(OKABE_ITO)
    p <- palette_parsed()$colours
    if (length(p)) p else OKABE_ITO
  })
  palette_settled <- debounce(reactive(list(txt = input$palette %||% "", name = input$palette_name %||% "",
                                            n = length(current_levels()))), 900)
  output$palette_status <- renderText({
    s <- palette_settled()
    if (!identical(s$name, "")) return("")
    p <- parse_palette(s$txt); msg <- character(0)
    if (length(p$rejected))
      msg <- c(msg, sprintf("Not a colour, left out: %s. Use hex codes such as #D55E00, separated by commas.",
                            paste0("'", p$rejected, "'", collapse = ", ")))
    if (length(p$colours) && s$n > length(unique(toupper(p$colours))))
      msg <- c(msg, sprintf("%d colour%s for %d samples: the other samples were given darker or lighter shades, so no two samples share a colour.",
                            length(unique(toupper(p$colours))), if (length(unique(toupper(p$colours))) > 1) "s" else "", s$n))
    paste(msg, collapse = " ")
  })

  # --- Colour registry: sample colours keyed by NAME ------------------------------------------
  # It outlives the CSV: loading another file keeps every name it has seen and gives a new name
  # the first colour of the current palette no other name uses. Choosing another colour theme
  # (or typing custom hex) reassigns the names loaded now in level order from the new palette;
  # names not loaded keep theirs. A paper style merges its sample_palette in by name, and keeps
  # doing so while "Paper style" is the colour theme (CT-R1 F15: one click on the theme menu
  # used to throw the style's colours away for good).
  colour_registry <- reactiveVal(setNames(character(0), character(0)))
  style_palette <- reactiveVal(setNames(character(0), character(0)))   # the style's name -> colour
  style_on <- reactiveVal(FALSE)                                       # are they in force?
  current_levels <- reactive({
    d <- tryCatch(dat(), error = function(e) NULL)
    if (is.null(d)) character(0) else levels(d$group)
  })
  palette_seen <- NULL                        # the palette the registry was last assigned from
  observe({
    lv <- current_levels(); sp <- style_palette()
    src <- list(name = input$palette_name %||% "", pal = palette_vec())
    old <- isolate(colour_registry()); reg <- old
    on <- isolate(style_on())
    if (!is.null(palette_seen) && !identical(src, palette_seen)) {
      if (length(lv)) reg[lv] <- distinct_colours(src$pal, length(lv))
      on <- identical(src$name, "paper")
      style_on(on)
    }
    palette_seen <<- src
    if (on && length(sp)) reg[names(sp)] <- unname(sp)
    reg <- extend_colour_registry(reg, lv, src$pal)
    if (!identical(reg, old)) colour_registry(reg)
  }, priority = 10)

  # --- Font and the shared look ---------------------------------------------------------------
  font_resolved <- reactive(resolve_font_family(font_family_request(input$font_family,
                                                                    input$font_family_custom)))
  # debounced so typing a custom name does not raise a notice per keystroke; said once
  font_settled <- debounce(reactive(font_family_request(input$font_family, input$font_family_custom)), 1000)
  observeEvent(font_settled(), {
    f <- resolve_font_family(font_settled())
    if (!isTRUE(f$available))
      tryCatch(showNotification(paste0(f$requested, " is not installed on this machine; drawn with the default sans."),
                                type = "warning", duration = 8), error = function(e) NULL)
  })
  output$font_status <- renderText({
    f <- font_resolved()
    if (isTRUE(f$available)) "" else paste0("Font: ", f$requested, " was not found on this machine; drawn with the default sans.")
  })
  # base size, family (as ggplot takes it), axis colour and line width, with the defaults the
  # figure has always had when an input is blank or invalid; out-of-range numbers are clamped
  # and said (CT-R1 F14: 120 pt and a 12-wide axis used to be drawn as typed)
  look <- reactive({
    bs <- clamp_look(input$base_size, BASE_SIZE_RANGE, 14, "Base font size")
    col <- trimws(if (is.null(input$axis_color)) "" else as.character(input$axis_color)[1])
    if (is.na(col) || !nzchar(col) || inherits(try(grDevices::col2rgb(col), silent = TRUE), "try-error"))
      col <- "#33413c"
    lw <- clamp_look(input$axis_line_width, AXIS_LW_RANGE, 0.6, "Axis line width")
    notes <- c(bs$note, lw$note)
    list(base_size = bs$value, family = drawn_family(font_resolved()$family), axis_color = col,
         axis_line_width = lw$value, notes = if (length(notes)) paste0(notes, ".") else character(0))
  })
  fig_size <- reactive({
    w <- suppressWarnings(as.numeric(input$width)); h <- suppressWarnings(as.numeric(input$height))
    list(w = if (length(w) == 1 && is.finite(w) && w > 0) w else 8,
         h = if (length(h) == 1 && is.finite(h) && h > 0) h else 5.2)
  })

  # THE colour mapping of the figure (and of its legend key)
  style <- reactive({
    d <- dat(); req(nrow(d) > 0)
    pn <- input$palette_name %||% ""
    chose_theme <- (!identical(pn, "") && !is.null(PALETTES[[pn]])) ||
                   (identical(pn, "") && length(palette_parsed()$colours) > 0) ||
                   # CT-R1 F15: a paper style colours the violins only when it names a sample
                   # that is in this data
                   (isTRUE(style_on()) && any(levels(d$group) %in% names(style_palette())))
    # colour the violins by group when the user asks for group fill, OR picks a colour theme
    # (otherwise the theme silently does nothing under the neutral grey SuperPlot default),
    # OR a paper style named the sample colours; otherwise keep the grey SuperPlot violin so
    # the plate colours carry the hue.
    style_map(d, colour_registry(), input$vfill, chose_theme, isTRUE(superplot()), palette_vec(),
              show_points = !identical(input$show_points, FALSE))
  })
  key <- reactive(key_entries(style()))

  # --- Paper style: the paper_style.json CFU Plot Studio 0.4.0 writes, applied at start ------
  # Only the keys both apps share are taken (an explicit allowlist); everything else in the file
  # (plot_title, legend_position, x_angle, download_width, y_min, time_palette, ...) is ignored.
  paper_style_status <- reactiveVal("")
  paper_style_applied <- reactiveVal(list(inputs = list(), sample_palette = list()))
  paper_style_report <- reactiveVal(NULL)     # what was applied / not applied, in words
  # CT-R1 F14: the status line says what the style did: the settings applied, how many of its
  # sample names are in this data, and everything that was left out and why
  output$paper_style_status <- renderText({
    base <- paper_style_status(); rep <- paper_style_report()
    if (is.null(rep)) return(base)
    sp <- style_palette(); lv <- current_levels(); parts <- character(0)
    if (length(rep$applied)) parts <- c(parts, paste0("Applied: ", paste(rep$applied, collapse = "; "), "."))
    if (length(sp)) {
      hit <- lv[lv %in% names(sp)]
      parts <- c(parts,
        if (!length(lv)) sprintf("Sample colours for %d names are ready (no data loaded yet).", length(sp))
        else if (!isTRUE(style_on())) sprintf("The colour theme was changed, so the style's %d sample colours are not in use; choose 'Paper style' under Colour theme to bring them back.", length(sp))
        else if (!length(hit)) sprintf("None of the style's %d sample names (%s) is in this data, so no style colour is used.",
                                       length(sp), paste(utils::head(names(sp), 4), collapse = ", "))
        else sprintf("Sample colours: %d of the style's %d names are in this data (%s).", length(hit), length(sp),
                     paste(hit, collapse = ", ")))
    } else parts <- c(parts, "The style names no sample colours.")
    if (length(rep$skipped)) parts <- c(parts, paste0("Not applied: ", paste(rep$skipped, collapse = "; "), "."))
    if (length(rep$unused))
      parts <- c(parts, sprintf("%d other setting%s in the file %s not used by this app (%s%s).", length(rep$unused),
                                if (length(rep$unused) > 1) "s" else "", if (length(rep$unused) > 1) "are" else "is",
                                paste(utils::head(rep$unused, 4), collapse = ", "),
                                if (length(rep$unused) > 4) ", …" else ""))
    paste(c(base, parts), collapse = " ")
  })
  load_paper_style <- function() {
    path <- paper_style_path()
    if (!file.exists(path)) {
      paper_style_status(paste0("No paper style (looked for ", path, ")."))
      return(invisible(NULL))
    }
    style <- tryCatch(jsonlite::read_json(path, simplifyVector = TRUE), error = function(e) NULL)
    if (is.null(style) || !is.list(style)) {
      paper_style_status(paste0("Paper style at ", path, " could not be read; nothing was applied."))
      return(invisible(NULL))
    }
    s <- if (is.list(style$settings)) style$settings else style
    scalar <- function(x) if (is.null(x) || !length(x)) NULL else unlist(x)[[1]]
    applied <- list(); said <- character(0); skipped <- character(0)
    # font_family (+ font_family_custom) -> font_family (+ font_family_custom)
    ff <- scalar(s$font_family)
    if (is.character(ff) && !is.na(ff) && nzchar(ff)) {
      custom <- scalar(s$font_family_custom)
      custom <- if (is.character(custom) && !is.na(custom)) custom else ""
      if (!ff %in% c("sans", "Arial", "Helvetica", "Times New Roman", "serif", "custom")) {
        custom <- ff; ff <- "custom"                   # a family the menu lacks goes via Custom…
      }
      updateSelectInput(session, "font_family", selected = ff)
      updateTextInput(session, "font_family_custom", value = custom)
      applied$font_family <- ff; applied$font_family_custom <- custom
      said <- c(said, paste0("font ", font_family_request(ff, custom)))
    }
    if (!is.null(scalar(s$font_size))) {                                  # font_size -> base_size
      fs <- clamp_look(scalar(s$font_size), BASE_SIZE_RANGE, NA, "font_size")
      if (isTRUE(fs$ok) && fs$value > 0) {
        updateNumericInput(session, "base_size", value = fs$value); applied$base_size <- fs$value
        said <- c(said, paste0("base font size ", format(fs$value), " pt"))
        if (!is.null(fs$note)) skipped <- c(skipped, fs$note)
      } else skipped <- c(skipped, sprintf("font_size '%s' is not a number", format(scalar(s$font_size))))
    }
    ac <- scalar(s$axis_color)                                          # axis_color -> axis_color
    if (!is.null(ac)) {
      if (valid_colour(ac)) {
        updateTextInput(session, "axis_color", value = ac); applied$axis_color <- ac
        said <- c(said, paste0("axis colour ", ac))
      } else skipped <- c(skipped, sprintf("axis_color '%s' is not a colour", format(ac)))
    }
    if (!is.null(scalar(s$axis_line_width))) {                          # axis_line_width -> same
      lw <- clamp_look(scalar(s$axis_line_width), AXIS_LW_RANGE, NA, "axis_line_width")
      if (isTRUE(lw$ok)) {
        updateNumericInput(session, "axis_line_width", value = lw$value); applied$axis_line_width <- lw$value
        said <- c(said, paste0("axis line width ", format(lw$value)))
        if (!is.null(lw$note)) skipped <- c(skipped, lw$note)
      } else skipped <- c(skipped, sprintf("axis_line_width '%s' is not a number", format(scalar(s$axis_line_width))))
    }
    # sample_palette (name -> hex) merges into the registry BY NAME; names the data lacks are
    # kept, so one style can name every strain of the paper. {} changes nothing.
    pal <- unlist(s$sample_palette); kept <- list()
    if (length(pal) && !is.null(names(pal))) {
      reg <- isolate(colour_registry())
      for (nm in names(pal)) {
        hx <- as.character(pal[[nm]])
        if (nzchar(nm) && valid_colour(hx)) {
          if (grepl("^#[0-9A-Fa-f]{8}$", hx)) hx <- substr(hx, 1, 7)     # no alpha in a sample colour
          reg[[nm]] <- hx; kept[[nm]] <- hx
        } else if (nzchar(nm)) skipped <- c(skipped, sprintf("the colour of '%s' ('%s') is not a colour", nm, hx))
      }
      if (length(kept)) {
        colour_registry(reg)
        style_palette(setNames(unlist(kept), names(kept))); style_on(TRUE)
        # "Paper style" becomes the first colour theme, so the style's colours can always be
        # brought back after trying another theme
        updateSelectInput(session, "palette_name",
                          choices = c("Paper style (colours by sample name)" = "paper", THEME_CHOICES),
                          selected = "paper")
      }
    }
    used_keys <- c("font_family", "font_family_custom", "font_size", "axis_color", "axis_line_width",
                   "sample_palette")
    paper_style_applied(list(inputs = applied, sample_palette = kept))
    paper_style_report(list(applied = said, skipped = skipped, unused = setdiff(names(s), used_keys)))
    paper_style_status(paste0("Paper style: ", path, ", saved ",
                              if (!is.null(style$created_at)) style$created_at else "at an unknown time", "."))
    invisible(applied)
  }
  # after the first flush, so the inputs the style updates exist in the page
  session$onFlushed(function() isolate(load_paper_style()), once = TRUE)

  # CT-R1 F21: values a log axis cannot show
  log_dropped <- reactive({
    d <- dat()
    if (!isTRUE(input$log_y)) return(NULL)
    bad <- d$value <= 0
    if (!any(bad)) return(NULL)
    by <- table(droplevels(d$group[bad]))
    list(n = sum(bad), total = nrow(d),
         caption = sprintf("Log axis: %d of %d values are 0 or negative and cannot be shown (%s).", sum(bad), nrow(d),
                           paste0(names(by), ": ", as.integer(by), collapse = ", ")))
  })

  # CT-R1 F7: the brackets, laid out above the tallest drawn element
  brackets <- reactive({
    d <- dat(); st <- stats(); lk <- look(); lev <- levels(d$group)
    sel <- pairs_to_draw(st$pairwise, lev, input$annotate %||% "auto", st$posthoc)
    out <- list(pairs = NULL, note = sel$note, caption = sel$caption, top = NA_real_)
    if (!nrow(sel$pairs)) return(out)
    logy <- isTRUE(input$log_y)
    tr <- function(v) if (logy) log10(v[v > 0]) else v
    vals <- tr(d$value)
    if (!length(vals)) return(out)
    top <- max(vals); bottom <- min(vals)
    if (isTRUE(superplot())) {                 # the error bars of the plate means can be taller
      fd <- summary_fun(input$center %||% "mean", input$error %||% "auto"); rm <- st$rm
      for (g in lev) {
        v <- tr(rm$value[rm$group == g])
        if (length(v)) top <- max(top, fd(v)$ymax, na.rm = TRUE)
      }
    }
    lay <- bracket_layout(sel$pairs, top, bottom, scale = max(1, lk$base_size / 14))
    p <- lay$pairs; head <- lay$top
    if (!identical(input$show_n, FALSE)) head <- head + (head - bottom) * 0.08 * max(1, lk$base_size / 14)
    back <- function(v) if (logy) 10^v else v
    p$y <- back(p$y); p$ytip <- back(p$ytip); p$ylab <- back(p$ylab)
    out$pairs <- p; out$top <- back(head)
    out
  })

  make_main <- function(family = look()$family) {
    d <- dat(); req(nrow(d) > 0)
    sm <- style(); lk <- look()         # colours by name; font, base size, axis colour + width
    superplot <- sm$superplot           # Violin SuperPlot: plate-coloured points + plate means
    neutral_violin <- sm$neutral
    # CT-R1 F23: the jitter is seeded, so the points do not move between redraws and the
    # preview is the download
    jit <- position_jitter(width = 0.09, height = 0, seed = 1)
    g <- ggplot(d, aes(group, value))
    if (neutral_violin) {
      g <- g + geom_violin(fill = "#b9c2bd", color = "#6f7b74", alpha = 0.38,
                           width = 0.85, trim = TRUE, linewidth = 0.5)
    } else {
      # one layer per sample in its mapped colour: the plate means below own the fill scale
      for (lv in levels(d$group))
        g <- g + geom_violin(data = d[d$group == lv, ], fill = sm$gcol[[lv]], color = NA,
                             alpha = 0.25, width = 0.85, trim = TRUE)
    }
    if (!identical(input$show_points, FALSE)) {
      if (superplot) {
        dd <- d; dd$.shape <- unname(sm$pshape[dd$replicate]); dd$.shape[is.na(dd$.shape)] <- 19L
        g <- g + geom_point(data = dd, aes(color = replicate, fill = replicate, shape = .shape),
                            position = jit, size = 1.5, alpha = 0.5)
      } else {
        # CT-R1 F8: each sample's points in that sample's colour (they were all drawn in the
        # FIRST sample's colour)
        g <- g + geom_point(aes(color = group), position = jit, size = 1.5, alpha = 0.45) +
          scale_color_manual(values = sm$gcol, guide = "none")
      }
    }
    if (superplot) {
      rm <- rep_means()
      rm$.shape <- unname(sm$rshape[rm$replicate])
      fdata <- summary_fun(input$center %||% "mean", input$error %||% "auto")
      cfun  <- if (identical(input$center, "median")) stats::median else base::mean
      g <- g +
        stat_summary(data = rm, aes(group, value), fun.data = fdata, geom = "errorbar",
                     width = 0, linewidth = 0.7, color = "#12211d") +
        # CT-R1 F6: the centre line. It was a crossbar with fatten = 0, which ggplot2 4.x
        # draws with stroke width 0 (invisible in SVG, PDF and PNG); now a plain segment at
        # the mean / median of the plate means, on the same (transformed) scale as the bar.
        stat_summary(data = rm, aes(x = stage(group, after_stat = x - 0.17), y = value,
                                    xend = after_stat(x + 0.17), yend = after_stat(y)),
                     fun = cfun, geom = "segment", linewidth = 0.7, color = "#12211d",
                     inherit.aes = FALSE) +
        geom_point(data = rm, aes(group, value, fill = replicate, shape = .shape),
                   size = 4.2, color = "#12211d", stroke = 0.9) +
        scale_fill_manual(values = sm$rcol, name = "plate", guide = "none") +
        scale_color_manual(values = sm$rcol, name = "plate", guide = "none") +
        scale_shape_identity()
    } else {
      # no replicates: a THIN, unfilled box (median + IQR) — lines only, not a filled rectangle
      g <- g + geom_boxplot(width = 0.12, outlier.shape = NA, fill = NA,
                            color = "#33413c", linewidth = 0.5)
    }
    br <- if (isTRUE(input$show_sig)) brackets() else NULL
    caption <- c(br$caption, log_dropped()$caption)
    g <- g +
      labs(title = if (nzchar(input$title %||% "")) input$title else NULL,
           y = if (nzchar(input$ylab %||% "")) input$ylab else metric_name(),
           x = if (nzchar(input$xlab %||% "")) input$xlab else NULL) +
      theme_classic(base_size = lk$base_size, base_family = family) +
      theme(plot.title = element_text(face = "bold"),
            axis.text.x = element_text(face = "bold"), axis.title = element_text(face = "bold"),
            legend.position = "none",       # the legend key (below) replaces ggplot's legend
            plot.margin = margin(t = 16, r = 12, b = 6, l = 6),
            # the frame is drawn 0.1 heavier than the axis lines, as it always was (0.7 vs 0.6)
            panel.border = if (isTRUE(input$frame))
              element_rect(fill = NA, color = lk$axis_color, linewidth = lk$axis_line_width + 0.1)
              else element_blank(),
            axis.line = if (isTRUE(input$frame)) element_blank()
                        else element_line(linewidth = lk$axis_line_width, color = lk$axis_color),
            axis.ticks = element_line(linewidth = lk$axis_line_width, color = lk$axis_color))
    if (length(caption))                 # only when there is something the figure must say
      g <- g + labs(caption = paste(caption, collapse = "\n")) +
        theme(plot.caption = element_text(hjust = 0, size = rel(0.7), colour = "#33413c"),
              plot.caption.position = "plot")
    if (!is.null(br$pairs))              # room above the data for the brackets and the n row
      g <- g + geom_blank(data = data.frame(group = factor(levels(d$group)[1], levels = levels(d$group)),
                                            value = br$top), aes(group, value))
    if (isTRUE(input$show_n)) {
      ns <- dplyr::count(d, group)
      # CT-R1 F23: the n row follows the base font size (3.3 at the default 14 pt)
      g <- g + geom_text(data = ns, aes(x = group, y = Inf, label = paste0("n = ", n)),
                         vjust = 1.4, size = 3.3 * (lk$base_size / 14), fontface = "bold", color = "#33413c",
                         family = family, inherit.aes = FALSE) +
        coord_cartesian(clip = "off")
    }
    if (isTRUE(input$log_y)) g <- g + scale_y_log10()
    if (!is.null(br$pairs)) {
      p <- br$pairs
      seg <- rbind(data.frame(x = p$x1, xend = p$x2, y = p$y, yend = p$y),
                   data.frame(x = p$x1, xend = p$x1, y = p$y, yend = p$ytip),
                   data.frame(x = p$x2, xend = p$x2, y = p$y, yend = p$ytip))
      p$xmid <- (p$x1 + p$x2) / 2
      p$vj <- ifelse(grepl("^\\*+$", p$label), 0.45, 0)     # stars sit low in their line box
      g <- g +
        geom_segment(data = seg, aes(x = x, xend = xend, y = y, yend = yend), inherit.aes = FALSE,
                     linewidth = 0.3, colour = "black") +
        # stars and p-values follow the base font size too (3.88 at 14 pt, as ggpubr drew them)
        geom_text(data = p, aes(x = xmid, y = ylab, label = label, vjust = vj), inherit.aes = FALSE,
                  size = 3.88 * (lk$base_size / 14),
                  family = family, colour = "black")
    }
    g
  }
  build_main <- reactive(make_main())

  # CT-R1 F17: where the placed key goes. Beside the plot (top right) when it fits; under the
  # plot when it is too wide for that but short; not placed at all -- with a note -- when it
  # fits neither way, because a key squeezed into the figure is unreadable.
  key_place <- reactive({
    e <- key(); lk <- look(); fs <- fig_size()
    if (!isTRUE(input$place_key) || !nrow(e)) return(list(where = "none", note = NULL))
    ks <- key_size(e, lk$base_size); kw <- ks[["width"]]; kh <- ks[["height"]]
    if (kw <= 0.5 * fs$w && kh <= fs$h) return(list(where = "beside", kw = kw, kh = kh, note = NULL))
    if (kh <= 0.5 * fs$h && kw <= fs$w) return(list(where = "below", kw = kw, kh = kh, note = NULL))
    list(where = "none", kw = kw, kh = kh,
         note = sprintf("The key was not placed on the figure: at this font size it needs %.1f x %.1f in and the figure is %.1f x %.1f in. Make the figure wider or taller, lower the base font size, or use the Legend key download (it always holds the full key).",
                        kw, kh, fs$w, fs$h))
  })
  # the figure: the main plot, plus the legend key beside it when "Place key on figure" is on --
  # the very same key_plot() the "Legend key" download saves
  make_plot <- function(family = look()$family) {
    g <- make_main(family); e <- key(); lk <- look(); kp <- key_place(); fs <- fig_size()
    if (identical(kp$where, "beside")) {
      side <- ggpubr::ggarrange(key_plot(e, lk$base_size, family), NULL, ncol = 1,  # key at its own size, top-right
                                heights = c(kp$kh, max(0.1, fs$h - kp$kh)))
      return(ggpubr::ggarrange(g, side, widths = c(max(1, fs$w - kp$kw), kp$kw)))
    }
    if (identical(kp$where, "below")) {
      foot <- ggpubr::ggarrange(key_plot(e, lk$base_size, family), NULL, ncol = 2,
                                widths = c(kp$kw, max(0.1, fs$w - kp$kw)))
      return(ggpubr::ggarrange(g, foot, ncol = 1, heights = c(max(1, fs$h - kp$kh), kp$kh)))
    }
    g
  }
  build_plot <- reactive(make_plot())

  # CT-R1 F17: the preview IS the download -- the figure at its width x height in inches,
  # scaled to the page -- so what overlaps on screen overlaps in the file and vice versa
  # (it used to be drawn at the page's size, whatever the figure size was).
  output$violin <- renderImage({
    p <- build_plot(); fs <- fig_size()
    wpx <- session$clientData$output_violin_width
    if (is.null(wpx) || !is.finite(wpx) || wpx <= 0) wpx <- 900
    wpx <- max(200, min(wpx, 1100, 720 * fs$w / fs$h))
    pr <- session$clientData$pixelratio; if (is.null(pr) || !is.finite(pr) || pr <= 0) pr <- 1
    f <- tempfile(fileext = ".png")
    drawn <- tryCatch({ suppressWarnings(ggsave(f, p, width = fs$w, height = fs$h, dpi = wpx * pr / fs$w,
                                                device = "png", bg = "white")); NULL },
                      error = function(e) conditionMessage(e))
    shiny::validate(shiny::need(is.null(drawn), paste0("The figure could not be drawn with these settings (", drawn,
                                         "). Change the last setting back, or reload the data.")))
    list(src = f, width = round(wpx), height = round(wpx * fs$h / fs$w), contentType = "image/png",
         alt = "Violin plot of the loaded data")
  }, deleteFile = TRUE)
  has_figure <- reactive(!is.null(tryCatch(dat(), error = function(e) NULL)))
  output$has_figure <- has_figure
  try(outputOptions(output, "has_figure", suspendWhenHidden = FALSE), silent = TRUE)
  has_key <- reactive(nrow(tryCatch(key(), error = function(e) NULL) %||% data.frame()) > 0)
  output$has_key <- has_key
  try(outputOptions(output, "has_key", suspendWhenHidden = FALSE), silent = TRUE)
  output$key_text <- renderText({ s <- text_starter(key()); if (nzchar(s)) s else "(no sample colours to key)" })

  # everything the user should know about this figure, in one visible place under it
  # (CT-R1 F2, F7, F12, F13, F21): rows left out, the unit that was tested and why, which
  # comparisons are drawn, values a log axis cannot show, a key that does not fit
  figure_notes <- reactive({
    d <- dat(); st <- stats(); sm <- style()
    out <- c(attr(d, "info")$notes, st$warnings)
    if (isTRUE(input$show_sig)) out <- c(out, brackets()$note)
    ld <- log_dropped()
    if (!is.null(ld)) out <- c(out, paste(ld$caption, "The statistics still use every value; untick 'Log y-axis' to see them all."))
    if (length(sm$recoloured))
      out <- c(out, sprintf("%s had the same colour as another sample here, so %s given a different shade.",
                            paste(sm$recoloured, collapse = ", "), if (length(sm$recoloured) > 1) "they were" else "it was"))
    unique(c(out, key_place()$note, look()$notes))
  })
  output$plot_notes <- renderUI({
    n <- tryCatch(figure_notes(), error = function(e) NULL)
    if (!length(n)) return(NULL)
    div(class = "alert alert-warning", style = "margin-top: 8px; padding: 8px 12px;",
        tags$ul(style = "margin: 0; padding-left: 18px;", lapply(n, tags$li)))
  })

  summ_group_full <- reactive({
    d <- dat()
    d %>% group_by(group) %>%
      summarise(n = n(), n_plates = length(unique(replicate[!is.na(replicate)])),
                mean = mean(value), sd = sd(value), sem = sd(value) / sqrt(n()),
                ci95_lo = if (n() > 1) mean(value) - qt(.975, n() - 1) * sd(value) / sqrt(n()) else NA_real_,
                ci95_hi = if (n() > 1) mean(value) + qt(.975, n() - 1) * sd(value) / sqrt(n()) else NA_real_,
                median = median(value), q1 = quantile(value, .25), q3 = quantile(value, .75),
                iqr = quantile(value, .75) - quantile(value, .25),
                min = min(value), max = max(value),
                cv_pct = 100 * sd(value) / mean(value), .groups = "drop")
  })
  summ_group <- reactive(summ_group_full() %>% mutate(across(where(is.numeric), ~round(., 4))))

  # CT-R1 F22: tables scroll inside their own box; CT-R1 F19: no paging (66 pairs were cut at 10)
  dt_opts <- list(dom = "t", scrollX = TRUE, paging = FALSE)
  output$summary_group <- renderDT(datatable(summ_group(), options = dt_opts))
  output$summary_rep <- renderDT({
    if (is.null(stats()$rm)) return(datatable(data.frame(note = "no replicate column"), options = dt_opts))
    datatable(rep_means() %>% mutate(value = round(value, 4)), options = dt_opts)
  })
  pairwise_table <- reactive({
    st <- stats(); pw <- st$pairwise
    data.frame(group1 = pw$group1, group2 = pw$group2, n1 = pw$n_a, n2 = pw$n_b,
               mean_a = pw$mean_a, mean_b = pw$mean_b, mean_diff = pw$mean_diff,
               p_adj = pw$p_adj, signif = pw$signif, stringsAsFactors = FALSE)
  })
  output$pairwise <- renderDT({
    pw <- pairwise_table()
    if (!nrow(pw)) return(datatable(data.frame(note = "Nothing to compare: only one sample has data."),
                                    options = dt_opts))
    # CT-R1 F19: p to 3 significant digits, "< 0.001" below that (cells used to read
    # 0.000006505873659801154, or 0)
    for (cn in c("mean_a", "mean_b", "mean_diff")) pw[[cn]] <- round(pw[[cn]], 4)
    pw$p_adj <- fmt_p3(pw$p_adj)
    datatable(pw, options = dt_opts)
  })
  output$omni <- renderText(omnibus_text(stats()))
  output$sentence <- renderText({
    s <- summ_group_full()
    stats_sentence(metric_name(), as.data.frame(s), stats())
  })

  # --- downloads ------------------------------------------------------------------------------
  # CT-R1 F20: a blank, zero or absurd dpi no longer fails the download; it is replaced and said
  checked_dpi <- function() {
    v <- suppressWarnings(as.numeric(input$dpi))
    if (length(v) == 1 && is.finite(v) && v >= 72 && v <= 1200) return(v)
    notify("PNG dpi must be a number from 72 to 1200. This download used 300 dpi; correct the 'PNG dpi' box to change it.")
    300
  }
  failed <- function(what) function(e) {
    notify(sprintf("The %s could not be made (%s). Nothing was saved; change the last setting back and try again.",
                   what, conditionMessage(e)), type = "error", duration = 15)
    stop(e)
  }
  figure_name <- function(ext) sprintf("violin_%s.%s", metric_name(), ext)
  output$dl_png <- downloadHandler(
    filename = function() figure_name("png"),
    content = function(f) tryCatch({
      fs <- fig_size()                       # CT-R1 F16: white under the key, never transparent
      ggsave(f, build_plot(), width = fs$w, height = fs$h, dpi = checked_dpi(), device = "png", bg = "white")
    }, error = failed("PNG")))
  output$dl_svg <- downloadHandler(
    filename = function() figure_name("svg"),
    content = function(f) tryCatch({
      fs <- fig_size()
      ggsave(f, build_plot(), width = fs$w, height = fs$h, device = svglite::svglite)
    }, error = failed("SVG")))
  output$dl_pdf <- downloadHandler(
    filename = function() figure_name("pdf"),
    content = function(f) tryCatch({
      fs <- fig_size()
      note <- save_pdf(f, make_plot, look()$family, fs$w, fs$h)
      if (!is.null(note)) notify(note)
    }, error = failed("PDF")))
  output$dl_key <- downloadHandler(
    filename = function() sprintf("violin_%s_legend_key.zip", metric_name()),
    content = function(f) tryCatch({
      e <- key()
      if (!nrow(e)) stop("there is nothing to key in this view")
      tmp <- tempfile("key"); dir.create(tmp)
      base <- file.path(tmp, sprintf("violin_%s", metric_name()))
      lk <- look()
      files <- write_key_files(e, base, checked_dpi(), lk$base_size, lk$family)
      for (n in attr(files, "notes")) notify(n)
      # the zip package needs no external program (utils::zip needs a 'zip' on the PATH, which
      # a stock Windows R lacks); fall back to utils::zip where the package is not installed
      if (requireNamespace("zip", quietly = TRUE)) zip::zipr(f, as.character(files))
      else utils::zip(f, as.character(files), flags = "-j")
    }, error = failed("legend key")))
  # CT-R1 F19: the numbers behind the Statistics tab, unrounded, in one CSV: the omnibus test,
  # every pairwise comparison, the values that were tested and the per-plaque group summary
  output$dl_stats <- downloadHandler(
    filename = function() sprintf("statistics_%s.csv", metric_name()),
    content = function(f) tryCatch({
      st <- stats(); con <- file(f, open = "w", encoding = "UTF-8"); on.exit(close(con))
      section <- function(title, df) {
        writeLines(paste0("# ", title), con)
        utils::write.csv(df, con, row.names = FALSE, na = "")
        writeLines("", con)
      }
      section("Omnibus test", data.frame(
        metric = metric_name(), test = st$test, p = st$p, unit = st$unit, parametric = st$parametric_used,
        pairwise = st$posthoc, levene_p = st$levene_p, min_n = st$min_n, stringsAsFactors = FALSE))
      section(sprintf("Pairwise comparisons (%s; adjusted p)", if (is.na(st$posthoc)) st$test else st$posthoc),
              pairwise_table())
      section(sprintf("Tested values per sample (unit: %s)", st$unit), st$unit_stats)
      section("Group summary (per plaque)", as.data.frame(summ_group_full()))
      if (length(st$warnings)) writeLines(paste0("# NOTE: ", st$warnings), con)
    }, error = failed("statistics CSV")))
  output$dl_sumg <- downloadHandler("summary_by_group.csv",
    content = function(f) write_csv(summ_group_full(), f))
  output$dl_sumr <- downloadHandler("summary_by_replicate.csv",
    content = function(f) write_csv(if (!is.null(stats()$rm)) rep_means() else data.frame(), f))
}

shinyApp(ui, server)
