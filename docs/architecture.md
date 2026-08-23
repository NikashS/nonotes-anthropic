# No Notes — Implementation Architecture

## Core invariant

The persistent canvas is never cleared by an interaction. A request resolves to one of four behaviors: modify the focused artifact, extend it, navigate to related existing work, or create a separate spatial region for genuinely unrelated intent. The seeded welcome artifact is orientation rather than conversation context, so a user's first substantive request always creates its own topic region.

## Rendering model

- React renders a custom world-coordinate viewport with camera pan, zoom, and focus transitions.
- An artifact is a positioned generative document, not a draggable graph node.
- Each artifact contains stable semantic blocks such as hero text, prose, processes, comparisons, timelines, diagrams, metrics, lists, and callouts.
- FastAPI compiles validated model output into escaped, themed HTML fragments. The model chooses information structure; the renderer owns CSS and visual style.
- Typed NDJSON events stream complete HTML fragments into stable block IDs.
- A separate topic triggers a blur → camera move → reveal transition. Continuations refocus without blurring or clearing existing work.

The visualization is intentionally non-editing-first. Users can navigate the world and select text, but they do not drag blocks, expose handles, or manually wire diagrams.

## Persistence model

- `Artifact` is the stable identity and retrieval unit for a composition.
- `ArtifactRegion` stores its world position, approximate bounds, layout, and accent.
- `ArtifactBlock` stores semantic type, structured source content, compiled HTML, order, and revision.
- `ArtifactRevision` stores immutable region and block snapshots after each successful interaction.
- `InteractionRun` records input, explicit focus context, resolved behavior, planner, and completion state.
- `Relationship` stores typed semantic links independently from what is visibly drawn.

Production runs on Supabase Postgres through the transaction-mode Supavisor endpoint. Vercel functions use no client-side connection pool and disable prepared statements; Supavisor owns pooling across transient instances. Foreign keys and common artifact/order access paths are indexed.

Structured block content is the source of truth. Compiled HTML is a render cache and streaming payload, never unrestricted model-authored markup.

## Streaming contract

The frontend consumes ordered events:

- `artifact.started`
- `block.started`
- `block.html_delta`
- `block.committed`
- `artifact.committed`
- `viewport.focus_requested`
- `run.completed` or `run.failed`

HTML deltas are complete escaped fragments, so the UI never executes model-authored scripts, styles, event handlers, or arbitrary attributes.

## Focus and retrieval

Every request carries the viewport, focused artifact, focused block IDs, and recent focus history. Retrieval gives explicit focus a strong prior and supplies only the most relevant artifact summaries and structured blocks to the planner.

Follow-ups patch stable block IDs or append new blocks to the focused artifact. Referential cues and model classification distinguish a continuation from a self-contained new subject; visual focus alone is not enough. Only a `new` plan allocates a separate region. Postgres full-text search and pgvector embeddings can be added behind `retrieve_artifacts` without changing the canvas or stream contracts.

## Model contract

Claude is forced to call a validated `compose_artifact` tool. Its result contains intent mode, targeted block updates, new semantic blocks, and layout hints. The backend owns stable IDs, placement, HTML compilation, validation, sequencing, revisions, and commits.

Without a configured Anthropic key, a deterministic planner exercises the same composition and streaming contracts for local development and automated tests.
