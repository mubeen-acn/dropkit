---
name: diagram-ingestion
description: >
  Ingest architecture diagrams, event storming boards, and event maps from
  images. Uses a two-pass strategy — an overview pass for structural layout
  analysis followed by a sliding-window detail pass that guarantees every
  element is fully captured in at least one tile. Reads each tile via the
  AWS Document Loader MCP server's read_image tool, assembles LLM-extracted
  content, and produces a structured markdown summary suitable as input to
  downstream SDLC artifacts (solution concepts, domain synthesis, architecture
  views, feature specs). Use when the user provides an image of an
  architecture diagram, event storming board, event map, process flow,
  domain model, or any visual artifact that needs to be converted into
  structured knowledge.
compatibility:
  - Kiro
  - Claude Code
  - Cursor
metadata:
  category: document-processing
  complexity: intermediate
  requires-mcp:
    - awslabs.document-loader-mcp-server
  requires-python: ">=3.10"
  requires-packages:
    - Pillow
---

# Diagram Ingestion Skill

Converts large architecture diagrams, event storming boards, and event maps
into structured markdown knowledge records using a two-pass analysis strategy
and the AWS Document Loader MCP server.

---

## Prerequisites

1. **AWS Document Loader MCP server** must be installed and enabled.
   MCP configuration (add to `.kiro/settings/mcp.json` or your client's
   `mcp.json`):

   ```json
   {
     "mcpServers": {
       "awslabs.document-loader-mcp-server": {
         "command": "uvx",
         "args": ["awslabs.document-loader-mcp-server@latest"],
         "env": {
           "FASTMCP_LOG_LEVEL": "ERROR"
         },
         "disabled": false,
         "autoApprove": ["read_image"]
       }
     }
   }
   ```

2. **Python ≥ 3.10** with `Pillow` installed.
   The helper script `scripts/split_image.py` handles image tiling.
   Install Pillow if not present: `pip install Pillow` or `uv pip install Pillow`.

---

## Why Two-Pass Sliding Window

A naive grid cut risks bisecting diagram elements — boxes, sticky notes,
arrows, labels — across tile boundaries, producing partial extractions that
are difficult to reconcile. This skill avoids that problem with two
mechanisms:

1. **Overview pass** — A single downscaled image gives the LLM the full
   structural layout (element positions, groupings, flow direction) without
   needing to read fine detail.
2. **Sliding-window detail pass** — A fixed-size viewport moves across the
   full-resolution image with a stride smaller than the viewport. Every
   point in the image is covered by at least two overlapping windows, so
   every element appears fully intact in at least one tile. The LLM
   extracts fine detail per tile, and deduplication reconciles the overlaps.

An optional **focus-region** mechanism lets the overview pass identify areas
that need targeted re-cropping (e.g., a dense cluster of sticky notes or a
complex integration boundary) for a third, precision pass.

An automatic **pre-scaling** step handles source images that are so large
that even individual tiles would exceed the MCP server's file-size limit
(default 50 MB) or the longest dimension exceeds a safe working threshold
(default 8000 px). When triggered, the source is downscaled to a working
size before any tiling occurs. The pre-scale metadata is recorded in all
manifests so downstream analysis can map coordinates back to the original
image if needed.

---

## Workflow

### Step 1 — Validate Input and Recommend Settings

When the user provides an image file path (or drops an image into chat):

1. Confirm the file exists and is a supported image format
   (PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF).
2. Run the recommend command to assess the image:
   ```bash
   python scripts/split_image.py recommend --input "<source-image-path>"
   ```
   This returns the source dimensions, whether a single pass suffices,
   recommended viewport/stride settings, and whether the image needs
   automatic pre-scaling (with the effective working dimensions after
   pre-scale).
3. If the recommend output shows `needs_prescale: true`, inform the user
   that the source image will be automatically downscaled before tiling.
   The pre-scale is transparent — all subsequent steps work on the
   working-size image, and manifests record the original-to-working
   coordinate mapping.
4. If the image is small enough for single-pass analysis
   (both dimensions ≤ 1200 px), skip directly to **Step 3** using the
   original image.
4. Otherwise, present the recommendation to the user and confirm:
   - **Viewport size** — the pixel dimensions of each analysis window
     (default 1200 px).
   - **Stride** — how far the window moves between captures (default 800 px).
     Smaller stride = more overlap = more tiles but better coverage.
   - **Max source dimension** — threshold above which the source is
     pre-scaled (default 8000 px). User can override if they want to
     preserve more resolution at the cost of more/larger tiles.
   - **Diagram type** — auto-detect or let user specify:
     architecture, event-storming, process-flow, domain-model, conceptual.

### Step 2 — Split Image (Two Passes)

All tile output goes to a transient working directory (e.g., OS temp
directory or a project-local scratch folder). Do NOT assume a fixed
workspace path — use the OS temp directory or ask the user if uncertain.

**Pass 1 — Overview:**

```bash
python scripts/split_image.py overview \
  --input "<source-image-path>" \
  --output-dir "<temp-working-dir>/tiles/" \
  --max-dim 1200 \
  [--max-source-dim 8000]
```

Produces `overview.png` — a single downscaled image — and
`overview_manifest.json` with scale factor metadata. If the source
exceeds `max-source-dim`, it is automatically pre-scaled first (recorded
in the manifest's `prescale` field).

**Pass 2 — Detail tiles:**

```bash
python scripts/split_image.py detail \
  --input "<source-image-path>" \
  --output-dir "<temp-working-dir>/tiles/" \
  --viewport 1200 \
  --stride 800 \
  [--max-source-dim 8000] \
  [--focus-regions focus_regions.json]
```

Produces numbered tiles (`tile_W0_R<row>_C<col>.png`) and
`detail_manifest.json` with per-tile crop coordinates.

If the overview analysis (Step 3a) identifies focus regions, write them
to a `focus_regions.json` file and re-run the detail command with
`--focus-regions` to generate additional targeted crops.

### Step 3 — Analyze with LLM Vision

#### Step 3a — Overview Analysis

1. Use the AWS Document Loader MCP `read_image` tool on the overview:
   ```
   read_image(file_path="<temp-working-dir>/tiles/overview.png")
   ```
2. Analyze the overview to extract:
   - **Diagram type** (if not already specified by user)
   - **Overall layout** — flow direction (left-to-right, top-to-bottom,
     radial, etc.), number of major sections/groups
   - **Element inventory** — approximate count and types of elements
     visible (components, sticky notes, entities, etc.)
   - **Spatial groups** — clusters, swim lanes, bounded context
     boundaries, containers
   - **Focus regions** — areas that are dense, complex, or contain
     small text that will need careful detail extraction. Record these
     as `{x, y, w, h}` in source-image coordinates (multiply overview
     coordinates by the inverse of the scale factor from the manifest).
3. Store the overview analysis as the **structural map** — this provides
   the global context that individual detail tiles lack.

#### Step 3b — Detail Tile Analysis

For each detail tile (from `detail_manifest.json`):

1. Use `read_image` on the tile:
   ```
   read_image(file_path="<tile-path>")
   ```
2. Provide the LLM with the structural map from Step 3a as context,
   plus the tile's position metadata from the manifest, so the LLM
   knows where in the overall diagram this tile sits.
3. Extract according to diagram type:

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
   - Spatial position: left-to-right = temporal sequence,
     vertical stacking = command→event→policy chains
   - Swim lanes or explicit boundary lines

   **Process flow diagrams:**
   - Steps (name, actor, description)
   - Decisions (condition, branches)
   - Sequence order
   - Swim lanes (actor/system ownership)

   **Domain model diagrams:**
   - Entities (name, key attributes)
   - Relationships (type, cardinality, direction)
   - Aggregate boundaries

   **General / conceptual diagrams:**
   - All visible text labels, groupings, arrows, and annotations
   - Spatial relationships and hierarchy

4. For each tile, record:
   - `tile_id`: identifier from manifest
   - `crop_box`: pixel coordinates in the source image
   - `position_label`: human-readable region name
   - `elements_found`: list of extracted elements with type and content
   - `confidence`: high / medium / low based on legibility
   - `is_duplicate_candidate`: flag elements that likely also appear in
     adjacent overlapping tiles (based on proximity to tile edges)

### Step 4 — Reconcile and Merge

After all tiles are analyzed:

1. **Overlap deduplication** — Because the sliding window guarantees
   overlap, many elements will be extracted from multiple tiles. For
   each element, determine the tile where it appears most centrally
   (farthest from all edges) and treat that as the canonical extraction.
   Discard duplicates from tiles where the element was near an edge.
   Use the crop-box coordinates from the manifest to compute centrality.

2. **Structural-map anchoring** — Cross-reference the detail extractions
   against the overview structural map from Step 3a. Verify that every
   major group/section identified in the overview has corresponding
   detail elements. Flag any groups that appear in the overview but
   have no detail coverage (possible extraction gap).

3. **Relationship completion** — Reconnect arrows or flow lines that
   span multiple tiles. The overview pass will have identified these
   long-range connections; the detail pass provides the endpoint labels.

4. **Sequence reconstruction** — Using the overview's layout analysis,
   assign each element a global position in the diagram's flow:
   - For left-to-right flows: sort by source-image X coordinate
   - For top-to-bottom flows: sort by source-image Y coordinate
   - For event storming: reconstruct the timeline from left-to-right
     position and vertical command→event→policy chains

5. **Confidence assessment** — Assign overall extraction confidence:
   - High: digital export (Miro, FigJam, Lucidchart), clean lines,
     legible text, overview and detail extractions are consistent
   - Medium: whiteboard photo with good lighting, or minor
     inconsistencies between overview and detail passes
   - Low: blurry, cluttered, or partially obscured content, or
     significant gaps between overview and detail coverage

### Step 5 — Generate Structured Markdown Output

Produce a single markdown file with YAML frontmatter following
a standard knowledge record format:

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

The markdown body should follow this structure:

```markdown
# <Diagram Title>

## Overview
<1–3 sentence summary of what the diagram depicts, derived from the
overview pass>

## Diagram Type
<Detected type and notation if identifiable (C4, BPMN, UML, informal,
event storming)>

## Structural Layout
<Description of the overall spatial organization derived from the
overview pass — flow direction, grouping strategy, number of major
sections, notable patterns>

## Elements

### Components / Entities / Events
<Table of all extracted elements, deduplicated>

| # | Name | Type | Description | Source Region | Confidence |
|---|------|------|-------------|---------------|------------|
| 1 | ...  | ...  | ...         | top-left      | high       |

### Relationships / Flows
<Table of connections between elements>

| Source | Target | Type/Label | Direction |
|--------|--------|------------|-----------|
| ...    | ...    | ...        | →         |

### Boundaries / Groups
<Identified groupings, swim lanes, bounded contexts, containers>

### Annotations / Notes
<Free-text annotations, legends, hot spots>

## Ambiguities and Review Items
<Elements that could not be confidently extracted, illegible areas,
inconsistencies between overview and detail passes — each marked with
`requires-review: true`>

## Downstream Usage Guidance
<Recommendations for which SDLC commands or processes can consume this
output — determined by diagram type>
```

### Step 6 — Save and Report

1. **Determine output location.** The skill does NOT assume a fixed
   directory. Resolve the output path in this priority order:
   - **User-specified path** — if the user provides an explicit output
     directory or file path, use it.
   - **Project convention** — check for project steering, environment
     variables, or workspace configuration that defines a knowledge base
     or output root (e.g., a `KNOWLEDGE_BASE_DIR` env var, a path in
     `.kiro/steering/`, or an equivalent project config).
   - **Prompt the user** — if neither of the above yields a path, ask the
     user where to save the output before writing anything.
2. Save the markdown file to the resolved location, organizing by diagram
   category subdirectory (e.g., `event-storming/big-picture/`,
   `architecture/`, etc.) if the target directory already follows that
   convention — otherwise save flat.
3. If a master index file (e.g., `_master-index.md`) exists in the same
   output root, append an entry for the new record.
4. Clean up tile images from the processing directory (or archive if
   user requests preservation).
5. Present a summary to the user:
   - Elements extracted count by type
   - Confidence distribution
   - Items flagged for review
   - Tiles analyzed (sliding window + focus regions)
   - Recommended next steps or downstream commands

---

## Handling Ambiguity

- When elements are unclear, extract what is visible and mark with
  `requires-review: true`.
- When spatial relationships are ambiguous, capture multiple possible
  interpretations and flag them.
- When event storming colors are indistinguishable (e.g., bad lighting
  on a photo), flag for human classification.
- When the overview and detail passes disagree (e.g., overview shows a
  boundary that detail tiles don't confirm), flag the discrepancy.
- **Never fabricate elements that are not visible in the source image.**

---

## Error Handling

- If `split_image.py` fails, check Pillow installation and file format.
- If `read_image` MCP tool fails on a tile, log the failure, skip the tile,
  and note the gap in the final output under Ambiguities.
- If the image is too large for the configured `MAX_FILE_SIZE_MB` on the
  MCP server even after pre-scaling, suggest further reducing
  `--max-source-dim` or increasing stride.
- If the detail pass produces an excessive number of tiles (>100), warn
  the user and suggest increasing stride or reducing viewport.
- Provide a clear error message and recovery suggestion for each failure mode.

---

## Configuration Defaults

| Parameter        | Default  | Notes                                            |
|------------------|----------|--------------------------------------------------|
| Overview max dim | 1200 px  | Downscale target for structural analysis         |
| Viewport         | 1200 px  | Sliding window size for detail pass              |
| Stride           | 800 px   | Step size; overlap = (viewport-stride)/viewport  |
| Effective overlap| ~33%     | At default settings                              |
| Max source dim   | 8000 px  | Auto-downscale source images above this          |
| Max tile size    | 50 MB    | MCP server default; triggers pre-scale if needed |
| Min stride       | 200 px   | Floor to prevent excessive tile counts           |
| Max tile warning | 100      | Warn if detail pass exceeds this count           |
| Tile format      | PNG      | Lossless for best extraction quality             |
| Output format    | markdown | With YAML frontmatter                            |
