---
name: file-to-markdown
description: >
  Convert documents and images to Markdown.
  Documents (PDF, DOCX, PPTX, XLSX, XLS) use Docling for text extraction.
  Images (PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF) use a two-pass sliding-window
  strategy — an overview pass for structural layout followed by a detail pass
  that tiles the image and reads each tile via LLM vision to guarantee full
  coverage of every element.
compatibility:
  - Kiro
  - Claude Code
  - Cursor
metadata:
  category: document-processing
  complexity: intermediate
  requires-python: ">=3.10"
  requires-packages:
    - docling
    - Pillow
---

# File to Markdown Skill

Converts documents and images to Markdown.

| File type | Strategy |
| --------- | -------- |
| PDF, DOCX, PPTX, XLSX, XLS | Docling text extraction (`scripts/convert.py`) |
| PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF | Two-pass sliding-window vision analysis (`scripts/split_image.py`) |

---

## Prerequisites

**Python ≥ 3.10** with the following packages installed:

```bash
pip install docling Pillow
# or
uv pip install docling Pillow
```

> **Note:** First Docling run downloads ML models (~1–2 min). Subsequent runs are fast.

---

## Document Workflow (PDF, DOCX, PPTX, XLSX, XLS)

### Step 1 — Verify environment

```bash
python -c "import docling; print('ok')"
```

### Step 2 — Convert

```bash
python scripts/convert.py "<input-file>"
```

For multiple files:

```bash
for f in docs/*.pdf; do python scripts/convert.py "$f"; done
```

The script writes `<basename>.md` to the same directory as the input.

### Step 3 — Parse output

| Marker | Meaning |
| ------ | ------- |
| `OUTPUT: <path>` | Path to the written Markdown file |
| `LINES: <n>` | Line count |
| `WORDS: <n>` | Word count |
| `WARNING: <msg>` | Non-fatal issue (e.g., sparse text) |

### Step 4 — Save and report

Tell the user the output file path and word/line counts. Surface any `WARNING:` so
the user can decide whether the output needs manual review.

**Edge cases:**

| Situation | Action |
| --------- | ------ |
| First Docling run | Warn user about model download (1–2 min); one-time only |
| Scanned PDF | Docling applies OCR automatically; output may be lower quality |
| Password-protected file | Error with suggestion to remove password first |
| XLSX with multiple sheets | Docling outputs each sheet as a separate section |
| PPTX with embedded images | Text extracted; images are noted but not converted |

---

## Image Workflow (PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF)

Images are processed using a two-pass sliding-window strategy. A naive single-pass
extraction risks bisecting diagram elements across tile boundaries. This skill avoids
that with two mechanisms:

1. **Overview pass** — A single downscaled image gives the LLM the full structural
   layout (positions, groupings, flow direction) without needing fine detail.
2. **Sliding-window detail pass** — A fixed-size viewport moves across the image with
   a stride smaller than the viewport. Every point is covered by at least two
   overlapping windows, so every element appears fully intact in at least one tile.

An automatic **pre-scaling** step handles source images whose longest dimension
exceeds 8000 px or whose tiles would exceed 50 MB. The source is downscaled to a
working size before tiling; all manifests record the coordinate mapping.

### Step 1 — Validate and recommend settings

Confirm the file exists and is a supported image format, then run:

```bash
python scripts/split_image.py recommend --input "<source-image-path>"
```

This returns source dimensions, whether a single pass suffices, and recommended
viewport/stride settings. If `needs_prescale: true`, inform the user that the source
will be automatically downscaled before tiling (this is transparent to subsequent steps).

If both dimensions are ≤ 1200 px, skip to **Step 3** using the original image directly.

### Step 2 — Split image (two passes)

Use the OS temp directory or a project-local scratch folder for tile output.

**Pass 1 — Overview:**

```bash
python scripts/split_image.py overview \
  --input "<source-image-path>" \
  --output-dir "<temp-dir>/tiles/" \
  --max-dim 1200 \
  [--max-source-dim 8000]
```

Produces `overview.png` and `overview_manifest.json` (includes scale factor and
pre-scale metadata if applicable).

**Pass 2 — Detail tiles:**

```bash
python scripts/split_image.py detail \
  --input "<source-image-path>" \
  --output-dir "<temp-dir>/tiles/" \
  --viewport 1200 \
  --stride 800 \
  [--max-source-dim 8000] \
  [--focus-regions focus_regions.json]
```

Produces `tile_W0_R<row>_C<col>.png` tiles and `detail_manifest.json` with per-tile
crop coordinates.

If the overview analysis (Step 3a) identifies dense or complex focus regions, write
them to `focus_regions.json` as `[{x, y, w, h}, ...]` in source-image coordinates
and re-run the detail command with `--focus-regions`.

### Step 3 — Analyze with LLM vision

#### Step 3a — Overview analysis

Read the overview image and extract:

- **Diagram type** — architecture, event-storming, process-flow, domain-model, conceptual
- **Overall layout** — flow direction (left-to-right, top-to-bottom, radial), major sections
- **Element inventory** — approximate count and types of elements
- **Spatial groups** — clusters, swim lanes, bounded-context boundaries, containers
- **Focus regions** — dense or complex areas needing targeted detail extraction

Store this as the **structural map** — it provides global context that individual
tiles lack.

#### Step 3b — Detail tile analysis

For each tile listed in `detail_manifest.json`, read the tile image and extract
content. Provide the structural map and tile position metadata as context so the LLM
knows where in the overall diagram the tile sits.

Extract according to diagram type:

**Architecture diagrams:**

- Components (name, type, technology if visible)
- Relationships (source → target, protocol/pattern label)
- Boundaries / containers (what they enclose)
- Annotations and labels

**Event storming boards:**

- Sticky notes by color:
  - Orange → domain events
  - Blue → commands
  - Yellow → aggregates
  - Lilac/purple → policies
  - Red/pink → hot spots
  - Green → read models
  - White/other → external systems, actors, notes
- Spatial position: left-to-right = temporal sequence; vertical stacking =
  command → event → policy chains
- Swim lanes and explicit boundary lines

**Process flow diagrams:**

- Steps (name, actor, description), decisions (condition, branches), sequence order

**Domain model diagrams:**

- Entities (name, key attributes), relationships (type, cardinality, direction),
  aggregate boundaries

**General / conceptual diagrams:**

- All visible text labels, groupings, arrows, and annotations; spatial relationships
  and hierarchy

For each tile, record: `tile_id`, `crop_box`, `position_label`, `elements_found`
(list with type and content), `confidence` (high / medium / low), and
`is_duplicate_candidate` flag for elements near tile edges.

### Step 4 — Reconcile and merge

1. **Overlap deduplication** — Identify elements extracted from multiple tiles.
   For each, treat the tile where it appears most centrally (farthest from all edges)
   as canonical; discard edge-proximity duplicates.
2. **Structural-map anchoring** — Cross-reference detail extractions against the
   overview structural map. Flag any overview groups with no detail coverage.
3. **Relationship completion** — Reconnect arrows that span multiple tiles using the
   overview's long-range connections and detail tile endpoint labels.
4. **Sequence reconstruction** — Assign each element a global flow position:
   left-to-right flows → sort by X; top-to-bottom → sort by Y; event storming →
   reconstruct timeline from horizontal position and vertical chains.
5. **Confidence assessment:**
   - High: digital export, clean lines, legible text, overview and detail consistent
   - Medium: whiteboard photo with good lighting, or minor inconsistencies
   - Low: blurry, cluttered, or significant gaps between overview and detail coverage

### Step 5 — Generate structured markdown output

Produce a markdown file with YAML frontmatter:

```yaml
---
title: "<Diagram title or user-provided name>"
source-file: "<original image filename>"
content-type: image
content-category: <architecture-diagram | event-storming-big-picture | event-storming-design-level | process-diagram | domain-model | conceptual>
ingestion-date: "<ISO-8601 datetime>"
diagram-type: "<detected or user-specified type>"
processing:
  strategy: two-pass-sliding-window
  overview-scale-factor: <scale>
  viewport: <px>
  stride: <px>
  overlap-pct: <computed>
  sliding-window-tiles: <count>
  focus-region-tiles: <count>
  total-tiles-analyzed: <count>
ingestion-quality:
  extraction-confidence: <high | medium | low>
  completeness: <complete | partial | minimal>
  source-quality: <high | medium | low>
  requires-review: <true | false>
  quality-notes: "<specific observations>"
---
```

Markdown body structure:

```markdown
# <Diagram Title>

## Overview
<1–3 sentence summary derived from the overview pass>

## Diagram Type
<Detected type and notation if identifiable>

## Structural Layout
<Spatial organization — flow direction, grouping strategy, major sections>

## Elements

### Components / Entities / Events
| # | Name | Type | Description | Source Region | Confidence |
|---|------|------|-------------|---------------|------------|

### Relationships / Flows
| Source | Target | Type/Label | Direction |
|--------|--------|------------|-----------|

### Boundaries / Groups
<Swim lanes, bounded contexts, containers>

### Annotations / Notes
<Free-text annotations, legends, hot spots>

## Ambiguities and Review Items
<Elements that could not be confidently extracted; each marked requires-review: true>

## Downstream Usage Guidance
<Recommendations for which SDLC commands or processes can consume this output>
```

### Step 6 — Save and report

Resolve output path in this priority order:

1. **User-specified path** — if provided, use it.
2. **Project convention** — check for `KNOWLEDGE_BASE_DIR` env var, `.kiro/steering/`
   config, or equivalent project convention.
3. **Prompt the user** — if neither yields a path, ask before writing.

Organize into category subdirectories (e.g., `event-storming/big-picture/`,
`architecture/`) if the target already follows that convention; otherwise save flat.

Clean up tile images from the processing directory (or archive if user requests
preservation).

Present a summary to the user:

- Element count by type
- Confidence distribution
- Items flagged for review
- Tiles analyzed (sliding window + focus regions)
- Recommended next steps

---

## Handling Ambiguity

- Extract what is visible and mark unclear elements with `requires-review: true`.
- Capture multiple interpretations when spatial relationships are ambiguous.
- Flag event storming colors that are indistinguishable (e.g., bad photo lighting).
- Flag discrepancies between overview and detail passes.
- **Never fabricate elements that are not visible in the source image.**

---

## Configuration Defaults

| Parameter        | Default  | Notes                                            |
|------------------|----------|--------------------------------------------------|
| Overview max dim | 1200 px  | Downscale target for structural analysis         |
| Viewport         | 1200 px  | Sliding window size for detail pass              |
| Stride           | 800 px   | Step size; overlap = (viewport−stride)/viewport  |
| Effective overlap| ~33%     | At default settings                              |
| Max source dim   | 8000 px  | Auto-downscale source images above this          |
| Max tile size    | 50 MB    | Triggers pre-scale if tiles would exceed this    |
| Min stride       | 200 px   | Floor to prevent excessive tile counts           |
| Max tile warning | 100      | Warn if detail pass exceeds this count           |
| Tile format      | PNG      | Lossless for best extraction quality             |
| Output format    | Markdown | With YAML frontmatter                            |

---

## Error Handling

| Error | Action |
| ----- | ------ |
| `docling` not installed | Print install command and exit 1 |
| `Pillow` not installed | Print install command and exit 1 |
| File not found | Print `ERROR: File not found: <path>` and exit 1 |
| Unsupported file type | Print `ERROR: Unsupported file type` with supported list |
| Tile read fails | Log failure, skip tile, note gap under Ambiguities in output |
| Image too large after pre-scale | Suggest reducing `--max-source-dim` or increasing stride |
| Detail pass > 100 tiles | Warn user; suggest increasing stride or reducing viewport |
