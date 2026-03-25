#!/usr/bin/env python3
"""
split_image.py — Split a large image into an R×C grid of overlapping tiles.

Part of the diagram-ingestion skill. Designed to be invoked by Kiro, Claude
Code, or any agentic coding assistant that supports the agentskills.io
standard and the AWS Document Loader MCP server.

Usage:
    python scripts/split_image.py \
        --input diagram.png \
        --output-dir ./tiles \
        --rows 3 --cols 3 \
        --overlap 0.10

Outputs:
    - Numbered tile PNGs: tile_R0_C0.png … tile_R<n>_C<n>.png
    - tile_manifest.json with full metadata for downstream reconciliation
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print(
        "ERROR: Pillow is required. Install with:\n"
        "  pip install Pillow\n"
        "  uv pip install Pillow",
        file=sys.stderr,
    )
    sys.exit(1)


def validate_args(args: argparse.Namespace) -> None:
    src = Path(args.input)
    if not src.exists():
        sys.exit(f"ERROR: Input file not found: {src}")
    if not src.suffix.lower() in {
        ".png", ".jpg", ".jpeg", ".tiff", ".tif",
        ".bmp", ".webp", ".gif",
    }:
        sys.exit(f"ERROR: Unsupported image format: {src.suffix}")
    if args.rows < 3 or args.cols < 3:
        sys.exit("ERROR: Minimum grid size is 3×3.")
    if not 0.0 <= args.overlap < 0.5:
        sys.exit("ERROR: Overlap must be between 0.0 and 0.5.")


def split_image(
    input_path: Path,
    output_dir: Path,
    rows: int,
    cols: int,
    overlap: float,
) -> dict:
    """Split *input_path* into an rows×cols grid and return a manifest dict."""

    output_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(input_path)
    w, h = img.size

    # Base tile dimensions (before overlap)
    base_tw = w / cols
    base_th = h / rows

    # Overlap in pixels
    ov_x = int(base_tw * overlap)
    ov_y = int(base_th * overlap)

    tiles: list[dict] = []

    for r in range(rows):
        for c in range(cols):
            # Compute crop box with overlap bleed
            x0 = max(0, int(c * base_tw) - ov_x)
            y0 = max(0, int(r * base_th) - ov_y)
            x1 = min(w, int((c + 1) * base_tw) + ov_x)
            y1 = min(h, int((r + 1) * base_th) + ov_y)

            tile = img.crop((x0, y0, x1, y1))
            fname = f"tile_R{r}_C{c}.png"
            tile_path = output_dir / fname
            tile.save(tile_path, format="PNG")

            tiles.append({
                "filename": fname,
                "row": r,
                "col": c,
                "crop_box": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
                "position_label": _position_label(r, c, rows, cols),
            })

    manifest = {
        "source_image": str(input_path.resolve()),
        "source_dimensions": {"width": w, "height": h},
        "grid": {"rows": rows, "cols": cols},
        "overlap_pct": overlap,
        "overlap_px": {"x": ov_x, "y": ov_y},
        "tile_count": len(tiles),
        "output_dir": str(output_dir.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tiles": tiles,
    }

    manifest_path = output_dir / "tile_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def _position_label(r: int, c: int, rows: int, cols: int) -> str:
    """Human-readable position label for a tile."""
    v = "top" if r == 0 else ("bottom" if r == rows - 1 else "middle")
    h = "left" if c == 0 else ("right" if c == cols - 1 else "center")
    if v == "middle" and h == "center":
        return "center"
    return f"{v}-{h}"


def recommend_grid(width: int, height: int) -> tuple[int, int]:
    """Suggest a grid size based on image dimensions."""
    longer = max(width, height)
    if longer <= 1200:
        return (1, 1)  # single pass
    if longer <= 4000:
        return (3, 3)
    if longer <= 6000:
        return (4, 4)
    return (5, 5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split a large image into a grid of overlapping tiles.",
    )
    parser.add_argument("--input", required=True, help="Path to source image")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for output tiles and manifest",
    )
    parser.add_argument("--rows", type=int, default=3, help="Grid rows (min 3)")
    parser.add_argument("--cols", type=int, default=3, help="Grid cols (min 3)")
    parser.add_argument(
        "--overlap",
        type=float,
        default=0.10,
        help="Overlap fraction between tiles (0.0–0.5, default 0.10)",
    )
    parser.add_argument(
        "--recommend",
        action="store_true",
        help="Print recommended grid size and exit",
    )

    args = parser.parse_args()

    if args.recommend:
        src = Path(args.input)
        if not src.exists():
            sys.exit(f"ERROR: Input file not found: {src}")
        img = Image.open(src)
        rr, rc = recommend_grid(*img.size)
        print(json.dumps({
            "width": img.size[0],
            "height": img.size[1],
            "recommended_rows": rr,
            "recommended_cols": rc,
            "single_pass": rr == 1,
        }))
        return

    validate_args(args)

    manifest = split_image(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        rows=args.rows,
        cols=args.cols,
        overlap=args.overlap,
    )

    print(f"✓ Split into {manifest['tile_count']} tiles → {manifest['output_dir']}")
    print(f"  Grid: {manifest['grid']['rows']}×{manifest['grid']['cols']}")
    print(f"  Overlap: {manifest['overlap_pct']*100:.0f}% "
          f"({manifest['overlap_px']['x']}px × {manifest['overlap_px']['y']}px)")
    print(f"  Manifest: {manifest['output_dir']}/tile_manifest.json")


if __name__ == "__main__":
    main()