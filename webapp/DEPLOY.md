# Deploy the web measurement app (Hugging Face Spaces)

This puts the **Precise** measurement engine online at a public URL that works on **any device**
(Windows, Mac, Chromebook, phone). Free, no credit card. You do this once; it then rebuilds itself
from the GitHub repo whenever you want.

The Space builds from **two files** (`Dockerfile` + `README.md`) — the Dockerfile clones the public
toolkit repo (weights included) and runs `webapp/app.py`. You don't upload the code or the weights.

## One-time setup (~5 minutes)

1. **Make a free account** at <https://huggingface.co/join>.
2. Go to <https://huggingface.co/new-space>:
   - **Owner:** you · **Space name:** e.g. `plaque-toolkit`
   - **License:** `agpl-3.0`
   - **SDK:** choose **Docker** → **Blank**
   - **Hardware:** **CPU basic (free)**
   - Create the Space.
3. In the new Space, open the **Files** tab → **Add file → Create a new file**, and create these two,
   copying the contents from this repo:
   - **`Dockerfile`** ← copy from [`webapp/Dockerfile`](Dockerfile)
   - **`README.md`** ← copy from [`webapp/README_HF.md`](README_HF.md) (note: it becomes `README.md`
     on the Space; the YAML header at the top is required)
4. The Space **builds automatically** (watch the **Logs** tab) — first build ~5–10 min while it
   installs PyTorch. When it says *Running*, open the **App** tab. Share that URL. ✅

## Using it
Upload a plate photo → set the **dish diameter (mm)** → **Measure** → read the annotated plate + the
per-plaque table → download CSV / image. First request wakes the Space (~1 min); then ~20–60 s/plate.

## Updating it
The Dockerfile clones `main` at build time, so to pick up repo changes just click
**Settings → Factory rebuild** on the Space. (Want automatic rebuilds on every push? Ask and I'll add
a GitHub Action that syncs the repo to the Space using an HF token you create.)

## Alternatives / notes
- **Faster but paid:** upgrade the Space hardware (e.g. a small GPU) for near-instant inference.
- **shinyapps.io** is easier for the *stats/agreement* apps (no torch) but too small for Precise.
- **Local, no server:** the desktop installer (`Plaque Toolkit (share)\PlaqueToolkitFullSetup.exe`)
  remains the fastest option for Windows users.
- **Licence:** hosting the AGPL-3.0 app publicly is fine because the source is public (this repo);
  the weights are CC-BY-NC-SA (non-commercial research use).
