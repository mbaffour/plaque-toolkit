# Driven by tests/test_ct_r1_r_app.py (skipped where R or the app's packages are missing).
# Run from plaque_stats/ with OUT_DIR set. Click-through round 1 (CT-R1) findings F1..F24 of the
# R Shiny app (plaque_stats/app.R), checked with shiny::testServer and plain function calls.
# Prints one line per check:  PASS <id> <detail>   or   FAIL <id> <detail>
# The Python engine (plaque_stats.py) is the REFERENCE: the numbers below were produced by it.
out_dir <- Sys.getenv("OUT_DIR", tempdir())
fixtures <- normalizePath(file.path("..", "tests", "fixtures"))
Sys.setenv(CFU_PAPER_STYLE = file.path(out_dir, "no_paper_style.json"))
suppressMessages(suppressWarnings(source("app.R", chdir = TRUE)))
app <- shinyApp(ui, server)

chk <- function(id, ok, detail = "") {
  ok <- isTRUE(ok)
  cat(if (ok) "PASS" else "FAIL", " ", id, if (nzchar(detail)) paste0("  ", detail) else "", "\n", sep = "")
}
near <- function(a, b, tol = 1e-6) length(a) == length(b) && all(abs(a - b) <= tol | (is.na(a) & is.na(b)))
ui_defaults <- list(group = "group", replicate = "replicate", value = "diameter_mm", order = "",
                    unit = "auto", param = "auto", equal_var = "auto", show_points = TRUE,
                    vfill = "auto", center = "mean", error = "auto", show_n = TRUE, frame = FALSE,
                    show_sig = TRUE, annotate = "auto", log_y = FALSE, title = "", ylab = "",
                    xlab = "", palette_name = "", palette = "", width = 8, height = 5.2, dpi = 300,
                    place_key = TRUE, font_family = "sans", font_family_custom = "",
                    base_size = 14, axis_color = "#33413c", axis_line_width = 0.6)
tidy <- function(path, value = "diameter_mm", group = "group", replicate = "replicate", metric = NULL,
                 order = "") {
  df <- read_plaque_table(path)$df
  tidy_plaque_data(df, group, replicate, value, metric, order)
}
pw_p <- function(st) setNames(st$pairwise$p_adj, paste(st$pairwise$group1, st$pairwise$group2, sep = "|"))
tmp <- function(name, lines, mode = "w") {
  f <- file.path(out_dir, name)
  if (is.raw(lines)) writeBin(lines, f) else writeLines(lines, f, useBytes = TRUE)
  f
}
fx <- function(name) file.path(fixtures, name)

# ---- F1 + F11: R == Python ----------------------------------------------------------------------
# Python reference: python plaque_stats.py <file> --group group --replicate replicate
#   --value diameter_mm --out <dir>, then omnibus_test_diameter_mm.csv / pairwise_tests_diameter_mm.csv
# B_unequal.csv (tests/fixtures/ct_r1_B_unequal.csv), Levene p = 0.0199:
PY_B_OMNI <- 0.0025553501233988424
PY_B_PAIR <- c("WT|mutA" = 0.007377868408530719, "WT|mutB" = 0.0242435701197532,
               "mutA|mutB" = 0.4559728518028223)
# example_data_long.csv, --value diameter_mm (long file: the metric), Levene p = 0.62:
PY_A_OMNI <- 8.664450118784204e-06
PY_A_PAIR <- c("T4|T7" = 0.00014846125892786777, "T4|lambda" = 0.0011220469260948551,
               "T7|lambda" = 6.985589097507905e-06)
# ct_r1_E_oneplate_group.csv with --unit replicate (solo has ONE plate -> n/a):
# omnibus over the two samples that can be tested (WT, mutA); solo (1 plate) is n/a, as run_stats does
PY_E_OMNI <- 0.0014053424138857433
PY_E_PAIR <- c("WT|mutA" = 0.0014053424138855686, "WT|solo" = NA, "mutA|solo" = NA)
# ct_r1_D_two_12v14.csv: Welch t on plate means / Mann-Whitney U (scipy auto = asymptotic here)
PY_D_WELCH <- 0.0036614047047386056
PY_D_MWU <- 0.002210786372468205

stB <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")))
chk("F1_B_auto_is_welch", stB$test == "Welch ANOVA" && stB$posthoc == "Games-Howell",
    paste(stB$test, stB$posthoc))
chk("F1_B_omnibus_p", near(stB$p, PY_B_OMNI), sprintf("R %.12g py %.12g", stB$p, PY_B_OMNI))
chk("F1_B_pairwise_p", near(pw_p(stB), PY_B_PAIR), paste(sprintf("%.10g", pw_p(stB)), collapse = " "))
chk("F1_B_welch_reason_stated", any(grepl("Levene", stB$warnings)))
stBe <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "yes")
chk("F1_B_equal_is_classic", stBe$test == "one-way ANOVA" && stBe$posthoc == "Tukey HSD" &&
      near(stBe$p, 0.019484354511230786) && near(unname(pw_p(stBe)), c(0.14034054967218046, 0.014997722692196347,
                                                                      0.41712136513547327)))
stBu <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "no")
chk("F1_B_unequal_forced", stBu$test == "Welch ANOVA" && near(stBu$p, PY_B_OMNI))
# spread rule: NOTE with < 5 plates on the classic path, WARNING only on a significant Bonferroni F test
set.seed(12)
d8 <- do.call(rbind, lapply(list(c("a", 0.5), c("b", 0.05), c("c", 0.05)), function(x)
  data.frame(group = x[1], replicate = paste0("p", 1:8), value = rnorm(8, 2, as.numeric(x[2])))))
d8$group <- factor(d8$group, levels = c("a", "b", "c"))
st8 <- plaque_run_stats(d8, parametric = "parametric", equal_var = "yes")
chk("F1_spread_warning_when_significant", any(grepl("more than chance explains", st8$warnings)) && is.null(st8$spread_note),
    paste(st8$warnings, collapse = " | "))
stAuto8 <- plaque_run_stats(d8, parametric = "parametric", equal_var = "auto")
chk("F1_spread_warning_does_not_switch_auto", identical(stAuto8$test == "Welch ANOVA", levene_p(stAuto8$groups) < 0.05))
# parity with plaque_stats.py: at >= 8 plates auto = parametric iff every sample passes Shapiro; a failed
# Levene test then picks Welch + Games-Howell, it no longer sends normal data to Kruskal-Wallis
stFull8 <- plaque_run_stats(d8)
chk("F1_auto_8_plates_normal_unequal_is_welch", all(stFull8$normality_p > 0.05) && levene_p(stFull8$groups) < 0.05 &&
      isTRUE(stFull8$parametric_used) && stFull8$test == "Welch ANOVA" && stFull8$posthoc == "Games-Howell",
    paste(stFull8$test, signif(levene_p(stFull8$groups), 3)))
stEx <- plaque_run_stats(tidy(fx("../../plaque_stats/example_data_wide.csv")))
chk("F1_example_has_note_not_warning", grepl("assume the groups have similar spread", stEx$spread_note) &&
      grepl("With 3 plates per group", stEx$spread_note) && !any(grepl("chance explains|largest group SD", stEx$warnings)),
    paste(stEx$spread_note, paste(stEx$warnings, collapse = "|")))
chk("F1_note_shown_in_report_text", grepl("NOTE: ANOVA and Tukey assume", omnibus_text(stEx)))
stA <- plaque_run_stats(tidy(fx("../../plaque_stats/example_data_long.csv"), value = "diameter_mm",
                             metric = "diameter_mm"))
chk("F1_A_omnibus_p", stA$test == "one-way ANOVA" && near(stA$p, PY_A_OMNI), sprintf("%.12g", stA$p))
chk("F1_A_pairwise_p", near(pw_p(stA), PY_A_PAIR), paste(sprintf("%.10g", pw_p(stA)), collapse = " "))
chk("F1_A_pairwise_small_p_1e-6_relative", all(abs(pw_p(stA) / PY_A_PAIR - 1) < 1e-4))
chk("F1_test_named_in_report", grepl("Welch ANOVA", omnibus_text(stB)) && grepl("Games-Howell", omnibus_text(stB)))

stE <- plaque_run_stats(tidy(fx("ct_r1_E_oneplate_group.csv")), unit = "replicate")
chk("F2_E_unit_replicate", stE$unit == "replicate" && near(stE$p, PY_E_OMNI), sprintf("%s %.10g", stE$unit, stE$p))
chk("F2_E_pairwise_na_for_solo", near(pw_p(stE), PY_E_PAIR), paste(sprintf("%.8g", pw_p(stE)), collapse = " "))
chk("F2_E_warning_names_solo", any(grepl("solo", stE$warnings)) && any(grepl("n/a", stE$warnings)))
stE2 <- plaque_run_stats(tidy(fx("ct_r1_E_oneplate_group.csv")), unit = "auto")
# parity with plaque_stats.py (SM-F4): auto keeps the plate as the unit; the one-plate sample is n/a
chk("F2_E_auto_keeps_plate_unit_with_warning", stE2$unit == "replicate" && near(stE2$p, PY_E_OMNI) &&
      near(pw_p(stE2), PY_E_PAIR) && any(grepl("solo", stE2$warnings)) && !any(grepl("pseudoreplication", stE2$warnings)))
stE3 <- plaque_run_stats(tidy(fx("ct_r1_E_oneplate_group.csv")), unit = "plaque")
chk("F2_E_plaque_unit_still_warns", stE3$unit == "plaque" && any(grepl("pseudoreplication", stE3$warnings)))
dN <- tidy(fx("ct_r1_B_unequal.csv"), replicate = "(none)")
stN <- plaque_run_stats(dN, unit = "replicate")
chk("F2_no_plate_column_reports_plaque", stN$unit == "plaque" && !grepl("replicate = plate", omnibus_text(stN)) &&
      any(grepl("No plate", stN$warnings)))
stD <- plaque_run_stats(tidy(fx("ct_r1_D_two_12v14.csv")))
chk("F5_D_welch_p", near(stD$p, PY_D_WELCH, 1e-12))
stDn <- plaque_run_stats(tidy(fx("ct_r1_D_two_12v14.csv")), parametric = "nonparametric")
chk("F11_D_mannwhitney_asymptotic", near(stDn$p, PY_D_MWU, 1e-12) && grepl("normal approximation", stDn$method_note),
    sprintf("%.10g", stDn$p))
# n = 1 groups: n/a (python)
dd1 <- tidy(fx("ct_r1_B_unequal.csv"), replicate = "(none)")
dd1 <- rbind(dd1[dd1$group != "mutB", ], dd1[dd1$group == "mutB", ][1, ]); dd1$group <- droplevels(dd1$group)
st1 <- plaque_run_stats(dd1, unit = "plaque")
chk("F11_n1_group_is_na", all(is.na(pw_p(st1)[c("WT|mutB", "mutA|mutB")])), paste(pw_p(st1), collapse = " "))
chk("F11_stars_capped", all(p_stars(c(1e-9, 5e-4, 5e-3, 0.03, 0.2, NA)) == c("***", "***", "**", "*", "ns", "n/a")))

# ---- F19: p formatting ---------------------------------------------------------------------------
chk("F19_fmt", identical(fmt_p3(c(0.0001484560365915266, 6.5e-06, 0, 0.0123456, 0.5, NA)),
                         c("< 0.001", "< 0.001", "< 0.001", "0.0123", "0.500", "n/a")), paste(fmt_p3(c(0.0001484, 0.0123456, 0.5)), collapse = " "))
chk("F5_fmt_p_never_0.000", fmt_p(0.0004) == "< 0.001" && fmt_p(0.0036614) == "0.004")

# ---- F3 + F9 + F10 + F12: data in ----------------------------------------------------------------
set.seed(7)
mk <- function(sep = ",", dec = ".", groups = c("WT", "mutA", "mutB"), plates = 3, n = 8, head = c("group", "replicate", "diameter_mm")) {
  rows <- do.call(rbind, lapply(seq_along(groups), function(i) do.call(rbind, lapply(seq_len(plates), function(p)
    data.frame(g = groups[i], r = paste0("plate", p), v = round(rnorm(n, 2 + i * 0.4, 0.2), 3))))))
  v <- format(rows$v, nsmall = 3, trim = TRUE); if (dec == ",") v <- sub(".", ",", v, fixed = TRUE)
  c(paste(head, collapse = sep), paste(rows$g, rows$r, v, sep = sep))
}
read_ok <- function(f, ...) tryCatch(read_plaque_table(f, ...), plaque_data_problem = function(e) e)
r <- read_ok(tmp("semi.csv", mk(";")))
chk("F9_semicolon", !inherits(r, "error") && identical(names(r$df), c("group", "replicate", "diameter_mm")), paste(names(r$df), collapse = ","))
r <- read_ok(tmp("tab.tsv", mk("\t")))
chk("F9_tab", !inherits(r, "error") && ncol(r$df) == 3)
r <- read_ok(tmp("eu.csv", mk(";", ",")))
chk("F3_semicolon_decimal_comma", !inherits(r, "error") && all(is.finite(as.numeric(r$df$diameter_mm))) &&
      max(as.numeric(r$df$diameter_mm)) < 5 && any(grepl("decimal comma", r$notes)))
q <- mk(",", ","); q[-1] <- vapply(strsplit(q[-1], ","), function(x) paste0(x[1], ",", x[2], ',"', x[3], ",", x[4], '"'), "")
r <- read_ok(tmp("eu_quoted.csv", q))
# CT-R2: a comma inside a cell of a comma file can only come from quotes, so it is a decimal comma (Python reads it so)
chk("F3_quoted_decimal_comma_is_read", !inherits(r, "error") && all(is.finite(as.numeric(r$df$diameter_mm))) &&
      max(as.numeric(r$df$diameter_mm)) < 5 && any(grepl("decimal comma", r$notes)), if (inherits(r, "error")) conditionMessage(r) else "")
bad <- list(
  empty = raw(0), header_only = "group,replicate,diameter_mm",
  binary = as.raw(c(0:255, 0:255)), cp1252 = NULL,
  no_numeric = c("group,replicate,diameter_mm", "WT,p1,big", "WT,p1,huge"),
  one_col = c("a", "b", "c"), comments_only = c("# a", "# b"),
  xlsx = c(charToRaw("PK"), as.raw(c(3, 4, 0, 0, 8, 0, 0, 0))))
for (nm in setdiff(names(bad), "cp1252")) {
  f <- tmp(paste0("bad_", nm, ".csv"), bad[[nm]]); r <- read_ok(f)
  ok <- inherits(r, "plaque_data_problem") || (!inherits(r, "error") && tryCatch({ check_plaque_table(r$df); FALSE }, plaque_data_problem = function(e) TRUE))
  chk(paste0("F10_", nm, "_plain_message"), ok, if (inherits(r, "error")) conditionMessage(r) else "")
}
cp <- iconv(c("group,replicate,diameter_mm", "WT ±,p1,2.1", "WT ±,p1,2.3", "mut µ,p1,2.9", "mut µ,p1,3.1"), "UTF-8", "windows-1252")
r <- read_ok(tmp("cp.csv", charToRaw(paste(cp, collapse = "\r\n"))))
chk("F10_cp1252", !inherits(r, "error") && any(grepl("±", r$df$group)), paste(r$df$group, collapse = "|"))
f <- fx("../../plaque_stats/TEMPLATE.csv"); tp <- tidy(f, value = "diameter_mm", replicate = "replicate")
chk("F10_template_no_raw_error", !inherits(try(plaque_run_stats(tp), silent = TRUE), "try-error") &&
      all(is.na(plaque_run_stats(tp)$p) | TRUE))
st <- plaque_run_stats(tp); chk("F10_template_p_is_na", is.na(st$p) && !nzchar(paste(tryCatch(omnibus_text(st), error = function(e) "ERR"), collapse = "")) == FALSE)
# a text cell in the value column does not hide the column; value without metric is plain value
mv <- mk(","); mv[5] <- sub("[0-9.]+$", "2.5mm", mv[5]); mv[7] <- sub("[0-9.]+$", "-", mv[7])
r <- read_ok(tmp("missing.csv", mv))
chk("F9_text_cell_keeps_column", !inherits(r, "error") && "diameter_mm" %in% numeric_cols(r$df))
d <- tidy_plaque_data(r$df, "group", "replicate", "diameter_mm", NULL, "")
chk("F9_rows_dropped_reported", nrow(d) == 70 && any(grepl("^2 rows dropped: no numeric diameter_mm value \\(2 not a number, 0 empty\\)\\.$", attr(d, "info")$notes)), paste(attr(d, "info")$notes, collapse = " "))
lv <- mk(","); lv[1] <- "group,replicate,value"; r <- read_ok(tmp("long_nometric.csv", lv))
chk("F9_value_without_metric", is.null(long_cols(r$df)) && "value" %in% numeric_cols(r$df))
r <- read_ok(tmp("upper.csv", mk(",", head = c("GROUP", "REPLICATE", "DIAMETER_MM"))))
chk("F12_uppercase_headers", pick_col(names(r$df), GROUP_NAMES) == "GROUP" && pick_col(names(r$df), REPLICATE_NAMES) == "REPLICATE")
ts <- testServer(app, {
  df <- read_plaque_table(tmp("upper.csv", mk(",", head = c("GROUP", "REPLICATE", "DIAMETER_MM"))))$df
  raw(df)
  session$setInputs(group = "GROUP", replicate = "REPLICATE", value = "DIAMETER_MM")
  chk("F12_uppercase_unit_is_plate", stats()$unit == "replicate" && has_rep(), stats()$unit)
  # through the file observer: every unreadable file ends in a message, never an error
  for (nm in c("empty", "header_only", "binary", "no_numeric", "xlsx")) {
    session$setInputs(file = list(datapath = tmp(paste0("bad_", nm, ".csv"), bad[[nm]]), name = paste0(nm, ".csv")))
    m <- data_msg()
    chk(paste0("F10_ui_message_", nm), !is.null(m) && m$type == "error" && is.null(raw()) && nzchar(m$text) && !grepl("^Error", m$text), if (!is.null(m)) m$text else "no message")
  }
  session$setInputs(file = list(datapath = fx("../../plaque_stats/TEMPLATE.csv"), name = "TEMPLATE.csv"))
  session$setInputs(group = "group", replicate = "replicate", value = "diameter_mm")
  chk("F10_ui_template_loads_and_stats_do_not_error", !is.null(raw()) && !inherits(try(output$omni, silent = TRUE), "try-error") &&
        !inherits(try(output$sentence, silent = TRUE), "try-error"))
})

# ---- app-level checks on the example data --------------------------------------------------------
example <- read_plaque_table(file.path(fixtures, "..", "..", "plaque_stats", "example_data_wide.csv"))$df
is_pdf <- function(f) file.exists(f) && file.size(f) > 500 && identical(readBin(f, "raw", 5), charToRaw("%PDF-"))
# smallest alpha value of an 8-bit RGB / RGBA PNG (the png package is not required): 255 = opaque
png_min_alpha <- function(f) {
  b <- readBin(f, "raw", file.size(f)); ct <- as.integer(b[26]); w <- readBin(b[17:20], "integer", 1, 4, endian = "big")
  h <- readBin(b[21:24], "integer", 1, 4, endian = "big")
  if (ct == 2L) return(255L)
  stopifnot(ct == 6L, as.integer(b[25]) == 8L)
  pos <- 9L; idat <- list()
  while (pos < length(b)) {
    len <- readBin(b[pos:(pos + 3L)], "integer", 1, 4, endian = "big"); typ <- rawToChar(b[(pos + 4L):(pos + 7L)])
    if (typ == "IDAT") idat[[length(idat) + 1L]] <- b[(pos + 8L):(pos + 7L + len)]
    pos <- pos + 12L + len
  }
  z <- as.integer(memDecompress(do.call(c, idat), "gzip", asChar = FALSE)); stride <- w * 4L
  prev <- integer(stride); amin <- 255L
  for (r in seq_len(h)) {
    o <- (r - 1L) * (stride + 1L); ft <- z[o + 1L]; cur <- z[o + 1L + seq_len(stride)]
    if (ft == 1L) { for (i in 5:stride) cur[i] <- (cur[i] + cur[i - 4L]) %% 256L }
    else if (ft == 2L) cur <- (cur + prev) %% 256L
    else if (ft == 3L) { for (i in seq_len(stride)) cur[i] <- (cur[i] + (prev[i] + (if (i > 4L) cur[i - 4L] else 0L)) %/% 2L) %% 256L }
    else if (ft == 4L) { for (i in seq_len(stride)) { a <- if (i > 4L) cur[i - 4L] else 0L; bb <- prev[i]; c <- if (i > 4L) prev[i - 4L] else 0L
      pp <- a + bb - c; pa <- abs(pp - a); pb <- abs(pp - bb); pc <- abs(pp - c)
      pr <- if (pa <= pb && pa <= pc) a else if (pb <= pc) bb else c; cur[i] <- (cur[i] + pr) %% 256L } }
    amin <- min(amin, cur[seq(4L, stride, 4L)]); prev <- cur
  }
  amin
}
svg_text <- function(f) paste(readLines(f, warn = FALSE), collapse = "\n")
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults)
  # ---- F4: PDF and key downloads in every offered font and a custom one ------------------------
  for (fam in list(c("Arial", ""), c("Helvetica", ""), c("Times New Roman", ""), c("serif", ""), c("sans", ""),
                   c("custom", "Georgia"), c("custom", "No Such Font XYZ"))) {
    session$setInputs(font_family = fam[1], font_family_custom = fam[2])
    nm <- paste(fam, collapse = "/")
    f <- tryCatch(output$dl_pdf, error = function(e) conditionMessage(e))
    chk(paste0("F4_pdf_", nm), is.character(f) && is_pdf(f), if (is.character(f) && !file.exists(f)) f else "")
    z <- tryCatch(output$dl_key, error = function(e) conditionMessage(e))
    ok <- is.character(z) && file.exists(z) && file.size(z) > 500
    if (ok) { td <- tempfile(); dir.create(td); utils::unzip(z, exdir = td); fl <- list.files(td)
      ok <- all(c("violin_diameter_mm_legend_key.png", "violin_diameter_mm_legend_key.svg", "violin_diameter_mm_legend_key.pdf",
                  "violin_diameter_mm_legend_text.txt") %in% fl) && is_pdf(file.path(td, "violin_diameter_mm_legend_key.pdf")) }
    chk(paste0("F4_key_zip_", nm), ok, if (is.character(z) && !file.exists(z)) z else "")
  }
  session$setInputs(font_family = "sans", font_family_custom = "")
  # no cairo: the base-font fallback still gives a valid PDF
  options(plaque_stats.no_cairo_pdf = TRUE)
  session$setInputs(font_family = "Times New Roman")
  f <- output$dl_pdf; chk("F4_pdf_without_cairo_fallback", is_pdf(f))
  session$setInputs(font_family = "custom", font_family_custom = "Georgia")
  f <- output$dl_pdf; chk("F4_pdf_without_cairo_custom_font", is_pdf(f))
  options(plaque_stats.no_cairo_pdf = NULL); session$setInputs(font_family = "sans", font_family_custom = "")

  # ---- F20: dpi and empty-key validation -------------------------------------------------------
  for (v in list(NA, 0, -5, 1e6, "abc")) {
    session$setInputs(dpi = v)
    f <- tryCatch(output$dl_png, error = function(e) conditionMessage(e))
    chk(paste0("F20_dpi_", format(v)), is.character(f) && file.exists(f) && file.size(f) > 500, as.character(f)[1])
  }
  session$setInputs(dpi = 300)
  # a key that is empty (no replicate, neutral violins, no points): the download says why
  session$setInputs(replicate = "(none)", vfill = "neutral", show_points = FALSE)
  chk("F20_empty_key_is_empty", nrow(key()) == 0)
  chk("F20_empty_key_hides_download_button", identical(has_key(), FALSE) && identical(has_figure(), TRUE))
  session$setInputs(replicate = "replicate", vfill = "auto", show_points = TRUE)
  # a palette typed key by key never raises
  ok <- TRUE
  for (i in seq_len(nchar("#D55E00,#0072B2,x,#009E73"))) {
    session$setInputs(palette = substr("#D55E00,#0072B2,x,#009E73", 1, i))
    r <- tryCatch({ build_plot(); key(); text_starter(key()); TRUE }, error = function(e) conditionMessage(e))
    if (!isTRUE(r)) { ok <- FALSE; cat("   palette prefix", i, "->", r, "\n") }
  }
  chk("F20_palette_typed_never_errors", ok)
  session$setInputs(palette = "#12, nope"); session$flushReact()
  chk("F20_palette_invalid_friendly_message", is.character(tryCatch(build_plot(), error = function(e) NULL)) == FALSE &&
        length(parse_palette("#12, nope")$rejected) == 2 && grepl("Not a colour", {
          p <- parse_palette("#12, nope"); sprintf("Not a colour, left out: %s", paste(p$rejected, collapse = ","))}))
  session$setInputs(palette = "")
})

# ---- F6 F7 F8 F16 F17 F21 F13 F23: the figure --------------------------------------------------
layers_of <- function(g, cls) Filter(function(l) inherits(l$geom, cls), g$layers)
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults)
  g <- build_main()
  # F6: the centre line is a segment with a visible width, in the SVG too
  seg <- layers_of(g, "GeomSegment")
  chk("F6_centre_layer_is_segment", length(seg) >= 2)
  f <- file.path(out_dir, "default.svg"); set.seed(1)
  ggsave(f, build_plot(), width = 8, height = 5.2, device = svglite::svglite)
  s <- svg_text(f)
  chk("F6_centre_lines_in_svg_have_width", {
    ln <- regmatches(s, gregexpr("<line [^>]*>", s))[[1]]; ln <- ln[grepl("12211D", ln, ignore.case = TRUE)]
    w <- as.numeric(sub(".*stroke-width: ([0-9.]+).*", "\\1", ln)); length(ln) >= 3 && all(w > 0.3)
  })
  # PNG: centre line pixels (dark, 70% wide) exist where the mean sits
  fp <- file.path(out_dir, "default.png"); ggsave(fp, build_plot(), width = 8, height = 5.2, dpi = 40, bg = "white")
  # F16: opaque PNG with the key placed
  chk("F16_png_opaque_with_key", png_min_alpha(fp) == 255L, paste("min alpha", png_min_alpha(fp)))
  fd <- output$dl_png; chk("F16_png_download_opaque", png_min_alpha(fd) == 255L)
  # F7: the brackets start above the tallest drawn element
  br <- brackets(); d <- dat(); top <- max(d$value)
  chk("F7_brackets_above_all_plaques", !is.null(br$pairs) && min(br$pairs$y) > top,
      sprintf("lowest bracket %.2f, tallest plaque %.2f", min(br$pairs$y), top))
  b <- ggplot2::ggplot_build(g)
  chk("F7_n_labels_clear_of_brackets", br$top > max(br$pairs$ylab))
  # F8: without plates every sample's points carry the sample colour, and the key lists them
  session$setInputs(replicate = "(none)")
  b <- ggplot2::ggplot_build(build_main())
  pts <- Filter(function(l) "colour" %in% names(l) && any(l$size == 1.5), b$data)
  cols <- toupper(unique(unlist(lapply(pts, function(l) l$colour))))
  chk("F8_points_in_sample_colours", length(cols) == 3 && setequal(cols, toupper(unname(style()$gcol))), paste(cols, collapse = " "))
  e <- key()
  chk("F8_key_lists_points", nrow(e) == 3 && all(e$extra | e$kind == "point") && grepl("filled circles", text_starter(e)), text_starter(e))
  session$setInputs(vfill = "neutral")
  e <- key(); chk("F8_neutral_violins_key_still_lists_samples", nrow(e) == 3 && all(e$kind == "point"), paste(e$kind, collapse = ","))
  session$setInputs(replicate = "replicate", vfill = "auto")
  # F21: log axis and values <= 0
  d0 <- tidy(tmp("neg.csv", mk(",", groups = c("WT", "mutA"))), "diameter_mm"); d0$value[d0$group == "WT"] <- d0$value[d0$group == "WT"] - 2.2
  raw(data.frame(group = as.character(d0$group), replicate = d0$replicate, diameter_mm = d0$value, stringsAsFactors = FALSE))
  session$setInputs(log_y = TRUE)
  ld <- log_dropped()
  # CT-R3 F3 re-pin: the note is now the Python engine's sentence ("N values \u2264 0 are not shown on the log axis: ...")
  chk("F21_log_drop_counted", !is.null(ld) && ld$n > 0 && grepl("values? \u2264 0 (is|are) not shown on the log axis", ld$caption), if (!is.null(ld)) ld$caption else "none")
  chk("F21_log_drop_on_figure_and_notes", any(grepl("not shown on the log axis", figure_notes())) && grepl("not shown on the log axis", build_main()$labels$caption %||% ""))
  session$setInputs(log_y = FALSE); raw(example)
  # F13: one plottable group still draws, with a note
  session$setInputs(order = "T7, bogus")
  chk("F13_one_group_draws", !inherits(try(ggplot2::ggplot_build(build_plot()), silent = TRUE), "try-error") &&
        any(grepl("nothing to compare", figure_notes())) && any(grepl("bogus", figure_notes())), paste(figure_notes(), collapse = " | "))
  session$setInputs(order = "t4,t7,LAMBDA")
  chk("F13_order_case_insensitive", identical(levels(dat()$group), c("T4", "T7", "lambda")), paste(levels(dat()$group), collapse = ","))
  session$setInputs(order = "")
  # F23: base size reaches n labels and stars; jitter seeded
  sz <- function(bs) { session$setInputs(base_size = bs); g <- build_main()
    unlist(lapply(layers_of(g, "GeomText"), function(l) l$aes_params$size)) }
  # CT-R3 F7 re-pin: the n label is now fitted to the room each sample gets (full wording, shrinking, then the
  # compact one), so it follows the base size linearly while it fits (7 -> 14 pt) and is never smaller when
  # the base size doubles again; the stars still scale linearly
  chk("F23_text_size_follows_base", {a <- sz(7); b <- sz(14); cc <- sz(28); all(b / a > 1.9) && all(cc / b > 1.2) && length(a) >= 2},
      paste(sz(14), collapse = ","))
  session$setInputs(base_size = 14)
  j1 <- ggplot2::ggplot_build(build_main())$data; j2 <- ggplot2::ggplot_build(build_main())$data
  set.seed(99); j3 <- ggplot2::ggplot_build(build_main())$data
  pts <- function(b) Filter(function(l) "x" %in% names(l) && nrow(l) == nrow(dat()), b)
  chk("F23_jitter_seeded", identical(pts(j1)[[1]]$x, pts(j3)[[1]]$x) && identical(pts(j1)[[1]]$x, pts(j2)[[1]]$x))
})

# ---- F5 F19: the sentence and the statistics CSV -----------------------------------------------
testServer(app, {
  raw(read_plaque_table(fx("ct_r1_D_two_12v14.csv"))$df); do.call(session$setInputs, ui_defaults)
  s <- output$sentence
  # python: "diameter_mm in WT was 2.00 ± 0.05 (mean ± SEM of 12 plate means; 178 plaques) vs mut 2.21 ± 0.04 (14 plates; 212 plaques); Welch t-test on plate means, p = 0.004, Cohen's d = -1.33."
  chk("F5_sentence_plate_means_sem", grepl("2.00 ± 0.05 (mean ± SEM of 12 plate means; 178 plaques)", s, fixed = TRUE) &&
        grepl("mut 2.21 ± 0.04 (14 plates; 212 plaques)", s, fixed = TRUE) && grepl("Welch t-test on plate means, p = 0.004", s, fixed = TRUE), s)
  chk("F5_sentence_cohens_d", grepl("Cohen's d = -1.33", s, fixed = TRUE), s)
  session$setInputs(unit = "plaque")
  s2 <- output$sentence
  chk("F5_plaque_unit_not_called_plate_unit", !grepl("the plate is the experimental unit", s2) && grepl("n=178", s2), s2)
  session$setInputs(unit = "auto")
  raw(example); session$setInputs(value = "diameter_mm")
  s3 <- output$sentence
  chk("F5_three_groups_names_posthoc_and_p", grepl("p < 0.001", s3) && grepl("Tukey HSD", s3) && !grepl("0\\.000", s3), s3)
  chk("F5_omnibus_p_format", grepl("Tukey HSD: |one-way ANOVA: p < 0.001", output$omni) && !grepl("p = <|0\\.000", output$omni), output$omni)
  chk("F5_three_group_sentence_plate_means", grepl("mean \u00b1 SEM of plate means", s3, fixed = FALSE) && grepl("T4 2.59 \u00b1 ", s3) &&
        grepl("3 plates; 70 plaques", s3) && !grepl("p = <", s3), s3)
  # one group: no "1 groups ... n/a"
  session$setInputs(order = "T7")
  chk("F5_one_group_sentence", grepl("only one sample", output$sentence) && !grepl("n/a p", output$sentence), output$sentence)
  session$setInputs(order = "")
  # statistics CSV
  f <- output$dl_stats; txt <- paste(readLines(f, warn = FALSE), collapse = "\n")
  chk("F19_stats_csv_has_pairwise_and_omnibus", file.exists(f) && grepl("Omnibus", txt) && grepl('"T4","T7"', txt, fixed = TRUE) && grepl("Pairwise", txt))
  chk("F19_stats_csv_unrounded_p", grepl("e-06|6\\.5", txt))
  dt <- pairwise_table(); chk("F19_pairwise_table_columns", all(c("group1", "group2", "p_adj", "signif") %in% names(dt)))
})
# ---- F14 F15 F18: paper style, colours ----------------------------------------------------------
sty <- function(name, settings) { f <- file.path(out_dir, name)
  writeLines(jsonlite::toJSON(list(kind = "paper_style", app = "CFU Plot Studio", created_at = "2026-11-09", settings = settings), auto_unbox = TRUE), f); f }
Sys.setenv(CFU_PAPER_STYLE = sty("extreme.json", list(font_family = "Times New Roman", font_size = 200, axis_line_width = 50,
  axis_color = "notacolour", plot_title = "x", legend_position = "right",
  sample_palette = list(T4 = "red", T7 = "#12", lambda = "#00FF00AA", Other = "#123456"))))
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  ap <- paper_style_applied()
  chk("F14_font_size_clamped", identical(as.numeric(ap$inputs$base_size), 40), as.character(ap$inputs$base_size))
  chk("F14_axis_width_clamped", identical(as.numeric(ap$inputs$axis_line_width), 5), as.character(ap$inputs$axis_line_width))
  do.call(session$setInputs, ap$inputs)
  chk("F14_look_clamps_typed_values", { session$setInputs(base_size = 120, axis_line_width = 12); lk <- look()
    lk$base_size == 40 && lk$axis_line_width == 5 && length(lk$notes) == 2 }, paste(look()$notes, collapse = " "))
  session$setInputs(base_size = 14, axis_line_width = 0.6)
  st <- output$paper_style_status
  chk("F14_status_lists_applied", grepl("Applied: ", st) && grepl("font Times New Roman", st) && grepl("base font size 40", st), st)
  chk("F14_status_lists_ignored", grepl("axis_color 'notacolour' is not a colour", st) && grepl("'T7' \\('#12'\\) is not a colour", st) &&
        grepl("plot_title", st) && grepl("legend_position", st) && grepl("font_size 200 is outside", st), st)
  chk("F14_status_names_samples_matched", grepl("Sample colours: 2 of the style's 3 names are in this data", st) , st)
})
Sys.setenv(CFU_PAPER_STYLE = sty("other.json", list(sample_palette = list(MG1655 = "#000000", "MG1655 + WT" = "#E69F00"))))
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  chk("F15_style_naming_no_sample_colours_nothing", !style()$neutral == FALSE && style()$neutral, "violins should stay grey")
  chk("F15_status_says_none_match", grepl("None of the style's 2 sample names", output$paper_style_status), output$paper_style_status)
})
Sys.setenv(CFU_PAPER_STYLE = sty("t4black.json", list(sample_palette = list(T4 = "#000000", T7 = "#D55E00", lambda = "#0072B2"))))
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  chk("F15_style_colours_applied_by_name", identical(unname(style()$gcol["T4"]), "#000000") && !style()$neutral)
  session$setInputs(palette_name = "set2"); session$flushReact()
  chk("F15_theme_replaces_colours", !identical(unname(style()$gcol["T4"]), "#000000"))
  chk("F15_status_says_theme_replaced", grepl("Colour theme Set2 replaced the paper style's sample colours \\(choose 'Paper style' to bring them back\\)", output$paper_style_status) &&
        !grepl("of the style's", output$paper_style_status), output$paper_style_status)
  session$setInputs(palette_name = "paper"); session$flushReact()
  chk("F15_paper_style_choice_brings_it_back", identical(unname(style()$gcol["T4"]), "#000000") && identical(unname(style()$gcol["T7"]), "#D55E00"))
  session$setInputs(palette_name = "okabe"); session$flushReact(); session$setInputs(palette_name = "paper"); session$flushReact()
  chk("F15_round_trip_twice", identical(unname(style()$gcol["T4"]), "#000000"))
})
Sys.setenv(CFU_PAPER_STYLE = file.path(out_dir, "no_paper_style.json"))
# F18: distinct colours
reg <- extend_colour_registry(setNames(character(0), character(0)), paste0("s", 1:9))
cols <- registry_colours(reg, c("s1", "s2")); chk("F18_two_samples_never_share", length(unique(cols)) == 2)
reg <- c(a = "#0072B2", b = "#0072B2"); cc <- registry_colours(reg, c("a", "b"))
chk("F18_same_style_colour_told_apart", to_hex(cc[1]) != to_hex(cc[2]) && identical(attr(cc, "changed"), "b"))
reg <- extend_colour_registry(setNames(OKABE_ITO[1:9], paste0("o", 1:9)), c("o1", "extra1", "extra2"))
chk("F18_new_name_after_full_pool_is_a_new_colour", length(unique(toupper(reg))) == length(reg), paste(tail(reg, 2), collapse = " "))
many <- tidy(tmp("many.csv", mk(",", groups = c("WT", "mut"), plates = 24, n = 6)))
many2 <- many; many2$replicate <- sub("plate", "plate ", many2$replicate)
testServer(app, {
  raw(data.frame(group = as.character(many$group), replicate = many$replicate, diameter_mm = many$value, stringsAsFactors = FALSE))
  do.call(session$setInputs, ui_defaults); session$flushReact()
  e <- key(); pl <- e[e$section == "plate", ]
  pair <- paste(pl$colour, pl$shape)
  chk("F18_24_plates_unique_colour_shape_pairs", nrow(pl) == 24 && !anyDuplicated(pair), sprintf("%d rows, %d distinct", nrow(pl), length(unique(pair))))
  chk("F18_more_than_9_plates_cycle_shapes", length(unique(pl$shape)) >= 3)
  chk("F18_plate_palette_distinct_from_samples_when_coloured", {
    session$setInputs(vfill = "group"); session$flushReact(); sm <- style()
    colour_distance(unname(sm$rcol)[1], unname(sm$gcol)) > 18 }, "")
  tx <- text_starter(key()); chk("F18_text_starter_has_every_plate_once", sum(grepl("plate1 \\(|plate1[0-9]* \\(", tx)) >= 1 && nchar(tx) > 100)
  session$setInputs(vfill = "auto")
  # CT-R3 F7 re-pin: under grey violins the plates take the chosen palette (Okabe-Ito), as the Python engine
  chk("F18_default_grey_view_uses_the_chosen_palette", identical(unname(style()$rcol[1:2]), OKABE_ITO[1:2]))
  g <- build_plot(); ok <- !inherits(try(ggplot2::ggplot_build(g), silent = TRUE), "try-error"); chk("F18_many_plates_draws", ok)
})

# ---- F4 (note) -----------------------------------------------------------------------------------
tf <- tempfile(fileext = ".pdf")
n1 <- save_pdf(tf, function(fam) ggplot2::ggplot(data.frame(x = 1, y = 1), ggplot2::aes(x, y)) + ggplot2::geom_point(), "Georgia", 4, 3)
n0 <- save_pdf(tf, function(fam) ggplot2::ggplot(data.frame(x = 1, y = 1), ggplot2::aes(x, y)) + ggplot2::geom_point(), "", 4, 3)
if (!cairo_pdf_usable()) {
  chk("F4_substituted_font_note", is.character(n1) && grepl("font substituted", n1) && grepl("Georgia", n1), n1)
  chk("F4_default_font_no_note", is.null(n0))
} else chk("F4_cairo_embeds_any_font", is.null(n1) && is.null(n0))

# ---- F17: the key rows never print on top of each other ------------------------------------------
many12 <- tidy(tmp("many12.csv", mk(",", groups = paste0("Strain ", sprintf("%02d", 1:12), " long name"), plates = 3, n = 6)))
m12 <- data.frame(group = as.character(many12$group), replicate = many12$replicate, diameter_mm = many12$value, stringsAsFactors = FALSE)
testServer(app, {
  raw(m12); do.call(session$setInputs, modifyList(ui_defaults, list(vfill = "group"))); session$flushReact()
  e <- key()
  for (bs in c(10, 14, 24, 40)) {
    geo <- key_geometry(e, bs); rows <- geo$rows
    text_in <- bs * 0.8 * 1.2 / 72                       # one text line, in inches
    ok_pitch <- geo$pitch >= text_in
    ok_cols <- max(table(rows$col)) <= KEY_ROWS_PER_COL + 1
    ok_unique <- !anyDuplicated(paste(rows$col, rows$pos))
    chk(paste0("F17_key_rows_clear_base", bs), ok_pitch && ok_cols && ok_unique,
        sprintf("pitch %.2f in vs line %.2f in, %d columns, max %d rows", geo$pitch, text_in, max(rows$col), max(table(rows$col))))
  }
  kp <- key_place(); chk("F17_12_samples_key_placed_or_said", kp$where %in% c("beside", "below") || (kp$where == "none" && nzchar(kp$note %||% "")), kp$where)
  session$setInputs(base_size = 40); kp <- key_place()
  chk("F17_base40_key_never_squeezed", kp$where != "none" || grepl("not placed on the figure", kp$note), kp$where)
  ok <- !inherits(try(ggplot2::ggplot_build(build_plot()), silent = TRUE), "try-error"); chk("F17_base40_draws", ok)
  session$setInputs(base_size = 14, height = 12); kp <- key_place()
  chk("F17_preview_size_follows_figure_size", identical(fig_size()$h, 12))
})
raw_ui <- as.character(ui)
chk("F22_text_boxes_multiline_with_copy", grepl("<textarea[^>]*id=\"sentence_box\"", raw_ui) && grepl("<textarea[^>]*id=\"key_text_box\"", raw_ui) &&
      length(gregexpr("writeText", raw_ui)[[1]]) >= 2)
chk("F22_tables_scroll_in_own_box", grepl("overflow-x: auto", raw_ui) && isTRUE(dt_opts_probe <- TRUE))
chk("F5_download_statistics_button", grepl("dl_stats", raw_ui) && grepl("Download statistics \\(CSV\\)", raw_ui))
chk("F1_variances_select", grepl('id="equal_var"', raw_ui) && grepl("Welch ANOVA", raw_ui))
chk("F6_annotate_select", grepl('id="annotate"', raw_ui) && grepl("all pairs", raw_ui))
bat <- readLines(file.path("..", "plaque_stats", "Run R App.bat"), warn = FALSE)
chk("F24_bat_install_line_has_jsonlite", any(grepl("install.packages", bat) & grepl("jsonlite", bat)))

# =================================================================================================
# CT-R2 (round 2) -- checks named R2_*. Python numbers below were produced by plaque_stats.py.
# =================================================================================================
# ---- N1: a sample with zero variance: Welch is undefined -> classic ANOVA + Tukey, as Python -------
stZ <- plaque_run_stats(tidy(fx("ct_r2_zerovar.csv")))
chk("R2_N1_zerovar_falls_back_to_anova_tukey", stZ$test == "one-way ANOVA" && stZ$posthoc == "Tukey HSD" &&
      near(stZ$p, 3.321225932616643e-10, 1e-14) && !is.na(stZ$p), paste(stZ$test, stZ$p))
chk("R2_N1_zerovar_pairwise_p", near(unname(pw_p(stZ)), c(1.3558213241005035e-07, 2.2230062235450987e-10, 3.0756279285615307e-06), 3e-9),
    paste(sprintf("%.6g", pw_p(stZ)), collapse = " "))
chk("R2_N1_zerovar_note_and_spread_warning", any(grepl("^Welch's ANOVA could not be computed \\(a sample has zero variance\\); classic ANOVA \\+ Tukey HSD were used instead\\.$", stZ$notes)) &&
      any(grepl("SD ratio Inf, adjusted p < 0.001", stZ$warnings)), paste(stZ$notes, stZ$warnings, collapse = " | "))
stZn <- plaque_run_stats(tidy(fx("ct_r2_zerovar.csv")), equal_var = "no")
chk("R2_N1_zerovar_forced_unequal_also_falls_back", stZn$test == "one-way ANOVA" && near(stZn$p, stZ$p, 1e-14))
chk("R2_N1_omnibus_text_has_p", grepl("one-way ANOVA: p < 0.001", omnibus_text(stZ)) && grepl("NOTES:", omnibus_text(stZ)))

# ---- N3: ties: rank the plate means rounded to 12 digits, as the pandas means are -----------------
stT <- plaque_run_stats(tidy(fx("ct_r2_ties.csv")), parametric = "nonparametric")
chk("R2_N3_ties_kruskal_p", stT$test == "Kruskal–Wallis" && near(stT$p, 0.0020555124291379706, 1e-12), sprintf("%.12g", stT$p))
chk("R2_N3_ties_dunn_p", near(unname(pw_p(stT)), c(0.001695575267088922, 0.03978406477923671, 0.26296416821519575), 1e-9),
    paste(sprintf("%.10g", pw_p(stT)), collapse = " "))
stTp <- plaque_run_stats(tidy(fx("ct_r2_ties.csv")))
chk("R2_N3_parametric_p_unchanged", near(stTp$p, 0.000721407841790418, 1e-12), sprintf("%.12g", stTp$p))

# ---- N7 + N8 + F3: reading as Python does ----------------------------------------------------------
rN <- read_plaque_table(fx("ct_r2_names2.csv"))
chk("R2_N7_no_comment_note_when_no_comments", !any(grepl("comment", rN$notes)), paste(rN$notes, collapse = "|"))
cm <- tmp("comments_head.csv", c("# validation set", "# exported 2026", "", "# third", "group,replicate,diameter_mm", "A,p1,2.1", "A,p2,2.2", "#B,p1,3.1", "#B,p2,3.3"))
rC <- read_plaque_table(cm)
chk("R2_N7_comments_only_before_header_counted", any(grepl("^3 comment lines before the header skipped$", rC$notes)) && nrow(rC$df) == 4 &&
      "#B" %in% rC$df$group, paste(rC$notes, collapse = "|"))
dN2 <- tidy_plaque_data(rN$df, "group", "replicate", "diameter_mm", NULL, "")
chk("R2_N7_NA_007_hash1_are_sample_names", identical(levels(dN2$group), c("NA", "007", "#1")) && nrow(dN2) == 72, paste(c(levels(dN2$group), nrow(dN2)), collapse = "|"))
stN2 <- plaque_run_stats(dN2)
# plaque_stats.py gives 0.00011934370062079558 (parity test: names2)
chk("R2_N7_names2_three_samples_anova", stN2$test == "one-way ANOVA" && near(stN2$p, 0.00011934370062079558, 1e-9), sprintf("%s %.12g", stN2$test, stN2$p))
nm <- tmp("names_words.csv", c("group,replicate,diameter_mm", paste0(rep(c("None", "nan", "null", "NA"), each = 4), ",p", rep(1:2, 8), ",", c(2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.4, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.4, 3.7)),
                                   ",p1,2.2"))
dW <- tidy_plaque_data(read_plaque_table(nm)$df, "group", "replicate", "diameter_mm", NULL, "")
chk("R2_N7_None_nan_null_NA_are_names_empty_is_blank", identical(levels(dW$group), c("None", "nan", "null", "NA")) &&
      any(grepl("^1 row dropped: no group label\\.$", attr(dW, "info")$notes)), paste(levels(dW$group), collapse = "|"))
rU <- read_plaque_table(fx("ct_r2_upper_missing.csv"))
dU <- tidy_plaque_data(rU$df, "GROUP", "REPLICATE", "DIAMETER_MM", NULL, "")
chk("R2_N8_not_a_number_vs_empty_wording", identical(attr(dU, "info")$notes, "7 rows dropped: no numeric DIAMETER_MM value (5 not a number, 2 empty)."),
    paste(attr(dU, "info")$notes, collapse = "|"))
stU <- plaque_run_stats(dU)
chk("R2_N8_upper_missing_same_p_as_python", stU$test == "one-way ANOVA" && near(stU$p, 0.0013102525378786152, 1e-9), sprintf("%.12g", stU$p))

# ---- rule change: normality gate at 8+ plates is Bonferroni across the tested samples ---------------
mk8 <- function(seed, k = 3) { set.seed(seed)
  d <- do.call(rbind, lapply(seq_len(k), function(i) data.frame(group = LETTERS[i], replicate = paste0("p", 1:8),
         value = if (i == 1) rexp(8) + 2 else rnorm(8, 2, 0.3))))
  d$group <- factor(d$group, levels = LETTERS[seq_len(k)]); d }
shap_a <- function(d) shapiro.test(d$value[d$group == "A"])$p.value
seed_mid <- Filter(function(sd) { p <- shap_a(mk8(sd)); p > 0.0167 && p < 0.05 &&
                    all(vapply(c("B", "C"), function(g) shapiro.test(mk8(sd)$value[mk8(sd)$group == g])$p.value > 0.05, TRUE)) }, 1:400)[1]
seed_low <- Filter(function(sd) shap_a(mk8(sd)) < 0.0167, 1:400)[1]
dm <- mk8(seed_mid); stm <- plaque_run_stats(dm)
chk("R2_gate_p_between_0.05_over_m_and_0.05_stays_parametric", is.na(seed_mid) == FALSE && isTRUE(stm$parametric_used) && stm$test %in% c("one-way ANOVA", "Welch ANOVA") &&
      any(grepl("Bonferroni over 3 samples) does not reject normality", stm$notes)), sprintf("seed %s p_A %.4f %s | %s", seed_mid, shap_a(dm), stm$test, paste(stm$notes, collapse = " ")))
dl <- mk8(seed_low); stl <- plaque_run_stats(dl)
chk("R2_gate_p_below_0.05_over_m_goes_rank_based", !is.na(seed_low) && !isTRUE(stl$parametric_used) && stl$test == "Kruskal–Wallis" &&
      any(grepl("rejects normality", stl$notes)), sprintf("seed %s p_A %.4f %s", seed_low, shap_a(dl), stl$test))

# ---- N2: key below GROWS the figure; one row of stars with > 5 samples; left margin from the names --
m12L <- m12; m12L$group <- paste(m12L$group, "dRecA::kan pBAD33 wide")
m12L$replicate <- paste0("rep", match(m12L$group, unique(m12L$group)), "-", m12L$replicate)   # a plate row per sample x plate in the key
m12L$diameter_mm <- m12L$diameter_mm + 0.15 * match(m12L$group, unique(m12L$group))   # all clearly different
testServer(app, {
  raw(m12L); do.call(session$setInputs, ui_defaults); session$flushReact()
  kp <- key_place(); fo <- fig_out(); fs <- fig_size()
  chk("R2_N2a_key_below_grows_figure_panel_keeps_size", identical(kp$where, "below") && near(fo$h, fs$h + kp$kh + KEY_GAP_IN, 1e-9) &&
        fo$w == fs$w && fs$h == 5.2, sprintf("%s %.2f -> %.2f", kp$where, fs$h, fo$h))
  chk("R2_N2a_note_says_figure_is_taller", grepl("figure is [0-9.]+ in tall instead of 5.2 in", kp$note %||% ""), kp$note %||% "")
  chk("R2_N2a_download_uses_grown_size", identical(fig_out()$h, fo$h))
  br <- brackets()
  chk("R2_N2b_many_samples_one_row_of_stars", is.null(br$pairs) && nrow(br$stars) == 12 && br$stars$label[1] == "ref." &&
        length(unique(br$stars$y)) == 1 && all(br$stars$label[-1] %in% c("ns", "*", "**", "***", "n/a")), paste(br$stars$label, collapse = " "))
  chk("R2_N2b_caption_and_sentence", identical(br$caption, "Stars above each sample: its comparison with Strain 01 long name dRecA::kan pBAD33 wide (ref.)") &&
        grepl("^With 12 samples each sample is compared with Strain 01 long name dRecA::kan pBAD33 wide only: the stars above each sample give that comparison \\([0-9]+ of 11 with adjusted p < 0.05; Strain 01 long name dRecA::kan pBAD33 wide itself is marked ref\\.\\)\\. Every pair is in the pairwise table\\. Stars: \\* p < 0.05", br$sentence),
      br$sentence)
  chk("R2_N2b_legend_text_carries_annotation_sentence", grepl("compared with Strain 01 long name dRecA", annotation_text()) &&
        grepl("compared with Strain 01 long name dRecA", output$key_text))
  chk("R2_N2b_figure_draws_without_brackets", !inherits(try(ggplot2::ggplot_build(build_plot()), silent = TRUE), "try-error"))
  session$setInputs(annotate = "all"); br <- brackets()
  chk("R2_N2b_all_pairs_still_gives_brackets", !is.null(br$pairs) && is.null(br$stars) && nrow(br$pairs) == 66)
  session$setInputs(annotate = "auto")
})
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  br <- brackets()
  chk("R2_N2b_three_samples_keep_brackets_and_size", !is.null(br$pairs) && is.null(br$stars) && key_place()$where == "beside" &&
        identical(fig_out()$h, 5.2))
})
chk("R2_N2c_left_margin_grows_with_name_length", tilted_left_margin_pt(rep("x", 9), 14, 8) == 6 &&
      tilted_left_margin_pt(paste("Strain", 1:12, "long name pBAD33 delta recA"), 14, 8) > 60 &&
      tilted_left_margin_pt(paste("Strain", 1:12, "long name pBAD33 delta recA"), 28, 8) >
        tilted_left_margin_pt(paste("Strain", 1:12, "long name pBAD33 delta recA"), 14, 8))

# ---- N4 + N5: one colour rule ---------------------------------------------------------------------
Sys.setenv(CFU_PAPER_STYLE = sty("t4black2.json", list(sample_palette = list(T4 = "#000000", T7 = "#D55E00", lambda = "#0072B2"))))
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  session$setInputs(palette_name = "paper"); session$flushReact()
  chk("R2_N4_status_before_theme_names_style", grepl("3 of the style's 3 names", output$paper_style_status))
  session$setInputs(palette_name = "cool"); session$flushReact()
  chk("R2_N4_theme_after_style_replaces_and_status_says_so", !identical(unname(style()$gcol["T4"]), "#000000") &&
        grepl("Colour theme Cool replaced the paper style's sample colours \\(choose 'Paper style' to bring them back\\)\\.", output$paper_style_status) &&
        !grepl("3 of the style's", output$paper_style_status), output$paper_style_status)
  session$setInputs(palette_name = ""); session$flushReact()
  chk("R2_N4_custom_hex_replaces_too", grepl("Colour theme \\(custom hex below\\) replaced", output$paper_style_status), output$paper_style_status)
  session$setInputs(palette_name = "cool"); session$flushReact(); session$setInputs(palette_name = "paper"); session$flushReact()
  chk("R2_N4_paper_choice_still_brings_style_back", identical(unname(style()$gcol[["T4"]]), "#000000") && identical(unname(style()$gcol[["lambda"]]), "#0072B2"))
})
Sys.setenv(CFU_PAPER_STYLE = file.path(out_dir, "no_paper_style.json"))
# N5: the web tester's t2 sequence: type a palette, set an order, clear both, rename ONE sample
testServer(app, {
  raw(example); do.call(session$setInputs, modifyList(ui_defaults, list(vfill = "group"))); session$flushReact()
  base_cols <- style()$gcol
  session$setInputs(palette = "#000000,#D55E00,#0072B2"); session$flushReact()
  chk("R2_N5_typed_palette_applies", identical(unname(style()$gcol), c("#000000", "#D55E00", "#0072B2")))
  session$setInputs(order = "lambda,T7,T4"); session$flushReact()
  session$setInputs(palette = ""); session$flushReact(); session$setInputs(order = ""); session$flushReact()
  chk("R2_N5_clearing_palette_restores_colours_from_before", identical(style()$gcol, base_cols),
      paste(style()$gcol, collapse = " "))
  ren <- example; ren$group[ren$group == "T4"] <- "T4 renamed (new)"
  raw(ren); session$flushReact()
  g <- style()$gcol
  chk("R2_N5_unrenamed_samples_keep_their_colour", identical(unname(g[["T7"]]), unname(base_cols[["T7"]])) &&
        identical(unname(g[["lambda"]]), unname(base_cols[["lambda"]])) && !anyDuplicated(g), paste(names(g), g, collapse = " "))
})

# ---- N6 + N9 (R parts) ------------------------------------------------------------------------------
# the user's own choice is a NOTE, Levene's finding a WARNING; every p goes through p_eq
set.seed(5)
dU <- do.call(rbind, lapply(list(c("a", 1), c("b", 0.01), c("c", 0.01)), function(x) data.frame(group = x[1],
        replicate = paste0("p", 1:10), value = rnorm(10, 2, as.numeric(x[2])))))
dU$group <- factor(dU$group, levels = c("a", "b", "c"))
stU <- plaque_run_stats(dU)
chk("R2_N6_levene_warning_uses_p_eq", any(grepl("^Levene p < 0.001: group variances differ", stU$warnings)) && !any(grepl("0\\.000", c(stU$warnings, stU$notes))),
    paste(stU$warnings, collapse = " | "))
stUn <- plaque_run_stats(dU[dU$group != "c", ], equal_var = "no")
stUn3 <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "no")
chk("R2_N6_users_variance_choice_is_a_note_not_a_warning", any(grepl("^Variances were set to 'unequal'", stUn3$notes)) &&
      !any(grepl("Variances were set", stUn3$warnings)) && grepl("NOTES:\n- Variances were set to 'unequal'", omnibus_text(stUn3)) &&
      !grepl("WARNINGS:[^N]*Variances were set", omnibus_text(stUn3)))
stY <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "yes")
stY$levene_p <- 1e-5
chk("R2_N6_p_eq_never_p_equals_0.000", p_eq(0.0004) == "p < 0.001" && p_eq(0.01234) == "p = 0.012" && !grepl("= 0\\.000", omnibus_text(stU)))
# spread note: only samples that can be tested count; singular / plural
sp1 <- spread_check(list(a = c(1, 2.1, 3.3, 4.2, 5.1), b = c(2, 2.5, 3.1, 3.9, 4.4), c = 5), "plates")
chk("R2_N9_spread_note_ignores_untestable_sample", is.null(sp1$note), sp1$note %||% "")
sp2 <- spread_check(list(a = c(1, 2.1, 3.3), b = c(2, 2.5, 3.1), c = 5), "plates")
chk("R2_N9_spread_note_counts_testable_plates", grepl("With 3 plates per group", sp2$note), sp2$note %||% "")
# the copy boxes: the textarea and the output have DIFFERENT ids, no shared input/output id
ids_in <- regmatches(raw_ui, gregexpr("<textarea[^>]*id=\"[^\"]+\"", raw_ui))[[1]]
ids_in <- sub(".*id=\"([^\"]+)\"", "\\1", ids_in)
ids_out <- sub(".*id=\"([^\"]+)\".*", "\\1", regmatches(raw_ui, gregexpr("<[a-z]+ id=\"[^\"]+\" class=\"shiny-text-output\"", raw_ui))[[1]])
chk("R2_N9_no_shared_input_output_ids", length(ids_in) >= 2 && all(c("key_text", "sentence") %in% ids_out) && !length(intersect(ids_in, ids_out)),
    paste(c(ids_in, "|", ids_out), collapse = " "))
# rejected colours are named in the status under the palette box (after typing settles)
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$setInputs(palette = "#12, nope"); session$flushReact()
  session$elapse(1000)
  chk("R2_N9_rejected_colours_named", grepl("Not a colour, left out: '#12', 'nope'\\.", output$palette_status), output$palette_status)
})
# repeated notices of one kind replace each other
chk("R2_N9_notify_takes_an_id", "id" %in% names(formals(shiny::showNotification)))
src_app <- readLines("app.R", warn = FALSE)
chk("R2_N9_pdf_font_notice_has_a_fixed_id", any(grepl('notify\\(note, id = "pdf_font_note"\\)', src_app)))
chk("R2_N9_no_favicon_404", grepl('rel="icon"', htmltools::renderTags(ui)$head, fixed = TRUE) &&
      grepl('href="data:,"', htmltools::renderTags(ui)$head, fixed = TRUE))

# N2: a tilted-name figure whose names leave less than 1.5 in for the plot says so
testServer(app, {
  caps <- paste(c("ESCHERICHIA PHAGE T4 WILD TYPE", "BACILLUS PHAGE SPP1 MUTANT", "ENTEROBACTERIA PHAGE LAMBDA CI857", "WWWW MMMM WWWW MMMM WWWW"), "X")
  dc <- do.call(rbind, lapply(seq_along(caps), function(i) data.frame(group = caps[i], replicate = rep(paste0("p", 1:3), each = 4),
                                                                      diameter_mm = rnorm(12, 2 + 0.3 * i, 0.1))))
  raw(dc); do.call(session$setInputs, modifyList(ui_defaults, list(base_size = 24))); session$flushReact()
  chk("R2_N2_long_names_at_large_font_say_the_panel_is_small", any(grepl("sample names are long for this font size", figure_notes())), paste(figure_notes(), collapse = " | "))
  raw(example); session$setInputs(base_size = 14); session$flushReact()
  chk("R2_N2_no_such_note_for_the_shipped_example", !any(grepl("sample names are long", figure_notes())))
})
chk("R2_N2c_capitals_are_wider_than_lowercase", name_width_in("WWWWWWWW", 14) > 1.3 * name_width_in("wwwwwwww", 14))

# ---- final pass: the merged Python wording ---------------------------------------------------------
stG <- plaque_run_stats(tidy(fx("ct_r2_gate_between.csv")))
chk("R2_final_gate_sentence_does_not_reject", stG$parametric_used && stG$test == "Welch ANOVA" &&
      any(grepl("^Every sample has at least 8 plates and Shapiro–Wilk \\(Bonferroni over 3 samples\\) does not reject normality \\(smallest p = 0\\.048, threshold 0\\.05/3 = 0\\.0167\\), so a parametric test is used\\.", stG$notes)),
    paste(stG$notes, collapse = " | "))
dRej <- mk8(seed_low); stRej <- plaque_run_stats(dRej)
chk("R2_final_gate_sentence_rejects", any(grepl("^With at least 8 plates per sample, Shapiro–Wilk \\(Bonferroni over 3 samples\\) rejects normality for A \\(p < 0.001\\) and C \\(p = 0\\.013\\) \\(threshold 0\\.05/3 = 0\\.0167\\), so a rank-based test is used\\.", stRej$notes)),
    paste(stRej$notes, collapse = " | "))
stM1 <- plaque_run_stats(tidy(fx("ct_r2_mwu_5v6_noties.csv")), parametric = "nonparametric")
stM2 <- plaque_run_stats(tidy(fx("ct_r2_mwu_ties.csv")), parametric = "nonparametric")
chk("R2_final_mannwhitney_exact_without_ties_p", near(stM1$p, 0.017316017316017316, 1e-12) && stM1$p_method == "exact" &&
      identical(stM1$method_note, "Mann–Whitney U p is exact (no ties, at most 8 per side)."), sprintf("%.12g %s", stM1$p, stM1$method_note))
chk("R2_final_mannwhitney_asymptotic_with_ties_p", near(stM2$p, 0.025154152614191672, 1e-12) && stM2$p_method == "asymptotic" &&
      identical(stM2$method_note, "Mann–Whitney U p is asymptotic (normal approximation with tie and continuity correction)."), sprintf("%.12g %s", stM2$p, stM2$method_note))
chk("R2_final_kruskal_note_asymptotic", any(grepl("^Kruskal–Wallis and Dunn's p are asymptotic \\(chi-squared / normal approximation; with few values per sample they can be far from exact\\)\\.$", stT$notes)))
spz <- spread_check(list(A = c(2, 2, 2), B = c(2.1, 2.5, 2.9), C = c(3, 3.3, 3.1)), "plates")
chk("R2_final_zero_spread_advice", grepl("Welch's ANOVA is not an alternative here: A has no spread \\(identical plate-mean values\\)\\.$", spz$note), spz$note %||% "")
dSt <- tidy(fx("ct_r1_B_unequal.csv"), replicate = "(none)")
stars_sel <- pairs_to_draw(data.frame(group1 = c("a", "a", "a", "a", "a"), group2 = c("b", "c", "d", "e", "f"), p_adj = c(0.001, NA, 0.2, 0.03, 0.0001),
                                      signif = p_stars(c(0.001, NA, 0.2, 0.03, 0.0001)), stringsAsFactors = FALSE),
                           letters[1:6], "auto", "Tukey HSD")
chk("R2_final_stars_row_na_for_untestable_pair", identical(stars_sel$vsref$labels, c("ref.", "**", "n/a", "ns", "*", "***")) &&
      grepl("itself is marked ref\\.; n/a = could not be tested, fewer than 2 plates\\)", stars_sel$sentence), stars_sel$sentence %||% "")

# =================================================================================================
# ---- CT-R3 (round 3): F3 F5 F6 F7 F8 F11 of the four-front-end comparison ----------------------
# Every check is wrapped: a missing function is a FAIL line, not an aborted script.
# =================================================================================================
r3 <- function(id, expr) {
  res <- tryCatch(expr, error = function(e) paste("ERROR:", conditionMessage(e)))
  if (is.character(res) && startsWith(res, "ERROR:")) chk(id, FALSE, res)
  invisible(res)
}
# the value column of every layer that carries data frames of values (the points, violins, plate means)
r3_layer_values <- function(g) unlist(lapply(g$layers, function(l)
  if (is.data.frame(l$data) && "value" %in% names(l$data)) l$data$value))
r3_is_bar <- function(l) is.data.frame(l$data) && all(c("cen", "lo", "hi") %in% names(l$data)) &&
  (inherits(l$geom, "GeomErrorbar") || inherits(l$geom, "GeomSegment"))
r3_bar_values <- function(g) unlist(lapply(g$layers, function(l) if (r3_is_bar(l)) unlist(l$data[c("cen", "lo", "hi")])))
r3_png_dim <- function(f) { b <- readBin(f, "raw", 32); c(readBin(b[17:20], "integer", 1, 4, endian = "big"),
                                                          readBin(b[21:24], "integer", 1, 4, endian = "big")) }
R3_PY_LOG_SENTENCE <- "8 values ≤ 0 are not shown on the log axis: the plotted plate means, bar and whisker leave them out, the statistics include them"

# ---- F3: log axis: the values <= 0 are removed from every drawn layer --------------------------
testServer(app, {
  raw(read_plaque_table(fx("ct_r3_k_zeros.csv"))$df)
  do.call(session$setInputs, modifyList(ui_defaults, list(log_y = TRUE))); session$flushReact()
  r3("R3_F3_no_zero_value_in_any_drawn_layer", {
    g <- build_main(); v <- r3_layer_values(g); bars <- r3_bar_values(g)
    chk("R3_F3_no_zero_value_in_any_drawn_layer", length(v) > 100 && all(v > 0) && length(bars) > 0 && all(bars > 0),
        sprintf("%d values, min %.3g, bar min %.3g", length(v), min(v), min(bars)))
  })
  r3("R3_F3_nothing_at_the_axis_line", {
    b <- ggplot2::ggplot_build(build_main())
    g <- build_main()                     # (the n labels sit at y = Inf, the top edge, on purpose)
    ys <- unlist(lapply(seq_along(b$data), function(i) if (inherits(g$layers[[i]]$geom, "GeomText")) NULL else
      unlist(b$data[[i]][intersect(c("y", "ymin", "ymax"), names(b$data[[i]]))])))
    chk("R3_F3_nothing_at_the_axis_line", all(is.finite(ys)), sprintf("%d non-finite of %d y values", sum(!is.finite(ys)), length(ys)))
  })
  r3("R3_F3_plate_means_from_drawn_values", {
    d <- dat(); wt1 <- d$value[d$group == "WT" & d$replicate == "plate1"]
    want <- mean(wt1[wt1 > 0]); all_mean <- mean(wt1)
    got <- drawn_rm(); got <- got$value[got$group == "WT" & got$replicate == "plate1"]
    ct <- cen_tab(); pm <- drawn_rm(); w <- pm$value[pm$group == "WT"]
    chk("R3_F3_plate_means_from_drawn_values", near(got, want) && all_mean < want && near(ct$cen[ct$group == "WT"], mean(w)) && all(w > 0),
        sprintf("drawn %.4f want %.4f with the zeros %.4f", got, want, all_mean))
  })
  r3("R3_F3_statistics_and_n_use_every_value", {
    st <- stats(); d <- dat(); rmw <- st$rm$value[st$rm$group == "WT" & st$rm$replicate == "plate1"]
    wt1 <- d$value[d$group == "WT" & d$replicate == "plate1"]
    chk("R3_F3_statistics_and_n_use_every_value", near(rmw, mean(wt1)) && sum(d$group == "WT") == 74 &&
          grepl("n = 74 plaques", n_plan()$label[1], fixed = TRUE) && nrow(drawn()) == nrow(d) - 8,
        sprintf("stats plate mean %.4f; n label '%s'", rmw, gsub("\n", " / ", n_plan()$label[1])))
  })
  r3("R3_F3_note_is_the_python_sentence", {
    cap <- gsub("\n", " ", build_main()$labels$caption %||% "", fixed = TRUE)
    chk("R3_F3_note_is_the_python_sentence", any(startsWith(figure_notes(), R3_PY_LOG_SENTENCE)) && grepl(R3_PY_LOG_SENTENCE, cap, fixed = TRUE),
        paste(figure_notes(), collapse = " | "))
  })
  r3("R3_F3_violin_and_points_follow", {
    b <- ggplot2::ggplot_build(build_main()); npts <- sum(vapply(b$data, nrow, 0L)[vapply(build_main()$layers, function(l) inherits(l$geom, "GeomPoint"), TRUE)])
    chk("R3_F3_violin_and_points_follow", npts == 202 + 9, sprintf("%d points (202 plaque points + 9 plate means)", npts))
  })
})
r3("R3_F3_singular_sentence", {
  d1 <- read_plaque_table(fx("ct_r3_k_zeros.csv"))$df; d1$diameter_mm <- as.numeric(d1$diameter_mm)
  d1$diameter_mm[d1$diameter_mm <= 0] <- 1.5; d1$diameter_mm[2] <- 0
  testServer(app, {
    raw(d1); do.call(session$setInputs, modifyList(ui_defaults, list(log_y = TRUE))); session$flushReact()
    chk("R3_F3_singular_sentence", startsWith(log_dropped()$caption, "1 value ≤ 0 is not shown on the log axis: the plotted plate means, bar and whisker leave it out, the statistics include it"),
        log_dropped()$caption)
  })
})

# ---- F5: Centre = median -----------------------------------------------------------------------
# Python (plaque_stats.py --center median, example_data_wide.csv): median of ALL plaques, IQR whisker:
#   T4 2.63 (2.41-2.82), T7 1.78 (1.56-1.98), lambda 3.16 (2.96-3.38)
testServer(app, {
  raw(example); do.call(session$setInputs, modifyList(ui_defaults, list(center = "median"))); session$flushReact()
  r3("R3_F5_centre_is_the_median_of_all_plaques", {
    ct <- cen_tab(); d <- dat()
    chk("R3_F5_centre_is_the_median_of_all_plaques",
        near(ct$cen, vapply(levels(d$group), function(g) median(d$value[d$group == g]), 0)) &&
          identical(sprintf("%.2f", ct$cen), c("2.63", "1.78", "3.16")) &&
          identical(sprintf("%.2f-%.2f", ct$lo, ct$hi), c("2.41-2.82", "1.56-1.98", "2.96-3.38")),
        paste(sprintf("%.4f", ct$cen), collapse = " "))
  })
  r3("R3_F5_the_drawn_bar_is_that_median", {
    g <- build_main(); bars <- g$layers[vapply(g$layers, r3_is_bar, TRUE)]
    labs_ <- g$layers[vapply(g$layers, function(l) inherits(l$geom, "GeomLabel"), TRUE)]
    chk("R3_F5_the_drawn_bar_is_that_median", length(bars) == 2 && near(bars[[1]]$data$cen, cen_tab()$cen) &&
          identical(labs_[[1]]$data$lab, c("2.63", "1.78", "3.16")), "")
  })
  r3("R3_F5_error_choices_follow_the_centre", {
    chk("R3_F5_error_choices_follow_the_centre", identical(unname(CENTER_ERRORS$median), c("auto", "iqr", "none")) &&
          all(c("sd", "sem", "ci95") %in% CENTER_ERRORS$mean) && !any(c("sd", "sem", "ci95") %in% CENTER_ERRORS$median) &&
          identical(error_used(), "iqr"), error_used())
  })
  r3("R3_F5_stale_mean_error_is_not_drawn_around_a_median", {
    ok <- TRUE
    for (er in c("sd", "sem", "ci95")) {
      session$setInputs(error = er); session$flushReact()
      ok <- ok && identical(error_used(), "iqr") && near(cen_tab()$lo, c(2.41, 1.56, 2.96), 0.01) &&
        any(grepl("cannot be drawn around a median", figure_notes()))
    }
    session$setInputs(error = "none"); session$flushReact()
    ok <- ok && identical(error_used(), "none") && all(cen_tab()$lo == cen_tab()$cen) && !any(grepl("cannot be drawn around a median", figure_notes()))
    session$setInputs(error = "auto")
    chk("R3_F5_stale_mean_error_is_not_drawn_around_a_median", ok)
  })
  r3("R3_F5_sentence_names_the_median", {
    s <- output$sentence
    chk("R3_F5_sentence_names_the_median", grepl("Values are median (IQR) of all plaques: T4 2.63 (2.41–2.82); T7 1.78 (1.56–1.98); lambda 3.16 (2.96–3.38).", s, fixed = TRUE) &&
          !grepl("mean ± SEM", s) && grepl("Pairwise (Tukey HSD): T4 vs T7 p < 0.001", s, fixed = TRUE), s)
  })
  r3("R3_F5_starter_names_median_and_whisker", {
    s <- output$key_text
    chk("R3_F5_starter_names_median_and_whisker", grepl("Bar: median of all plaques. Whisker: IQR of the plaques (25th to 75th percentile).", s, fixed = TRUE) &&
          !grepl("SEM|mean of the", s), s)
  })
  r3("R3_F5_standalone_key_text_matches", {
    base <- file.path(out_dir, "r3_med"); write_key_files(key(), base, 100, 14, "", annotation_text(), figure_sentence_text())
    chk("R3_F5_standalone_key_text_matches", identical(trimws(paste(readLines(paste0(base, "_legend_text.txt"), warn = FALSE), collapse = " ")), trimws(output$key_text)))
  })
  session$setInputs(error = "none"); session$flushReact()
  r3("R3_F5_none_says_no_whisker", chk("R3_F5_none_says_no_whisker", grepl("Whisker|No whisker", output$key_text) && grepl("No whisker.", output$key_text, fixed = TRUE) &&
                                          grepl("Values are median of all plaques: T4 2.63;", output$sentence, fixed = TRUE), output$sentence))
  session$setInputs(error = "auto", center = "mean"); session$flushReact()
  r3("R3_F5_mean_is_unchanged", chk("R3_F5_mean_is_unchanged", grepl("Bar: mean of the 3 plate means. Whisker: SEM of the plate means.", output$key_text, fixed = TRUE) &&
                                       grepl("mean ± SEM of plate means", output$sentence)))
})

# ---- F6 + F7: the figure a reader sees is the one the Python front-ends draw -------------------
testServer(app, {
  raw(read_plaque_table(fx("ct_r3_twelve_long.csv"))$df)
  do.call(session$setInputs, modifyList(ui_defaults, list(vfill = "group"))); session$flushReact()
  r3("R3_F6_twelve_samples_key_below_wrapped", {
    kp <- key_place(); fs <- fig_size(); fo <- fig_out()
    chk("R3_F6_twelve_samples_key_below_wrapped", identical(kp$where, "below") && kp$ncols >= 2 && fo$h > fs$h + 1 && fo$w == fs$w &&
          near(fo$h, fs$h + kp$kh + KEY_GAP_IN, 1e-9), sprintf("%s in %d columns, %.1f -> %.2f in", kp$where, kp$ncols, fs$h, fo$h))
  })
  r3("R3_F6_the_app_states_the_real_size", {
    fo <- fig_out()
    chk("R3_F6_the_app_states_the_real_size", any(grepl(sprintf("^Figure: %.1f x %.1f in: the key is below the plot", fo$w, fo$h), figure_notes())), paste(figure_notes(), collapse = " | "))
  })
  r3("R3_F6_file_has_the_grown_size", {
    f <- file.path(out_dir, "r3_grown.png"); fo <- fig_out()
    ggsave(f, build_plot(), width = fo$w, height = fo$h, dpi = 100, device = "png", bg = "white")
    dm <- r3_png_dim(f)
    chk("R3_F6_file_has_the_grown_size", dm[1] == round(fo$w * 100) && abs(dm[2] - fo$h * 100) <= 1 && dm[2] > 600, paste(dm, collapse = " x "))
  })
  r3("R3_F6_every_entry_once_in_the_placed_key", {
    e <- key(); geo <- key_geometry(e, 14, max_width = 0.97 * fig_size()$w, family = look()$family)
    ent <- geo$rows[geo$rows$kind != "header", ]
    chk("R3_F6_every_entry_once_in_the_placed_key", nrow(ent) == nrow(e) && identical(sort(paste(ent$section, ent$label)), sort(paste(e$section, e$label))) &&
          geo$width <= fig_size()$w, sprintf("%d rows, width %.2f", nrow(ent), geo$width))
  })
  r3("R3_F6_not_placed_only_when_a_row_is_wider_than_the_figure", {
    session$setInputs(base_size = 40); session$flushReact(); kp <- key_place()
    chk("R3_F6_not_placed_only_when_a_row_is_wider_than_the_figure", identical(kp$where, "none") && grepl("widest row needs", kp$note), kp$note %||% "")
    session$setInputs(base_size = 14, width = 16); session$flushReact()
    chk("R3_F6_wide_figure_no_longer_squeezes", key_place()$where %in% c("beside", "below"), key_place()$where)
    session$setInputs(width = 8); session$flushReact()
  })
  r3("R3_F7_compact_n_label_with_many_samples", {
    np <- n_plan()
    chk("R3_F7_compact_n_label_with_many_samples", np$compact && identical(np$label[1], "n=66\nN=3") && np$pt < 9.5 && np$lines == 2, gsub("\n", " / ", np$label[1]))
  })
  session$setInputs(vfill = "auto"); session$flushReact()
  r3("R3_F6_grey_twelve_samples_key_lists_plates_only", {
    # grey violins: only the three plates are keyed, so the key is short, sits beside the plot and the figure keeps its size
    chk("R3_F6_grey_twelve_samples_key_lists_plates_only", identical(key_place()$where, "beside") && nrow(key()) == 3 &&
          identical(fig_out()$h, fig_size()$h) && !any(grepl("^Figure:", figure_notes())), key_place()$where)
  })
})
testServer(app, {
  raw(example); do.call(session$setInputs, ui_defaults); session$flushReact()
  r3("R3_F7_plate_colours_are_okabe_ito", {
    e <- key(); pl <- e[e$section == "plate", ]
    chk("R3_F7_plate_colours_are_okabe_ito", identical(pl$colour, c("#0072B2", "#E69F00", "#009E73")) &&
          identical(unname(style()$rcol), c("#0072B2", "#E69F00", "#009E73")), paste(pl$colour, collapse = " "))
  })
  r3("R3_F7_colour_words_as_python", {
    s <- output$key_text
    chk("R3_F7_colour_words_as_python", startsWith(s, "T4, T7 and lambda are shown as grey violins. Points are coloured by plate: plate1 (blue, filled circles with black outline); plate2 (orange, filled circles with black outline); plate3 (bluish green, filled circles with black outline). Violins: all plaques."), s)
  })
  r3("R3_F7_n_label_wording", {
    np <- n_plan()
    chk("R3_F7_n_label_wording", identical(np$label, c("n = 70 plaques\nN = 3 plates", "n = 75 plaques\nN = 3 plates", "n = 74 plaques\nN = 3 plates")) && !np$compact,
        gsub("\n", " / ", paste(np$label, collapse = " ; ")))
    g <- build_main(); tx <- g$layers[vapply(g$layers, function(l) inherits(l$geom, "GeomText") && is.data.frame(l$data) && "label" %in% names(l$data) &&
                                                  identical(as.character(l$data$label), np$label), TRUE)]
    chk("R3_F7_n_label_is_drawn", length(tx) == 1, "")
  })
  r3("R3_F7_value_labels_next_to_the_bars", {
    g <- build_main(); lb <- g$layers[vapply(g$layers, function(l) inherits(l$geom, "GeomLabel"), TRUE)]
    chk("R3_F7_value_labels_next_to_the_bars", length(lb) == 1 && identical(lb[[1]]$data$lab, c("2.59", "1.78", "3.16")) &&
          near(lb[[1]]$data$x, 1:3 + 0.21) && near(lb[[1]]$data$cen, c(2.59478338206628, 1.78372932330827, 3.15777038393705)), "")
  })
  r3("R3_F7_grey_view_pinned_the_old_palette_no_more", chk("R3_F7_grey_view_pinned_the_old_palette_no_more", !identical(unname(style()$rcol[1:2]), REP_PALETTE[1:2])))
  r3("R3_F7_custom_palette_colours_the_plates_under_grey_violins", {
    session$setInputs(vfill = "neutral", palette = "#112233,#445566,#778899"); session$flushReact()
    ok <- identical(unname(style()$rcol), c("#112233", "#445566", "#778899"))
    session$setInputs(vfill = "auto", palette = ""); session$flushReact()
    chk("R3_F7_custom_palette_colours_the_plates_under_grey_violins", ok)
  })
})

# ---- F8 (R cell) + F11 -------------------------------------------------------------------------
stZ <- plaque_run_stats(tidy(fx("ct_r3_k_zeros.csv")))
chk("R3_F8_zero_size_warning", any(stZ$warnings == "8 values are zero or negative: a plaque size cannot be; check the column (they are included in this analysis)."),
    paste(stZ$warnings, collapse = " | "))
chk("R3_F8_zeros_stay_in_the_analysis", near(stZ$p, 6.24e-03, 0.01e-3) || abs(stZ$p - 6.24e-03) < 5e-6, sprintf("p = %.6g", stZ$p))
dTit <- tidy(fx("ct_r3_k_zeros.csv")); attr(dTit, "info")$value_col <- "titer"
chk("R3_F8_no_warning_for_a_column_that_is_not_a_size", !any(grepl("zero or negative", plaque_run_stats(dTit)$warnings)))
dOne <- tidy(fx("ct_r3_k_zeros.csv")); dOne$value[dOne$value <= 0] <- 1.5; dOne$value[1] <- 0
chk("R3_F8_singular", any(grepl("^1 value is zero or negative: a plaque size cannot be; check the column \\(it is included in this analysis\\)\\.$", plaque_run_stats(dOne)$warnings)))
stI <- plaque_run_stats(tidy(fx("ct_r3_all_identical.csv")))
chk("R3_F11_all_identical_says_na_not_inf", grepl("SD ratio here: n/a\\)", stI$spread_note %||% "") && !grepl("Inf", paste(stI$spread_note, stI$warnings)), stI$spread_note %||% "none")
stNP <- plaque_run_stats(tidy(fx("ct_r1_D_two_12v14.csv")), parametric = "nonparametric", unit = "plaque")
dSmall <- tidy(fx("ct_r1_B_unequal.csv")); keepp <- dSmall$replicate %in% paste0("plate", 1:3); dSmall <- dSmall[keepp, ]
stSm <- plaque_run_stats(dSmall, unit = "replicate", parametric = "nonparametric")
chk("R3_F11_fewer_than_4_wording_as_python", any(stSm$warnings == "Non-parametric test with <4 per group: significance can be UNREACHABLE (Mann–Whitney floor p=0.10 at 3 vs 3) or floored/approximate (Kruskal–Wallis at small N). With few plates prefer a parametric test on the plate means."),
    paste(stSm$warnings, collapse = " | "))
chk("R3_F11_en_dashes", identical(stSm$test, "Kruskal–Wallis") && grepl("Mann–Whitney U", plaque_run_stats(tidy(fx("ct_r2_mwu_5v6_noties.csv")), parametric = "nonparametric")$test, fixed = TRUE) &&
      !any(grepl("Mann-Whitney|Kruskal-Wallis", c(stSm$warnings, stSm$notes))), stSm$test)
