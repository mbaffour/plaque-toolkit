# Driven by tests/test_paper_style.py (skipped where R or the app's packages are missing).
# Run from plaque_stats/ with OUT_DIR set. Runs the R Shiny app's server headlessly
# (shiny::testServer) and prints tagged lines:
#   1. BYTE_*     default violins rendered by the 1.2.0 app.R (commit 176656b) and by this one,
#                 each in its own Rscript, compared byte for byte (BYTE_SKIP when the commit is
#                 not in this clone)
#   2. KEY_A/KEY_B/DRAWN_B   colours keyed by sample NAME across two CSVs
#   3. *3         tests/fixtures/paper_style_times.json applied through CFU_PAPER_STYLE
#   4. *4         tests/fixtures/paper_style_missing_font.json (a font this machine lacks)
#   5. *5         no paper style file
# shiny::testServer does not echo update*Input() back into input (there is no browser), so the
# style's input values are mirrored with session$setInputs from paper_style_applied(), exactly
# the values the browser would send back; the registry merge needs no mirroring.
out_dir <- Sys.getenv("OUT_DIR")
fixtures <- normalizePath(file.path("..", "tests", "fixtures"))
repo_root <- normalizePath("..")
no_style <- file.path(out_dir, "no_paper_style.json")       # never touch a real paper_style.json
Sys.setenv(CFU_PAPER_STYLE = no_style)
suppressMessages(suppressWarnings(source("app.R", chdir = TRUE)))
app <- shinyApp(ui, server)
emit <- function(tag, x) cat(tag, "=", paste(x, collapse = "|"), "\n", sep = "")
rscript <- file.path(R.home("bin"), "Rscript")

fixture_data <- function() {
  set.seed(1)
  d <- expand.grid(group = c("WT", "T7", "lambda"), replicate = c("plate1", "plate2"), i = 1:15,
                   stringsAsFactors = FALSE)
  d$diameter_mm <- rnorm(nrow(d), 1 + match(d$group, c("WT", "T7", "lambda")) * 0.3, 0.08)
  d
}
# every sidebar input at the value its UI gives it (the old app ignores the ones it lacks)
ui_defaults <- list(group = "group", replicate = "replicate", value = "diameter_mm", order = "",
                    unit = "auto", param = "auto", show_points = TRUE, vfill = "auto",
                    center = "mean", error = "auto", show_n = TRUE, frame = FALSE,
                    show_sig = TRUE, log_y = FALSE, title = "", ylab = "", xlab = "",
                    palette_name = "", palette = "", width = 8, height = 5.2, dpi = 300,
                    place_key = TRUE, font_family = "sans", font_family_custom = "",
                    base_size = 14, axis_color = "#33413c", axis_line_width = 0.6)
fills <- function(g) {
  b <- ggplot2::ggplot_build(g)
  toupper(unique(unlist(lapply(b$data, function(l) if ("fill" %in% names(l)) l$fill))))
}

# ---- 1. byte-identical defaults against the 1.2.0 app.R --------------------------------------
BASE_COMMIT <- "176656b"
base_dir <- file.path(out_dir, "base_app"); dir.create(base_dir, showWarnings = FALSE)
base_app <- file.path(base_dir, "app.R")
st <- tryCatch(suppressWarnings(system2("git", c("-C", shQuote(repo_root), "show",
                                                 paste0(BASE_COMMIT, ":plaque_stats/app.R")),
                                        stdout = base_app, stderr = FALSE)), error = function(e) 1L)
have_base <- identical(as.integer(st), 0L) && file.exists(base_app) && file.size(base_app) > 0
if (!have_base) {
  emit("BYTE_SKIP", paste0("commit ", BASE_COMMIT, " is not in this clone"))
} else {
  child <- file.path(out_dir, "render_defaults.R")
  writeLines(c(
    'args <- commandArgs(TRUE); app_path <- args[1]; out <- args[2]',
    'Sys.setenv(CFU_PAPER_STYLE = file.path(out, "no_paper_style.json"))',
    'suppressMessages(suppressWarnings(source(app_path, chdir = TRUE)))',
    'app <- shinyApp(ui, server)',
    'set.seed(1)',
    'd <- expand.grid(group = c("WT", "T7", "lambda"), replicate = c("plate1", "plate2"), i = 1:15, stringsAsFactors = FALSE)',
    'd$diameter_mm <- rnorm(nrow(d), 1 + match(d$group, c("WT", "T7", "lambda")) * 0.3, 0.08)',
    'defaults <- list(group = "group", replicate = "replicate", value = "diameter_mm", order = "",',
    '  unit = "auto", param = "auto", show_points = TRUE, vfill = "auto", center = "mean", error = "auto",',
    '  show_n = TRUE, frame = FALSE, show_sig = TRUE, log_y = FALSE, title = "", ylab = "", xlab = "",',
    '  palette_name = "", palette = "", width = 8, height = 5.2, dpi = 300, place_key = TRUE,',
    '  font_family = "sans", font_family_custom = "", base_size = 14, axis_color = "#33413c", axis_line_width = 0.6)',
    'suppressWarnings(testServer(app, {',
    '  raw(d); do.call(session$setInputs, defaults)',
    '  save <- function(name) { set.seed(1); ggsave(file.path(out, paste0(name, ".svg")), build_plot(),',
    '                             width = 8, height = 5.2, device = svglite::svglite) }',
    '  save("default_key_on")                                   # the UI defaults, key placed',
    '  session$setInputs(place_key = FALSE); save("default_key_off")',
    '  session$setInputs(place_key = TRUE, vfill = "group", frame = TRUE); save("coloured_framed")',
    '  session$setInputs(frame = FALSE, show_sig = TRUE, show_points = FALSE); save("coloured_nopoints")',
    '  write_key_files(key(), file.path(out, "violin"), 100)   # the stand-alone key files',
    '}))'
  ), child)
  render_with <- function(app_path, dir) {
    dir.create(dir, showWarnings = FALSE)
    res <- suppressWarnings(system2(rscript, c(shQuote(child), shQuote(app_path), shQuote(dir)),
                                    stdout = TRUE, stderr = TRUE))
    status <- attr(res, "status"); if (is.null(status)) status <- 0L
    if (!identical(as.integer(status), 0L)) cat("child failed for", app_path, ":", tail(res, 8), sep = "\n")
    identical(as.integer(status), 0L)
  }
  old_dir <- file.path(out_dir, "old"); new_dir <- file.path(out_dir, "new")
  ok_old <- render_with(base_app, old_dir)
  ok_new <- render_with(normalizePath("app.R"), new_dir)
  emit("BYTE_RENDER", c(old = ok_old, new = ok_new))
  for (f in c("default_key_on.svg", "default_key_off.svg", "coloured_framed.svg",
              "coloured_nopoints.svg", "violin_legend_key.svg", "violin_legend_text.txt")) {
    a <- file.path(old_dir, f); b <- file.path(new_dir, f)
    same <- file.exists(a) && file.exists(b) && file.size(a) == file.size(b) &&
      identical(readBin(a, "raw", file.size(a)), readBin(b, "raw", file.size(b)))
    emit(paste0("BYTE_", sub("\\.(svg|txt)$", "", f)), if (same) "identical" else "differ")
  }
}

# ---- 2. colours keyed by sample NAME across files ----------------------------------------------
Sys.setenv(CFU_PAPER_STYLE = no_style)
suppressWarnings(testServer(app, {
  raw(fixture_data())
  do.call(session$setInputs, modifyList(ui_defaults, list(vfill = "group")))
  emit("KEY_A", paste(key()$label, key()$colour, sep = ":"))
  d2 <- fixture_data(); d2$group[d2$group == "WT"] <- "T7mut"      # WT gone, T7mut new
  d2 <- d2[order(match(d2$group, c("T7", "lambda", "T7mut"))), ]
  raw(d2); session$flushReact()
  emit("KEY_B", paste(key()$label, key()$colour, sep = ":"))
  emit("DRAWN_B", sort(fills(build_main())))
  emit("REGISTRY_B", paste(names(colour_registry()), colour_registry(), sep = ":"))
  emit("STATUS2", output$paper_style_status)
}))

# ---- 3. the Times New Roman paper style ---------------------------------------------------------
Sys.setenv(CFU_PAPER_STYLE = file.path(fixtures, "paper_style_times.json"))
suppressWarnings(testServer(app, {
  raw(fixture_data())
  do.call(session$setInputs, modifyList(ui_defaults, list(title = "Figure-specific title", width = 10,
                                                           log_y = TRUE)))
  ap <- paper_style_applied()
  emit("APPLIED3", paste(names(ap$inputs), unlist(ap$inputs), sep = ":"))
  emit("PALETTE3", paste(names(ap$sample_palette), unlist(ap$sample_palette), sep = ":"))
  do.call(session$setInputs, ap$inputs)                   # what the browser would echo back
  emit("STATUS3", output$paper_style_status)
  emit("FONT_STATUS3", output$font_status)
  emit("FONT3", font_resolved()$family)
  g <- build_main(); th <- g$theme
  emit("THEME_FAMILY3", th$text$family)
  emit("THEME_SIZE3", th$text$size)
  emit("AXIS_COL3", th$axis.line$colour)
  emit("AXIS_LW3", th$axis.line$linewidth)
  emit("TICK_LW3", th$axis.ticks$linewidth)
  lk <- look(); kp <- key_plot(key(), lk$base_size, lk$family)
  emit("KEY_FAMILY3", c(kp$layers[[1]]$aes_params$family, kp$layers[[2]]$aes_params$family,
                        kp$theme$text$family))
  emit("NROW_FAMILY3", g$layers[[length(g$layers)]]$aes_params$family)
  b <- ggplot2::ggplot_build(g)
  emit("FILL_WT3", toupper(b$data[[1]]$fill[1]))          # layer 1 = the WT violin
  emit("DRAWN3", sort(fills(g)))
  emit("KEY3", paste(key()$label, key()$colour, sep = ":"))
  emit("NEUTRAL3", style()$neutral)
  emit("UNTOUCHED3", c(input$title, input$width, input$log_y, input$vfill))
  emit("TEXT3", output$key_text)
}))

# ---- 4. a font this machine lacks -------------------------------------------------------------
Sys.setenv(CFU_PAPER_STYLE = file.path(fixtures, "paper_style_missing_font.json"))
suppressWarnings(testServer(app, {
  raw(fixture_data())
  do.call(session$setInputs, ui_defaults)
  ap <- paper_style_applied()
  emit("APPLIED4", paste(names(ap$inputs), unlist(ap$inputs), sep = ":"))
  do.call(session$setInputs, ap$inputs)
  f <- font_resolved()
  emit("FONT4", c(f$requested, f$family, f$available))
  emit("FONT_STATUS4", output$font_status)
  emit("THEME_FAMILY4", build_main()$theme$text$family)
  emit("THEME_SIZE4", build_main()$theme$text$size)
  emit("STATUS4", output$paper_style_status)
}))

# ---- 5. no paper style file -------------------------------------------------------------------
Sys.setenv(CFU_PAPER_STYLE = no_style)
suppressWarnings(testServer(app, {
  raw(fixture_data())
  do.call(session$setInputs, modifyList(ui_defaults, list(vfill = "group")))
  session$flushReact()      # the status set after the first flush reaches the output on the next
  ap <- paper_style_applied()
  emit("APPLIED5", length(ap$inputs) + length(ap$sample_palette))
  emit("STATUS5", output$paper_style_status)
  emit("FONT_STATUS5", output$font_status)
  th <- build_main()$theme
  emit("THEME5", c(th$text$family, th$text$size, th$axis.line$colour, th$axis.line$linewidth))
  emit("KEY5", paste(key()$label, key()$colour, sep = ":"))
  emit("NEUTRAL5", style()$neutral)
}))
