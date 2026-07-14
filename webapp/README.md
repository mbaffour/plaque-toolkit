# webapp/ — Plaque Toolkit on the web

A browser version of the **measurement** tool: upload a plate photo → set the dish size → detect &
measure with the **Precise** engine → download CSV / annotated image. It reuses the repo's validated
engine directly (`precise.pipeline.run_inprocess`), so results match the desktop Full app. Runs on any
device with a browser, including Chromebooks.

## Files
| file | what |
|---|---|
| `app.py` | the Shiny-for-Python app (UI + calls the engine) |
| `requirements.txt` | web deps (torch/torchvision come from the CPU index — see Dockerfile) |
| `Dockerfile` | Hugging Face Space (Docker SDK) — clones the repo + serves the app |
| `README_HF.md` | the README (with HF metadata header) to put on the Space |
| `DEPLOY.md` | **step-by-step** to put it online for free (Hugging Face Spaces) |

## Run it locally
From the repo root, in the `plaqueapp` env (has torch + the engine):
```bash
shiny run --launch-browser webapp/app.py
```
Then upload a plate, set the dish diameter, and click **Measure**.

## Put it online
See [`DEPLOY.md`](DEPLOY.md) — free Hugging Face Space, ~5 min of one-time setup, then a public URL
that works on any device (incl. Chrome OS).

## Notes
- **Precise on free CPU** works but is slow (~20–60 s/plate) and the host sleeps when idle.
- The interactive add/erase editing of the desktop app isn't in this v1 (auto-detect + download);
  it can be added later.
- Nothing is stored — each upload is processed in a temp folder and discarded.
