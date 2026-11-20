# Helper for tests/test_ct_r1_parity.py. Run from plaque_stats/ :
#   Rscript ../tests/r_parity_dump.R <csv> [unit] [parametric] [equal_var]
# Loads the app the same way tests/r_ct_r1_check.R does, runs plaque_run_stats() on the file
# (columns group, replicate, diameter_mm) and prints ONE JSON object on the last line.
args <- commandArgs(trailingOnly = TRUE)
csv <- normalizePath(args[1])
unit <- if (length(args) >= 2) args[2] else "auto"
parametric <- if (length(args) >= 3) args[3] else "auto"
equal_var <- if (length(args) >= 4) args[4] else "auto"
Sys.setenv(CFU_PAPER_STYLE = file.path(tempdir(), "no_paper_style.json"))
suppressMessages(suppressWarnings(source("app.R", chdir = TRUE)))
df <- read_plaque_table(csv)$df
d <- tidy_plaque_data(df, "group", "replicate", "diameter_mm", NULL, "")
st <- plaque_run_stats(d, unit = unit, parametric = parametric, equal_var = equal_var)
pw <- st$pairwise
keys <- vapply(seq_len(nrow(pw)), function(i) paste(sort(c(pw$group1[i], pw$group2[i]), method = "radix"), collapse = "|"), "")
pair <- setNames(lapply(pw$p_adj, function(v) if (is.na(v)) NULL else v), keys)
num <- function(x) if (is.null(x) || length(x) == 0 || is.na(x)) NULL else as.numeric(x)
# CT-R3 F5: the bar and whisker of every sample (center_table), for the Python engine's center_table()
ctr <- function(center, error) {
  ct <- center_table(d, st$rm, center, error)
  setNames(lapply(seq_len(nrow(ct)), function(i) lapply(list(ct$cen[i], ct$lo[i], ct$hi[i], ct$n_units[i]),
                                                       function(v) if (is.na(v)) NULL else as.numeric(v))),
           as.character(ct$group))
}
centers <- list(mean_sem = ctr("mean", "sem"), mean_sd = ctr("mean", "sd"), mean_ci95 = ctr("mean", "ci95"),
                mean_iqr = ctr("mean", "iqr"), mean_none = ctr("mean", "none"),
                median_iqr = ctr("median", "iqr"), median_none = ctr("median", "none"))
res <- list(test = st$test, centers = centers, p = num(st$p), pairwise = pair,
            posthoc = if (is.na(st$posthoc)) NULL else st$posthoc,
            unit = st$unit, parametric_used = isTRUE(st$parametric_used),
            levene_p = num(st$levene_p), min_n = as.integer(st$min_n),
            p_method = if (is.null(st$p_method)) NULL else st$p_method)
cat(jsonlite::toJSON(res, auto_unbox = TRUE, null = "null", digits = NA), "\n")
