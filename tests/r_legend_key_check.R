# Driven by tests/test_legend_key.py::test_r_shiny_app_key (skipped where R or the app's
# packages are missing). Runs the R Shiny app's server headlessly (shiny::testServer) and
# prints KEY=/DRAWN=/TEXT= lines plus the key files it writes into OUT_DIR.
out_dir <- Sys.getenv("OUT_DIR")
suppressMessages(suppressWarnings(source("app.R", chdir = TRUE)))
app <- shinyApp(ui, server)
emit <- function(tag, x) cat(tag, "=", paste(x, collapse = "|"), "\n", sep = "")
suppressWarnings(testServer(app, {
  set.seed(1)
  d <- expand.grid(group = c("WT", "T7", "lambda"), replicate = c("plate1", "plate2"), i = 1:15,
                   stringsAsFactors = FALSE)
  d$diameter_mm <- rnorm(nrow(d), 1 + match(d$group, c("WT", "T7", "lambda")) * 0.3, 0.08)
  raw(d)
  session$setInputs(group = "group", replicate = "replicate", value = "diameter_mm", order = "",
                    unit = "auto", param = "auto", show_points = TRUE, vfill = "group",
                    center = "mean", error = "auto", show_n = TRUE, frame = FALSE,
                    show_sig = FALSE, log_y = FALSE, title = "", ylab = "", xlab = "",
                    palette_name = "", palette = "", width = 8, height = 5.2, dpi = 100,
                    place_key = TRUE)
  fills <- function() {
    g <- build_main(); b <- ggplot2::ggplot_build(g)
    # CT-R3 F7: the white box behind a bar's value (GeomLabel) is a label background, not a key colour
    toupper(unique(unlist(lapply(seq_along(b$data), function(i)
      if (inherits(g$layers[[i]]$geom, "GeomLabel")) NULL else if ("fill" %in% names(b$data[[i]])) b$data[[i]]$fill))))
  }
  emit("KEY1", paste(key()$label, key()$colour, sep = ":"))
  emit("DRAWN1", sort(fills()))
  emit("TEXT1", output$key_text)
  emit("PLACED1", inherits(build_plot(), "ggarrange"))
  # CT-R3 F5: the file carries the bar / whisker sentence, as the Legend key download does
  write_key_files(key(), file.path(out_dir, "violin"), 100, 14, "", annotation_text(), figure_sentence_text())
  d$group[d$group == "T7"] <- "T7 mut"                      # rename one sample ...
  raw(d)
  session$setInputs(palette = "#0072B2,#E69F00,#D62728")    # ... and recolour another
  emit("KEY2", paste(key()$label, key()$colour, sep = ":"))
  emit("DRAWN2", sort(fills()))
  emit("TEXT2", output$key_text)
  session$setInputs(place_key = FALSE)
  emit("PLACED2", inherits(build_plot(), "ggarrange"))
}))
