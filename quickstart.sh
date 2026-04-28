#!/usr/bin/env bash
# quickstart.sh — 60-second proof of life for dropkit.
#
# What this does:
#   1. Verifies Python 3.10+
#   2. Installs Pillow (lightweight, ~10s) into the current environment
#   3. Generates a small sample diagram at examples/diagram.png
#   4. Runs the file-to-markdown image analyzer in two modes:
#        - recommend: prints suggested viewport/stride for the input
#        - overview:  writes a downscaled overview + manifest JSON
#
# What this does NOT do:
#   - Talk to Claude / OpenAI / any model. Pure local toolchain check.
#   - Install Docling (needed for the document branch — PDF/DOCX/etc.).
#     The first Docling run downloads ~1–2 GB of ML models and takes a
#     couple of minutes; that's not what a quickstart should subject you
#     to. To exercise the document branch, see the file-to-markdown
#     section in README.md.
#   - Set up credentials for the authenticated skills (jira, jira-align,
#     confluence-crawler). Those have their own setup_credentials.sh
#     scripts, which prompt interactively when you actually need them.
#
# When this finishes successfully you have proof that the toolchain
# installs and the skill scripts run on your machine.

set -euo pipefail

cd "$(dirname "$0")"

# --- 1. Python --------------------------------------------------------------

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  PY="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$PY" ]]; then
  echo "error: python 3.10+ is required and was not found on PATH" >&2
  echo "       (set \$PYTHON to override, e.g. PYTHON=/opt/python3.12/bin/python3)" >&2
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "error: python 3.10+ required, found: $("$PY" --version 2>&1)" >&2
  exit 1
fi
echo "==> Python: $("$PY" --version)"

# --- 2. Install Pillow ------------------------------------------------------

echo "==> Installing Pillow (file-to-markdown image dep)..."
"$PY" -m pip install --quiet --upgrade Pillow

# --- 3. Generate a tiny sample diagram --------------------------------------

mkdir -p examples
echo "==> Generating examples/diagram.png..."
"$PY" - <<'PY'
from PIL import Image, ImageDraw

W, H = 1000, 500
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)

def box(x, y, w, h, label):
    d.rectangle([x, y, x + w, y + h], outline="black", width=3)
    # crude centered label
    bbox = d.textbbox((0, 0), label)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((x + (w - tw) / 2, y + (h - th) / 2), label, fill="black")

def arrow(x1, y, x2):
    d.line([(x1, y), (x2, y)], fill="black", width=3)
    d.polygon([(x2 - 10, y - 6), (x2, y), (x2 - 10, y + 6)], fill="black")

box(60, 200, 180, 100, "Client")
box(420, 200, 180, 100, "API Gateway")
box(780, 200, 180, 100, "Service")
arrow(240, 250, 420)
arrow(600, 250, 780)
d.text((100, 60), "dropkit quickstart sample diagram", fill="black")

img.save("examples/diagram.png")
print(f"   wrote examples/diagram.png ({W}x{H})")
PY

# --- 4. Exercise the file-to-markdown image scripts -------------------------

SPLIT="skills/converters/file-to-markdown/scripts/split_image.py"

echo "==> Running file-to-markdown 'recommend' (no LLM, just dimension analysis)..."
"$PY" "$SPLIT" recommend --input examples/diagram.png

echo
echo "==> Running file-to-markdown 'overview' (writes a downscaled overview)..."
mkdir -p examples/processing
"$PY" "$SPLIT" overview \
  --input examples/diagram.png \
  --output-dir examples/processing/ \
  --max-dim 1200

echo
echo "==> Done. Artifacts:"
ls -la examples/diagram.png examples/processing/overview.png examples/processing/overview_manifest.json 2>/dev/null || true
echo
echo "Next steps:"
echo "  - Install a skill into your IDE: see README.md → 'Installing a skill'"
echo "  - Try the document branch (PDF/DOCX/etc.):"
echo "      $PY -m pip install docling   # downloads ML models on first run"
echo "      $PY skills/converters/file-to-markdown/scripts/convert.py <your-file>"
echo "  - Try an authenticated skill (jira / jira-align / confluence-crawler):"
echo "      bash skills/integrations/jira/scripts/setup_credentials.sh"
