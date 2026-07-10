# app.R — Plaque Stats & Violins (R-Shiny)
# ---------------------------------------------------------------------------------------------
# Interactive companion to plaque_stats.py: upload a tidy CSV of grouped plaque measurements,
# get publication-ready, customizable violin plots + statistics + data summaries, and download
# the figure (PNG/SVG/PDF) and tables. Uses the SAME data format as the Python script.
#
# Run:   R -e "shiny::runApp('plaque_stats', launch.browser=TRUE)"
#   or open app.R in RStudio and click "Run App".
# First time only, install packages:
#   install.packages(c("shiny","ggplot2","dplyr","tidyr","readr","DT","rstatix","ggpubr","scales","svglite"))
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

OKABE_ITO <- c("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
               "#D55E00", "#F0E442", "#999999", "#000000")
# muted palette for REPLICATES (plates): points + plate means are coloured by plate (SuperPlot)
REP_PALETTE <- c("#4C6E9C", "#E0A458", "#6AAA64", "#B65C5C", "#8A78B0",
                 "#4FA3A5", "#C77CB5", "#9A8C6B", "#6C6C6C")

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
                    "coloured by group" = "group")),
      checkboxInput("show_sig", "Significance brackets", TRUE),
      checkboxInput("log_y", "Log y-axis", FALSE),
      tags$hr(),
      textInput("title", "Title", ""),
      textInput("ylab", "Y-axis label", ""),
      textInput("xlab", "X-axis label", ""),
      textInput("order", "Group order (comma-sep, optional)", ""),
      textInput("palette", "Palette (comma-sep hex, optional)", ""),
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
          downloadButton("dl_pdf", "PDF (editable)")),
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
    sh <- d %>% group_by(group) %>%
      summarise(p = tryCatch(shapiro.test(value)$p.value, error = function(e) NA_real_), .groups = "drop")
    lev <- tryCatch(rstatix::levene_test(d, value ~ group)$p, error = function(e) NA_real_)
    normal <- all(is.na(sh$p) | sh$p > 0.05)
    if (input$param == "auto") normal && (is.na(lev) || lev > 0.05)
    else input$param == "parametric"
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
    p <- trimws(strsplit(input$palette, ",")[[1]]); p <- p[p != ""]
    if (length(p)) p else OKABE_ITO
  })

  build_plot <- reactive({
    d <- dat(); req(nrow(d) > 0)
    gpal <- rep(palette_vec(), length.out = nlevels(d$group))
    superplot <- isTRUE(has_rep())      # Violin SuperPlot when we have >=2 plates per group
    # neutral grey violin when plate colours carry the hue (forced in SuperPlot mode to keep one
    # fill scale for the plate legend); group-coloured only when there are no plate points
    neutral_violin <- superplot || input$vfill == "neutral"
    g <- ggplot(d, aes(group, value))
    if (neutral_violin) {
      g <- g + geom_violin(fill = "#b9c2bd", color = "#6f7b74", alpha = 0.38,
                           width = 0.85, trim = TRUE, linewidth = 0.5)
    } else {
      g <- g + geom_violin(aes(fill = group), color = NA, alpha = 0.25, width = 0.85, trim = TRUE) +
        scale_fill_manual(values = gpal, guide = "none")
    }
    if (input$show_points) {
      if (superplot)
        g <- g + geom_jitter(aes(color = replicate), width = 0.09, height = 0, size = 1.5, alpha = 0.5)
      else
        g <- g + geom_jitter(color = gpal[1], width = 0.09, height = 0, size = 1.5, alpha = 0.45)
    }
    if (superplot) {
      rm <- rep_means()
      g <- g +
        stat_summary(data = rm, aes(group, value), fun.data = mean_se, geom = "errorbar",
                     width = 0, linewidth = 0.7, color = "#12211d") +
        stat_summary(data = rm, aes(group, value), fun = mean, geom = "crossbar",
                     width = 0.34, linewidth = 0.7, color = "#12211d", fatten = 0) +
        geom_point(data = rm, aes(group, value, fill = replicate), shape = 21,
                   size = 4.2, color = "#12211d", stroke = 0.9) +
        scale_fill_manual(values = REP_PALETTE, name = "plate") +
        scale_color_manual(values = REP_PALETTE, name = "plate")
    } else {
      # no replicates: a THIN, unfilled box (median + IQR) — lines only, not a filled rectangle
      g <- g + geom_boxplot(width = 0.12, outlier.shape = NA, fill = NA,
                            color = "#33413c", linewidth = 0.5)
    }
    g <- g +
      labs(title = if (nchar(input$title)) input$title else NULL,
           y = if (nchar(input$ylab)) input$ylab else metric_name(),
           x = if (nchar(input$xlab)) input$xlab else NULL) +
      theme_classic(base_size = 14) +
      theme(plot.title = element_text(face = "bold"),
            legend.position = if (superplot) "right" else "none",
            axis.line = element_line(linewidth = 0.6, color = "#33413c"),
            axis.ticks = element_line(linewidth = 0.6, color = "#33413c"))
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
                          hide.ns = has_sig, inherit.aes = FALSE), error = function(e) NULL)
          g <- g + br
        }
      }
    }
    g
  })

  output$violin <- renderPlot({ build_plot() }, res = 96)

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
    keep <- intersect(c("group1", "group2", "p", "p.adj", "p.adj.signif", "statistic", "estimate"), names(st))
    datatable(as.data.frame(st)[, keep, drop = FALSE], options = list(dom = "t"))
  })
  output$omni <- renderText({
    o <- omni_test()
    sprintf("%s: p = %s  (unit: %s, parametric = %s)",
            o$name, ifelse(is.na(o$p), "n/a", ifelse(o$p < 1e-3, "< 0.001", formatC(o$p, format = "f", digits = 3))),
            use_unit(), isTRUE(o$param))
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
  output$dl_sumg <- downloadHandler("summary_by_group.csv",
    content = function(f) write_csv(summ_group(), f))
  output$dl_sumr <- downloadHandler("summary_by_replicate.csv",
    content = function(f) write_csv(if (has_rep()) rep_means() else data.frame(), f))
}

shinyApp(ui, server)
