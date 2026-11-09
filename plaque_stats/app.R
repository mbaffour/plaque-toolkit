# app.R — Plaque Stats & Violins (R-Shiny)
# ---------------------------------------------------------------------------------------------
# Interactive companion to plaque_stats.py: upload a tidy CSV of grouped plaque measurements,
# get publication-ready, customizable violin plots + statistics + data summaries, and download
# the figure (PNG/SVG/PDF) and tables. Uses the SAME data format as the Python script.
#
# Run:   R -e "shiny::runApp('plaque_stats', launch.browser=TRUE)"
#   or open app.R in RStudio and click "Run App".
# First time only, install packages:
#   install.packages(c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","scales","svglite","jsonlite"))
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
# ---------------------------------------------------------------------------------------------

library(shiny)
library(ggplot2)
library(dplyr)
library(tidyr)
library(readr)
library(DT)
library(rstatix)
library(ggpubr)
library(jsonlite)

OKABE_ITO <- c("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
               "#D55E00", "#F0E442", "#999999", "#000000")
# muted palette for REPLICATES (plates): points + plate means are coloured by plate (SuperPlot)
REP_PALETTE <- c("#4C6E9C", "#E0A458", "#6AAA64", "#B65C5C", "#8A78B0",
                 "#4FA3A5", "#C77CB5", "#9A8C6B", "#6C6C6C")
med_iqr <- function(x) data.frame(y = median(x), ymin = quantile(x, .25, names = FALSE),
                                  ymax = quantile(x, .75, names = FALSE))
PALETTES <- list(
  okabe = OKABE_ITO,
  set2  = c("#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"),
  tab10 = c("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"),
  warm  = c("#B4451F", "#D98032", "#E9B44C", "#9B2226", "#CA6702", "#BB3E03", "#AE2012", "#EE9B00"),
  cool  = c("#3D5A80", "#5E8B9E", "#98C1D9", "#293241", "#4C6E9C", "#6AAA9E", "#5C7AA0", "#7FB3C9"),
  grays = c("#4d4d4d", "#7f7f7f", "#a6a6a6", "#c9c9c9", "#2b2b2b", "#8f8f8f", "#606060", "#b8b8b8"))

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

# The registry with every name in `names` present, existing names untouched: a new name takes
# the first colour of `pool` no other name uses; once every colour is taken the pool recycles,
# as the positional palette always did. Accepts a named list (as JSON reads back) or a vector.
extend_colour_registry <- function(registry, names, pool = OKABE_ITO) {
  reg <- unlist(registry)
  if (is.null(reg) || is.null(names(reg))) reg <- setNames(character(0), character(0))
  reg <- setNames(as.character(reg), names(reg))
  for (nm in unique(as.character(names))) {
    if (is.na(nm) || nm %in% names(reg)) next
    free <- pool[!toupper(pool) %in% toupper(reg)]
    reg[[nm]] <- if (length(free)) free[1] else pool[(length(reg) %% length(pool)) + 1]
  }
  reg
}
# Colours for the given levels, in level order, from the registry by name.
registry_colours <- function(registry, levels_vec, pool = OKABE_ITO) {
  levels_vec <- as.character(levels_vec)
  reg <- extend_colour_registry(registry, levels_vec, pool)
  setNames(unname(reg[levels_vec]), levels_vec)
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

hex_to_lab <- function(hex) grDevices::convertColor(t(grDevices::col2rgb(hex)) / 255,
                                                    from = "sRGB", to = "Lab")
colour_name <- function(hex) {
  lab <- hex_to_lab(hex); ref <- hex_to_lab(KEY_COLOUR_NAMES)
  names(KEY_COLOUR_NAMES)[which.min(colSums((t(ref) - as.numeric(lab[1, ]))^2))]
}
to_hex <- function(col) toupper(grDevices::rgb(t(grDevices::col2rgb(col)), maxColorValue = 255))

# the ONE mapping of the violin: sample -> colour, plate -> colour, grey violins?
# Sample colours come from the registry BY NAME (a name the registry lacks takes the first
# colour of `pool` no other name uses), so a sample keeps its colour across files and apps.
style_map <- function(d, registry, vfill, chose_theme, superplot, pool = OKABE_ITO) {
  levs <- levels(d$group)
  gcol <- registry_colours(registry, levs, pool)
  reps <- if (superplot) sort(unique(d$replicate[!is.na(d$replicate)])) else character(0)
  rcol <- setNames(rep(REP_PALETTE, length.out = length(reps)), reps)
  group_fill <- identical(vfill, "group") || (chose_theme && identical(vfill, "auto"))
  neutral <- identical(vfill, "neutral") || (!group_fill && superplot)
  list(gcol = gcol, rcol = rcol, neutral = neutral, superplot = superplot)
}

# one row per keyed sample/plate, styled as drawn: coloured violins (alpha .25, no outline);
# plate means are filled circles (pch 21) with the dark #12211d outline
key_entries <- function(sm) {
  rows <- list()
  if (!sm$neutral)
    for (g in names(sm$gcol))
      rows[[length(rows) + 1]] <- data.frame(label = g, section = "sample", kind = "patch",
        colour = to_hex(sm$gcol[[g]]), edge = NA_character_, alpha = 0.25, shape = NA_integer_,
        stringsAsFactors = FALSE)
  if (sm$superplot)
    for (r in names(sm$rcol))
      rows[[length(rows) + 1]] <- data.frame(label = r, section = "plate", kind = "marker",
        colour = to_hex(sm$rcol[[r]]), edge = "#12211D", alpha = 1, shape = 21L,
        stringsAsFactors = FALSE)
  if (!length(rows)) return(data.frame(label = character(0), section = character(0),
                                       kind = character(0), colour = character(0),
                                       edge = character(0), alpha = numeric(0),
                                       shape = integer(0), stringsAsFactors = FALSE))
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
    words[idx] <- shade[e$colour[idx]]
  }
  desc <- vapply(seq_len(nrow(e)), function(i) {
    if (e$kind[i] == "patch") return(paste0(words[i], ", filled violin"))
    out <- paste0(words[i], ", filled circles")
    if (!is.na(e$edge[i]) && e$edge[i] != e$colour[i] && !grepl(colour_name(e$edge[i]), words[i], fixed = TRUE))
      out <- paste0(out, " with ", colour_name(e$edge[i]), " outline")
    out
  }, "")
  paste0(paste0(e$label, " (", desc, ")", collapse = "; "), ".")
}

# the key as a ggplot: section headers in bold when samples AND plates are keyed, the figure's
# font (theme_classic base_size and family) -- used stand-alone and placed beside the figure alike
key_plot <- function(e, base_size = 14, family = "") {
  secs <- unique(e$section)
  rows <- if (length(secs) > 1)
    do.call(rbind, lapply(secs, function(s) rbind(
      data.frame(label = s, section = s, kind = "header", colour = NA, edge = NA, alpha = NA,
                 shape = NA, stringsAsFactors = FALSE), e[e$section == s, ])))
  else rbind(data.frame(label = secs, section = secs, kind = "header", colour = NA, edge = NA,
                        alpha = NA, shape = NA, stringsAsFactors = FALSE), e)
  rows$y <- rev(seq_len(nrow(rows)))
  tsize <- base_size * 0.8 / ggplot2::.pt
  hdr <- rows[rows$kind == "header", ]; pat <- rows[rows$kind == "patch", ]
  mk <- rows[rows$kind == "marker", ]; ent <- rows[rows$kind != "header", ]
  p <- ggplot() +
    geom_text(data = hdr, aes(x = 0.05, y = y, label = label), hjust = 0, fontface = "bold",
              size = tsize, family = family) +
    geom_text(data = ent, aes(x = 0.45, y = y, label = label), hjust = 0, size = tsize,
              family = family)
  if (nrow(pat)) p <- p + geom_tile(data = pat, aes(x = 0.22, y = y), width = 0.3, height = 0.55,
                                    fill = pat$colour, alpha = pat$alpha, colour = NA)
  if (nrow(mk)) p <- p + geom_point(data = mk, aes(x = 0.22, y = y), shape = 21, size = 4.2,
                                    stroke = 0.9, fill = mk$colour, colour = mk$edge)
  # x is in inches of the saved key (key_size), so the names never clip
  p + scale_x_continuous(limits = c(0, key_size(e, base_size)[["width"]]), expand = c(0, 0)) +
    scale_y_continuous(limits = c(0.4, nrow(rows) + 0.6)) +
    theme_void(base_size = base_size, base_family = family) +
    theme(plot.background = element_rect(fill = "white", colour = NA))
}
write_key_files <- function(e, base, dpi = 300, base_size = 14, family = "") {
  sz <- key_size(e, base_size); kp <- key_plot(e, base_size, family)
  out <- c(png = paste0(base, "_legend_key.png"), svg = paste0(base, "_legend_key.svg"),
           pdf = paste0(base, "_legend_key.pdf"), txt = paste0(base, "_legend_text.txt"))
  ggsave(out[["png"]], kp, width = sz[["width"]], height = sz[["height"]], dpi = dpi)
  ggsave(out[["svg"]], kp, width = sz[["width"]], height = sz[["height"]], device = svglite::svglite)
  ggsave(out[["pdf"]], kp, width = sz[["width"]], height = sz[["height"]], device = "pdf")
  writeLines(text_starter(e), out[["txt"]])
  unname(out)
}
key_size <- function(e, base_size = 14) {
  n <- nrow(e) + length(unique(e$section))
  c(width = 0.6 + 0.105 * max(nchar(c(e$label, e$section))) * base_size / 14, height = 0.25 + 0.24 * n)
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
    "<li><b>value</b> / numeric columns: the measurement(s).</li></ul>"))
}

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
      checkboxInput("log_y", "Log y-axis", FALSE),
      tags$hr(),
      textInput("title", "Title", ""),
      textInput("ylab", "Y-axis label", ""),
      textInput("xlab", "X-axis label", ""),
      textInput("order", "Group order (comma-sep, optional)", ""),
      selectInput("palette_name", "Colour theme",
                  c("(custom hex below)" = "", "Okabe-Ito" = "okabe", "Set2" = "set2",
                    "Tab10" = "tab10", "Warm" = "warm", "Cool" = "cool", "Grays" = "grays")),
      textInput("palette", "Custom palette (comma-sep hex)", ""),
      selectInput("font_family", "Font",
                  c("Default sans" = "sans", "Arial", "Helvetica", "Times New Roman",
                    "Serif" = "serif", "Custom…" = "custom")),
      conditionalPanel("input.font_family == 'custom'",
                       textInput("font_family_custom", "Custom font name", "")),
      numericInput("base_size", "Base font size (pt)", 14, 6, 40, 1),
      textInput("axis_color", "Axis colour (hex)", "#33413c"),
      numericInput("axis_line_width", "Axis line width", 0.6, 0.1, 3, 0.1),
      tags$small(textOutput("paper_style_status"), textOutput("font_status")),
      sliderInput("width", "Figure width (in)", 4, 16, 8, 0.5),
      sliderInput("height", "Figure height (in)", 3, 12, 5.2, 0.2),
      numericInput("dpi", "PNG dpi", 300, 72, 1200, 50)
    ),
    mainPanel(
      width = 9,
      tabsetPanel(
        tabPanel("Plot",
          br(),
          plotOutput("violin", height = "560px"),
          br(),
          downloadButton("dl_png", "PNG"), downloadButton("dl_svg", "SVG (editable)"),
          downloadButton("dl_pdf", "PDF (editable)"),
          downloadButton("dl_key", "Legend key (PNG + SVG + PDF)"),
          checkboxInput("place_key", "Place key on figure", TRUE),
          h5("Legend text starter"), verbatimTextOutput("key_text"),
          tags$button("Copy", class = "btn btn-sm btn-default",
                      onclick = "navigator.clipboard.writeText(document.getElementById('key_text').innerText)")),
        tabPanel("Statistics",
          br(), h4("Omnibus test"), verbatimTextOutput("omni"),
          h4("Pairwise (adjusted)"), DTOutput("pairwise"),
          h4("Paste-ready sentence"), verbatimTextOutput("sentence")),
        tabPanel("Summaries",
          br(), h4("Per group"), DTOutput("summary_group"),
          downloadButton("dl_sumg", "Download group summary CSV"),
          h4("Per plate (replicate means)"), DTOutput("summary_rep"),
          downloadButton("dl_sumr", "Download replicate summary CSV")),
        tabPanel("Data format",
          br(), format_help())
      )
    )
  )
)

server <- function(input, output, session) {

  raw <- reactiveVal(NULL)

  observeEvent(input$file, {
    ext <- tools::file_ext(input$file$name)
    sep <- if (ext %in% c("tsv", "txt")) "\t" else ","
    raw(readr::read_delim(input$file$datapath, delim = sep, comment = "#",
                          show_col_types = FALSE))
  })
  observeEvent(input$load_example, {
    cand <- c("example_data_wide.csv",
              file.path("plaque_stats", "example_data_wide.csv"))
    p <- cand[file.exists(cand)][1]
    if (!is.na(p)) raw(readr::read_csv(p, show_col_types = FALSE))
    else showNotification("example_data_wide.csv not found — run: python plaque_stats.py --make-example",
                          type = "warning")
  })

  output$col_pickers <- renderUI({
    df <- raw(); req(df)
    cols <- names(df)
    numeric_cols <- cols[sapply(df, is.numeric)]
    is_long <- "value" %in% cols
    tagList(
      selectInput("group", "Group column", cols,
                  selected = intersect(c("group", "sample", "phage"), cols)[1] %||% cols[1]),
      selectInput("replicate", "Replicate column (plate)", c("(none)", cols),
                  selected = intersect(c("replicate", "plate"), cols)[1] %||% "(none)"),
      if (is_long)
        selectInput("metric", "Metric to plot",
                    unique(as.character(df$metric)), selected = unique(as.character(df$metric))[1])
      else
        selectInput("value", "Value column",
                    numeric_cols, selected = intersect(c("diameter_mm", "value"), numeric_cols)[1] %||% numeric_cols[1])
    )
  })

  `%||%` <- function(a, b) if (is.null(a) || is.na(a) || length(a) == 0) b else a

  # tidy long frame: group, replicate, value
  dat <- reactive({
    df <- raw(); req(df, input$group)
    is_long <- "value" %in% names(df)
    d <- data.frame(group = as.character(df[[input$group]]), stringsAsFactors = FALSE)
    d$replicate <- if (!is.null(input$replicate) && input$replicate != "(none)" &&
                       input$replicate %in% names(df)) as.character(df[[input$replicate]]) else NA_character_
    if (is_long) {
      req(input$metric)
      d$value <- suppressWarnings(as.numeric(df$value))
      d <- d[as.character(df$metric) == input$metric, ]
    } else {
      req(input$value)
      d$value <- suppressWarnings(as.numeric(df[[input$value]]))
    }
    d <- d[is.finite(d$value), ]
    # drop blank/NA groups; treat blank/"nan" replicate labels as missing (robust to Excel gaps)
    d$group <- trimws(d$group)
    d <- d[!is.na(d$group) & !(tolower(d$group) %in% c("", "na", "nan", "nat")), ]
    d$replicate <- sub("\\.0$", "", trimws(as.character(d$replicate)))
    d$replicate[tolower(d$replicate) %in% c("", "na", "nan", "nat")] <- NA
    ord <- trimws(strsplit(input$order, ",")[[1]])
    ord <- ord[ord != "" & ord %in% unique(d$group)]
    lev <- if (length(ord)) ord else unique(d$group)
    d$group <- factor(d$group, levels = lev)
    d[!is.na(d$group), ]
  })

  metric_name <- reactive({
    df <- raw()
    if ("value" %in% names(df)) input$metric else input$value
  })

  has_rep <- reactive({
    d <- dat()
    !all(is.na(d$replicate)) &&
      min(tapply(d$replicate, d$group, function(x) length(unique(x[!is.na(x)])))) >= 2
  })

  rep_means <- reactive({
    d <- dat(); req(has_rep())
    d %>% filter(!is.na(replicate)) %>% group_by(group, replicate) %>%
      summarise(value = mean(value), n_plaques = n(), .groups = "drop")
  })

  use_unit <- reactive({
    if (input$unit == "auto") if (has_rep()) "replicate" else "plaque" else input$unit
  })

  # data used for TESTING (plate means when unit = replicate)
  test_dat <- reactive({
    if (use_unit() == "replicate" && has_rep()) rep_means()[, c("group", "value")]
    else dat()[, c("group", "value")]
  })

  use_param <- reactive({
    d <- test_dat()
    min_n <- suppressWarnings(min(table(droplevels(factor(d$group)))))
    sh <- d %>% group_by(group) %>%
      summarise(p = tryCatch(shapiro.test(value)$p.value, error = function(e) NA_real_), .groups = "drop")
    lev <- tryCatch(rstatix::levene_test(d, value ~ group)$p, error = function(e) NA_real_)
    normal <- all(is.na(sh$p) | sh$p > 0.05)
    if (input$param == "auto") {
      # small replicate n -> parametric on plate means (Shapiro unreliable + non-parametric underpowered;
      # Mann-Whitney can't reach p<0.05 at 3 vs 3). SuperPlots (Lord 2020; Kenny & Schoen 2021).
      if (is.finite(min_n) && min_n < 8) TRUE else (normal && (is.na(lev) || lev > 0.05))
    } else input$param == "parametric"
  })

  stat_test <- reactive({
    d <- test_dat(); req(nlevels(droplevels(d$group)) >= 2)
    d$group <- droplevels(d$group)
    k <- nlevels(d$group); param <- use_param()
    tryCatch({
      if (k == 2) {
        if (param) d %>% t_test(value ~ group) else d %>% wilcox_test(value ~ group)
      } else {
        if (param) d %>% tukey_hsd(value ~ group) else d %>% dunn_test(value ~ group, p.adjust.method = "holm")
      }
    }, error = function(e) NULL)
  })

  omni_test <- reactive({
    d <- test_dat(); d$group <- droplevels(d$group)
    k <- nlevels(d$group); param <- use_param()
    if (k < 2) return(list(name = "n/a", p = NA))
    if (k == 2) {
      r <- if (param) t.test(value ~ group, d) else suppressWarnings(wilcox.test(value ~ group, d))
      list(name = if (param) "Welch t-test" else "Mann-Whitney U", p = r$p.value, param = param)
    } else {
      r <- if (param) summary(aov(value ~ group, d))[[1]][["Pr(>F)"]][1]
           else kruskal.test(value ~ group, d)$p.value
      list(name = if (param) "one-way ANOVA" else "Kruskal-Wallis", p = r, param = param)
    }
  })

  palette_vec <- reactive({
    if (!is.null(input$palette_name) && input$palette_name != "" &&
        !is.null(PALETTES[[input$palette_name]]))
      return(PALETTES[[input$palette_name]])
    txt <- if (is.null(input$palette)) "" else input$palette
    p <- trimws(strsplit(txt, ",")[[1]]); p <- p[p != ""]
    if (length(p)) p else OKABE_ITO
  })

  # --- Colour registry: sample colours keyed by NAME ------------------------------------------
  # It outlives the CSV: loading another file keeps every name it has seen and gives a new name
  # the first colour of the current palette no other name uses. Choosing another colour theme
  # (or typing custom hex) reassigns the names loaded now in level order from the new palette;
  # names not loaded keep theirs. A paper style merges its sample_palette in by name.
  colour_registry <- reactiveVal(setNames(character(0), character(0)))
  paper_palette_given <- reactiveVal(FALSE)   # a paper style named colours: colour the violins
  current_levels <- reactive({
    d <- tryCatch(dat(), error = function(e) NULL)
    if (is.null(d)) character(0) else levels(d$group)
  })
  palette_seen <- NULL                        # the palette the registry was last assigned from
  observe({
    lv <- current_levels(); pal <- palette_vec()
    old <- isolate(colour_registry()); reg <- old
    if (!is.null(palette_seen) && !identical(pal, palette_seen) && length(lv))
      reg[lv] <- rep(pal, length.out = length(lv))
    palette_seen <<- pal
    reg <- extend_colour_registry(reg, lv, pal)
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
  # figure has always had when an input is blank or invalid
  look <- reactive({
    bs <- suppressWarnings(as.numeric(input$base_size))
    if (length(bs) != 1 || !is.finite(bs) || bs <= 0) bs <- 14
    col <- trimws(if (is.null(input$axis_color)) "" else as.character(input$axis_color)[1])
    if (is.na(col) || !nzchar(col) || inherits(try(grDevices::col2rgb(col), silent = TRUE), "try-error"))
      col <- "#33413c"
    lw <- suppressWarnings(as.numeric(input$axis_line_width))
    if (length(lw) != 1 || !is.finite(lw) || lw < 0) lw <- 0.6
    list(base_size = bs, family = drawn_family(font_resolved()$family), axis_color = col,
         axis_line_width = lw)
  })

  # THE colour mapping of the figure (and of its legend key)
  style <- reactive({
    d <- dat(); req(nrow(d) > 0)
    chose_theme <- (!is.null(input$palette_name) && input$palette_name != "" &&
                    !is.null(PALETTES[[input$palette_name]])) ||
                   nzchar(trimws(if (is.null(input$palette)) "" else input$palette)) ||
                   isTRUE(paper_palette_given())
    # colour the violins by group when the user asks for group fill, OR picks a colour theme
    # (otherwise the theme silently does nothing under the neutral grey SuperPlot default),
    # OR a paper style named the sample colours; otherwise keep the grey SuperPlot violin so
    # the plate colours carry the hue.
    style_map(d, colour_registry(), input$vfill, chose_theme, isTRUE(has_rep()), palette_vec())
  })
  key <- reactive(key_entries(style()))

  # --- Paper style: the paper_style.json CFU Plot Studio 0.4.0 writes, applied at start ------
  # Only the keys both apps share are taken (an explicit allowlist); everything else in the file
  # (plot_title, legend_position, x_angle, download_width, y_min, time_palette, ...) is ignored.
  paper_style_status <- reactiveVal("")
  paper_style_applied <- reactiveVal(list(inputs = list(), sample_palette = list()))
  output$paper_style_status <- renderText(paper_style_status())
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
    valid_col <- function(x) is.character(x) && length(x) == 1 && !is.na(x) && nzchar(x) &&
      !inherits(try(grDevices::col2rgb(x), silent = TRUE), "try-error")
    applied <- list()
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
    }
    fs <- suppressWarnings(as.numeric(scalar(s$font_size)))             # font_size -> base_size
    if (length(fs) == 1 && is.finite(fs) && fs > 0) {
      updateNumericInput(session, "base_size", value = fs); applied$base_size <- fs
    }
    ac <- scalar(s$axis_color)                                          # axis_color -> axis_color
    if (valid_col(ac)) { updateTextInput(session, "axis_color", value = ac); applied$axis_color <- ac }
    lw <- suppressWarnings(as.numeric(scalar(s$axis_line_width)))       # axis_line_width -> same
    if (length(lw) == 1 && is.finite(lw) && lw >= 0) {
      updateNumericInput(session, "axis_line_width", value = lw); applied$axis_line_width <- lw
    }
    # sample_palette (name -> hex) merges into the registry BY NAME; names the data lacks are
    # kept, so one style can name every strain of the paper. {} changes nothing.
    pal <- unlist(s$sample_palette); kept <- list()
    if (length(pal) && !is.null(names(pal))) {
      reg <- isolate(colour_registry())
      for (nm in names(pal)) {
        hx <- as.character(pal[[nm]])
        if (nzchar(nm) && valid_col(hx)) { reg[[nm]] <- hx; kept[[nm]] <- hx }
      }
      if (length(kept)) { colour_registry(reg); paper_palette_given(TRUE) }
    }
    paper_style_applied(list(inputs = applied, sample_palette = kept))
    paper_style_status(paste0("Paper style: ", path, ", saved ",
                              if (!is.null(style$created_at)) style$created_at else "at an unknown time"))
    invisible(applied)
  }
  # after the first flush, so the inputs the style updates exist in the page
  session$onFlushed(function() isolate(load_paper_style()), once = TRUE)

  build_main <- reactive({
    d <- dat(); req(nrow(d) > 0)
    sm <- style(); lk <- look()         # colours by name; font, base size, axis colour + width
    gpal <- unname(sm$gcol)
    superplot <- sm$superplot           # Violin SuperPlot when we have >=2 plates per group
    neutral_violin <- sm$neutral
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
    if (input$show_points) {
      if (superplot)
        g <- g + geom_jitter(aes(color = replicate), width = 0.09, height = 0, size = 1.5, alpha = 0.5)
      else
        g <- g + geom_jitter(color = gpal[1], width = 0.09, height = 0, size = 1.5, alpha = 0.45)
    }
    if (superplot) {
      rm <- rep_means()
      fdata <- summary_fun(input$center, input$error)
      cfun  <- if (input$center == "median") stats::median else base::mean
      g <- g +
        stat_summary(data = rm, aes(group, value), fun.data = fdata, geom = "errorbar",
                     width = 0, linewidth = 0.7, color = "#12211d") +
        stat_summary(data = rm, aes(group, value), fun = cfun, geom = "crossbar",
                     width = 0.34, linewidth = 0.7, color = "#12211d", fatten = 0) +
        geom_point(data = rm, aes(group, value, fill = replicate), shape = 21,
                   size = 4.2, color = "#12211d", stroke = 0.9) +
        scale_fill_manual(values = sm$rcol, name = "plate", guide = "none") +
        scale_color_manual(values = sm$rcol, name = "plate", guide = "none")
    } else {
      # no replicates: a THIN, unfilled box (median + IQR) — lines only, not a filled rectangle
      g <- g + geom_boxplot(width = 0.12, outlier.shape = NA, fill = NA,
                            color = "#33413c", linewidth = 0.5)
    }
    g <- g +
      labs(title = if (nchar(input$title)) input$title else NULL,
           y = if (nchar(input$ylab)) input$ylab else metric_name(),
           x = if (nchar(input$xlab)) input$xlab else NULL) +
      theme_classic(base_size = lk$base_size, base_family = lk$family) +
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
    if (isTRUE(input$show_n)) {
      ns <- dplyr::count(d, group)
      g <- g + geom_text(data = ns, aes(x = group, y = Inf, label = paste0("n = ", n)),
                         vjust = 1.4, size = 3.3, fontface = "bold", color = "#33413c",
                         family = lk$family, inherit.aes = FALSE) +
        coord_cartesian(clip = "off")
    }
    if (input$log_y) g <- g + scale_y_log10()
    if (input$show_sig) {
      st <- stat_test()
      if (!is.null(st) && nrow(st) > 0) {
        st <- tryCatch(st %>% add_xy_position(x = "group"), error = function(e) NULL)
        if (!is.null(st)) {
          has_sig <- "p.adj.signif" %in% names(st) || "p.signif" %in% names(st)
          lab <- if ("p.adj.signif" %in% names(st)) "p.adj.signif"
                 else if ("p.adj" %in% names(st)) "p.adj" else "p"
          br <- tryCatch(stat_pvalue_manual(st, label = lab, tip.length = 0.01,
                          hide.ns = has_sig, inherit.aes = FALSE, family = lk$family),
                         error = function(e) NULL)       # family reaches geom_bracket via ...
          g <- g + br
        }
      }
    }
    g
  })

  # the figure: the main plot, plus the legend key beside it when "Place key on figure" is on --
  # the very same key_plot() the "Legend key" download saves
  build_plot <- reactive({
    g <- build_main(); e <- key(); lk <- look()
    if (!isTRUE(input$place_key) || !nrow(e)) return(g)
    ks <- key_size(e, lk$base_size); kw <- ks[["width"]]; kh <- ks[["height"]]
    side <- ggpubr::ggarrange(key_plot(e, lk$base_size, lk$family), NULL, ncol = 1,  # key at its own size, top-right
                              heights = c(kh, max(0.1, input$height - kh)))
    ggpubr::ggarrange(g, side, widths = c(max(1, input$width - kw), kw))
  })

  output$violin <- renderPlot({ build_plot() }, res = 96)
  output$key_text <- renderText({ s <- text_starter(key()); if (nzchar(s)) s else "(no sample colours to key)" })

  summ_group <- reactive({
    d <- dat()
    d %>% group_by(group) %>%
      summarise(n = n(), n_plates = length(unique(replicate[!is.na(replicate)])),
                mean = mean(value), sd = sd(value), sem = sd(value) / sqrt(n()),
                median = median(value), q1 = quantile(value, .25), q3 = quantile(value, .75),
                min = min(value), max = max(value),
                cv_pct = 100 * sd(value) / mean(value), .groups = "drop") %>%
      mutate(across(where(is.numeric), ~round(., 4)))
  })

  output$summary_group <- renderDT(datatable(summ_group(), options = list(dom = "t")))
  output$summary_rep <- renderDT({
    if (!has_rep()) return(datatable(data.frame(note = "no replicate column"), options = list(dom = "t")))
    datatable(rep_means() %>% mutate(value = round(value, 4)), options = list(dom = "t"))
  })
  output$pairwise <- renderDT({
    st <- stat_test(); if (is.null(st)) return(NULL)
    st <- as.data.frame(st)
    d <- test_dat(); gm <- tapply(d$value, d$group, mean)
    if (all(c("group1", "group2") %in% names(st))) {
      st$mean_a <- round(as.numeric(gm[st$group1]), 4)
      st$mean_b <- round(as.numeric(gm[st$group2]), 4)
      st$mean_diff <- round(st$mean_a - st$mean_b, 4)
    }
    keep <- intersect(c("group1", "group2", "mean_a", "mean_b", "mean_diff", "p", "p.adj",
                        "p.adj.signif", "statistic"), names(st))
    datatable(st[, keep, drop = FALSE], options = list(dom = "t"))
  })
  output$omni <- renderText({
    o <- omni_test(); u <- use_unit()
    d <- test_dat(); min_n <- suppressWarnings(min(table(droplevels(factor(d$group)))))
    msg <- sprintf("%s: p = %s  (unit: %s, parametric = %s, min n = %d/group)",
                   o$name, ifelse(is.na(o$p), "n/a", ifelse(o$p < 1e-3, "< 0.001", formatC(o$p, format = "f", digits = 3))),
                   u, isTRUE(o$param), ifelse(is.finite(min_n), min_n, 0))
    warns <- character(0)
    if (u == "plaque")
      warns <- c(warns, "unit = plaque: pseudoreplication — add a plate/replicate column for a valid test.")
    if (!isTRUE(o$param) && is.finite(min_n) && min_n < 4)
      warns <- c(warns, "non-parametric with <4/group: p<0.05 may be unreachable (Mann-Whitney) or floored (Kruskal-Wallis).")
    if (length(warns)) msg <- paste0(msg, "\n\nWARNINGS:\n- ", paste(warns, collapse = "\n- "))
    msg
  })
  output$sentence <- renderText({
    d <- dat(); o <- omni_test(); s <- summ_group()
    if (nrow(s) == 2) {
      sprintf("%s in %s was %.2f ± %.2f (n=%d%s) vs %s %.2f ± %.2f (n=%d%s); %s p = %s.",
              metric_name(), s$group[1], s$mean[1], s$sd[1], s$n[1],
              ifelse(has_rep(), sprintf(", %d plates", s$n_plates[1]), ""),
              s$group[2], s$mean[2], s$sd[2], s$n[2],
              ifelse(has_rep(), sprintf(", %d plates", s$n_plates[2]), ""),
              o$name, ifelse(o$p < 1e-3, "< 0.001", formatC(o$p, format = "f", digits = 3)))
    } else {
      sprintf("%s across %d groups: %s p = %s (unit: %s; the plate is the experimental unit).",
              metric_name(), nrow(s), o$name,
              ifelse(is.na(o$p), "n/a", formatC(o$p, format = "f", digits = 3)), use_unit())
    }
  })

  dl <- function(ext, dev) downloadHandler(
    filename = function() sprintf("violin_%s.%s", metric_name(), ext),
    content = function(f) ggsave(f, build_plot(), width = input$width, height = input$height,
                                 dpi = input$dpi, device = dev))
  output$dl_png <- dl("png", "png")
  output$dl_svg <- dl("svg", svglite::svglite)
  output$dl_pdf <- dl("pdf", "pdf")
  output$dl_key <- downloadHandler(
    filename = function() sprintf("violin_%s_legend_key.zip", metric_name()),
    content = function(f) {
      e <- key(); req(nrow(e) > 0)
      tmp <- tempfile("key"); dir.create(tmp)
      base <- file.path(tmp, sprintf("violin_%s", metric_name()))
      lk <- look()
      files <- write_key_files(e, base, input$dpi, lk$base_size, lk$family)
      utils::zip(f, files, flags = "-j")
    })
  output$dl_sumg <- downloadHandler("summary_by_group.csv",
    content = function(f) write_csv(summ_group(), f))
  output$dl_sumr <- downloadHandler("summary_by_replicate.csv",
    content = function(f) write_csv(if (has_rep()) rep_means() else data.frame(), f))
}

shinyApp(ui, server)
