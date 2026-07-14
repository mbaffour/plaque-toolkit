---
title: Plaque Toolkit
emoji: 🧫
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: agpl-3.0
---

# Plaque Toolkit — measure plaques online

Upload a Petri-dish photo, set the dish diameter, and measure bacteriophage plaques with the
**Precise** engine (PST detector + PlaqSeg YOLO + a ResNet precision gate) — the same validated code
as the desktop app. Runs in any browser, including Chromebooks.

- **Size metric:** area-equivalent diameter, `d = 2·√(A/π)` (mm), validated against manual Fiji
  tracing (ICC 0.974).
- **Note:** CPU inference — ~20–60 s per plate, and the Space sleeps when idle (first run ~1 min).
- **Source & licence:** <https://github.com/mbaffour/plaque-toolkit> · AGPL-3.0 (weights CC-BY-NC-SA,
  non-commercial research). PlaqSeg detector: Carbon16/PlaqSegDesktop.

> This Space builds itself from the public repo (see `Dockerfile`). Nothing is stored — each image
> is processed in a temp folder and discarded.
