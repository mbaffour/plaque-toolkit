# Hugging Face Space (Docker SDK) — Plaque Toolkit: measure plaques online (Precise engine, CPU).
# The image clones the public toolkit repo (model weights ship as normal git files, ~70 MB) and
# serves webapp/app.py. Free CPU tier: works, ~20-60 s/plate, sleeps when idle.
FROM python:3.10-slim

# System libs: git to fetch the toolkit; libGL/glib for OpenCV.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

# Hugging Face runs containers as uid 1000 — set up a writable home.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    YOLO_CONFIG_DIR=/tmp/ultralytics
WORKDIR /home/user/app

# The toolkit (public). Weights are committed as normal files, so a plain shallow clone is enough.
RUN git clone --depth 1 https://github.com/mbaffour/plaque-toolkit.git .

# CPU PyTorch from the CPU wheel index; then the app deps; then re-pin numpy 1.26 LAST
# (opencv/ultralytics otherwise drag numpy 2.x back into the metadata).
RUN pip install --no-cache-dir --user torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r webapp/requirements.txt \
 && pip install --no-cache-dir --user "numpy==1.26.4"

EXPOSE 7860
CMD ["python", "-m", "shiny", "run", "--host", "0.0.0.0", "--port", "7860", "webapp/app.py"]
