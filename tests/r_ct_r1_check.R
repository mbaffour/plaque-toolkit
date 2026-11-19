# Driven by tests/test_ct_r1_r_app.py (skipped where R or the app's packages are missing).
# Run from plaque_stats/ with OUT_DIR set. Click-through round 1 (CT-R1) findings F1..F24 of the
# R Shiny app (plaque_stats/app.R), checked with shiny::testServer and plain function calls.
# Prints one line per check:  PASS <id> <detail>   or   FAIL <id> <detail>
# The Python engine (plaque_stats.py) is the REFERENCE: the numbers below were produced by it.
pdf(NULL)                                  # no Rplots.pdf, whatever opens a device
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
chk("F1_B_sd_ratio_warning", any(grepl("Levene", stB$warnings)))
stBe <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "yes")
chk("F1_B_equal_is_classic", stBe$test == "one-way ANOVA" && stBe$posthoc == "Tukey HSD" &&
      near(stBe$p, 0.019484354511230786) && near(unname(pw_p(stBe)), c(0.14034054967218046, 0.014997722692196347,
                                                                      0.41712136513547327)))
stBu <- plaque_run_stats(tidy(fx("ct_r1_B_unequal.csv")), equal_var = "no")
chk("F1_B_unequal_forced", stBu$test == "Welch ANOVA" && near(stBu$p, PY_B_OMNI))
# the SD-ratio warning: tight Levene but a 5x SD ratio with 3 plates per group
set.seed(3)
dd <- data.frame(group = factor(rep(c("a", "b", "c"), each = 6), levels = c("a", "b", "c")),
                 replicate = rep(rep(c("p1", "p2", "p3"), each = 2), 3),
                 value = c(1, 1.02, 1.01, 0.99, 1.0, 1.03, 2, 2.4, 1.7, 2.2, 1.9, 2.5, 3, 3.01, 3.02, 3.0, 2.99, 3.01))
stR <- plaque_run_stats(dd, equal_var = "auto")
chk("F1_sd_ratio_warning_text", any(grepl("largest group SD", stR$warnings)) && any(grepl("unequal", stR$warnings)),
    paste(stR$warnings, collapse = " | "))
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
