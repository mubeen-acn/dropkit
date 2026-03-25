---
name: diagram-ingestion
description: >
  Ingest architecture diagrams, event storming boards, and event maps from
  images. Splits large images into a configurable grid (minimum 3×3) using a
  Python helper script, reads each tile via the AWS Document Loader MCP
  server's read_image tool, assembles LLM-extracted content, and produces a
  structured markdown summary suitable as input to downstream SDLC artifacts
  (solution concepts, domain synthesis, architecture views, feature specs).
  Use when the user provides an image of an architecture diagram, event
  storming board, event map, process flow, domain model, or any visual
  artifact that needs to be converted into structured knowledge.
license: Apache-2.0
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
into structured markdown knowledge records by splitting images into readable
batches and analyzing each tile with LLM vision via the AWS Document Loader
MCP server.

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

## Workflow

### Step 1 — Validate Input

When the user provides an image file path (or drops an image into chat):

1. Confirm the file exists and is a supported image format
   (PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF).
2. Determine the image dimensions. If the image is small enough to be
   analyzed in a single pass (both width ≤ 1200 px AND height ≤ 1200 px),
   skip to **Step 3 — Single-Pass Analysis**.
3. Ask the user to confirm or override:
   - **Grid size** — default 3×3; minimum 3×3; suggest larger grids for
     very large images (e.g., 4×4 for > 4000 px on either axis,
     5×5 for > 6000 px).
   - **Diagram type** — auto-detect or let user specify:
     architecture, event-storming, process-flow, domain-model, conceptual.
   - **Overlap percentage** — default 10 %; adds context bleed between tiles
     to avoid cutting elements at boundaries.

### Step 2 — Split Image into Tiles

Run the Python helper script to generate tile images:

```bash
python scripts/split_image.py \
  --input "<source-image-path>" \
  --output-dir "<temp-working-dir>/tiles/" \
  --rows <R> \
  --cols <C> \
  --overlap <0.10>
```

The `<temp-working-dir>` should be a transient location (e.g., a system
temp directory or a project-local scratch folder). Do NOT assume a fixed
workspace path — use the OS temp directory or ask the user if uncertain.

The script produces numbered tile files:
`tile_R0_C0.png`, `tile_R0_C1.png`, … `tile_R<n>_C<n>.png`

It also writes a `tile_manifest.json` containing:
- Source image path and dimensions
- Grid dimensions (rows × cols)
- Overlap percentage
- Per-tile metadata: filename, row, col, pixel coordinates (x, y, w, h)

### Step 3 — Analyze Tiles (or Single Image)

For each tile (or the whole image in single-pass mode):

1. Use the AWS Document Loader MCP `read_image` tool:
   ```
   read_image(file_path="<tile-path>")
   ```
2. After the MCP tool returns the image content, analyze the tile with
   LLM vision. Extract according to diagram type:

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

3. For each tile, record:
   - `tile_id`: row-col identifier
   - `position`: which region of the source image (top-left, center, etc.)
   - `elements_found`: list of extracted elements with type and content
   - `confidence`: high / medium / low based on legibility
   - `edge_elements`: elements that appear to be cut off at tile edges
     (these will be reconciled in Step 4)

### Step 4 — Reconcile and Merge

After all tiles are analyzed:

1. **Boundary reconciliation** — For elements flagged as `edge_elements`,
   match across adjacent tiles using name similarity and spatial position.
   Deduplicate and merge into a single element record.
2. **Sequence reconstruction** — Re-establish the global ordering:
   - Left-to-right across columns = temporal/flow sequence
   - Top-to-bottom across rows = grouping/swim-lane order
3. **Relationship completion** — Reconnect arrows or flow lines that
   were split across tile boundaries.
4. **Confidence assessment** — Assign overall extraction confidence:
   - High: digital export (Miro, FigJam, Lucidchart), clean lines, legible text
   - Medium: whiteboard photo with good lighting and clear handwriting
   - Low: blurry, cluttered, or partially obscured content

### Step 5 — Generate Structured Markdown Output

Produce a single markdown file with YAML frontmatter following the
knowledge record format used by the SDLC knowledge-ingestion command:

```yaml
---
title: "<Diagram title or user-provided name>"
source-file: "<original image filename>"
content-type: image
content-category: <architecture-diagram | event-storming-big-picture | event-storming-design-level | process-diagram | domain-model | conceptual>
ingestion-date: "<ISO-8601 datetime>"
diagram-type: "<detected or user-specified type>"
processing:
  grid-size: "<R>x<C>"
  overlap-pct: <overlap>
  tiles-processed: <count>
  tiles-with-low-confidence: <count>
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
<1–3 sentence summary of what the diagram depicts>

## Diagram Type
<Detected type and notation if identifiable (C4, BPMN, UML, informal, event storming)>

## Elements

### Components / Entities / Events
<Table or structured list of all extracted elements>

| # | Name | Type | Description | Tile Source | Confidence |
|---|------|------|-------------|-------------|------------|
| 1 | ...  | ...  | ...         | R0-C1       | high       |

### Relationships / Flows
<Table of connections between elements>

| Source | Target | Type/Label | Direction |
|--------|--------|------------|-----------|
| ...    | ...    | ...        | →         |

### Boundaries / Groups
<Identified groupings, swim lanes, bounded contexts, containers>

### Annotations / Notes
<Free-text annotations, legends, hot spots>

## Spatial Layout Summary
<Description of the overall spatial organization — flow direction,
grouping strategy, notable patterns>

## Ambiguities and Review Items
<Elements that could not be confidently extracted, cut-off text,
illegible areas — each marked with `requires-review: true`>

## Downstream Usage Guidance
<Recommendations for which SDLC commands can consume this output>
- If architecture diagram → `arch-domain-architecture`, `arch-logical-architecture`
- If event storming → `discovery-domain-synthesis`
- If process flow → `discovery-solution-concept`
- If domain model → `discovery-domain-synthesis`, `arch-domain-architecture`
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
   - Recommended next SDLC command to run

---

## Handling Ambiguity

- When elements are unclear, extract what is visible and mark with
  `requires-review: true`.
- When spatial relationships are ambiguous, capture multiple possible
  interpretations and flag them.
- When event storming colors are indistinguishable (e.g., bad lighting
  on a photo), flag for human classification.
- **Never fabricate elements that are not visible in the source image.**

---

## Error Handling

- If `split_image.py` fails, check Pillow installation and file format.
- If `read_image` MCP tool fails on a tile, log the failure, skip the tile,
  and note the gap in the final output under Ambiguities.
- If the image is too large for the configured `MAX_FILE_SIZE_MB` on the
  MCP server, suggest increasing the grid size or resizing the source.
- Provide a clear error message and recovery suggestion for each failure mode.

---

## Configuration Defaults

| Parameter        | Default | Notes                                    |
|------------------|---------|------------------------------------------|
| Grid rows        | 3       | Minimum 3                                |
| Grid columns     | 3       | Minimum 3                                |
| Overlap          | 10%     | Prevents elements from being cut off     |
| Max tile size    | 50 MB   | Matches MCP server default               |
| Output format    | markdown | With YAML frontmatter                    |
| Tile format      | PNG     | Lossless for best extraction quality     |