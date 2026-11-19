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
res <- list(test = st$test, p = num(st$p), pairwise = pair,
            posthoc = if (is.na(st$posthoc)) NULL else st$posthoc,
            unit = st$unit, parametric_used = isTRUE(st$parametric_used),
            levene_p = num(st$levene_p), min_n = as.integer(st$min_n))
cat(jsonlite::toJSON(res, auto_unbox = TRUE, null = "null", digits = NA), "\n")
