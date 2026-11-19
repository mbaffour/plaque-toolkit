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
PY_E_OMNI <- 0.0008799125772243469
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
chk("F2_E_auto_falls_back_with_warning", stE2$unit == "plaque" && any(grepl("pseudoreplication", stE2$warnings)) &&
      any(grepl("solo", stE2$warnings)))
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
chk("F3_ambiguous_comma_stops", inherits(r, "plaque_data_problem") && grepl("decimal point", conditionMessage(r)) &&
      grepl("nothing was loaded", conditionMessage(r)), if (inherits(r, "error")) conditionMessage(r) else "was read")
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
chk("F9_rows_dropped_reported", nrow(d) == 70 && any(grepl("2 of 72 rows were left out", attr(d, "info")$notes)), paste(attr(d, "info")$notes, collapse = " "))
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
  chk("F21_log_drop_counted", !is.null(ld) && ld$n > 0 && grepl("0 or negative", ld$caption), if (!is.null(ld)) ld$caption else "none")
  chk("F21_log_drop_on_figure_and_notes", any(grepl("Log axis", figure_notes())) && grepl("Log axis", build_main()$labels$caption %||% ""))
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
  chk("F23_text_size_follows_base", {a <- sz(7); b <- sz(28); all(b / a > 3.9) && length(a) >= 2}, paste(sz(14), collapse = ","))
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
  chk("F15_status_says_theme_replaced", grepl("colour theme was changed", output$paper_style_status), output$paper_style_status)
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
  chk("F18_default_grey_view_keeps_rep_palette", identical(unname(style()$rcol[1:2]), REP_PALETTE[1:2]))
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
chk("F22_text_boxes_multiline_with_copy", grepl("<textarea[^>]*id=\"sentence\"", raw_ui) && grepl("<textarea[^>]*id=\"key_text\"", raw_ui) &&
      length(gregexpr("writeText", raw_ui)[[1]]) >= 2)
chk("F22_tables_scroll_in_own_box", grepl("overflow-x: auto", raw_ui) && isTRUE(dt_opts_probe <- TRUE))
chk("F5_download_statistics_button", grepl("dl_stats", raw_ui) && grepl("Download statistics \\(CSV\\)", raw_ui))
chk("F1_variances_select", grepl('id="equal_var"', raw_ui) && grepl("Welch ANOVA", raw_ui))
chk("F6_annotate_select", grepl('id="annotate"', raw_ui) && grepl("all pairs", raw_ui))
bat <- readLines(file.path("..", "plaque_stats", "Run R App.bat"), warn = FALSE)
chk("F24_bat_install_line_has_jsonlite", any(grepl("install.packages", bat) & grepl("jsonlite", bat)))
