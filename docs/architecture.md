# No Notes — Implementation Architecture

## Core invariant

The persistent canvas is never cleared by an interaction. A request resolves to one of four behaviors: modify the focused artifact, extend it nearby, navigate to related existing work, or create a separate spatial locus for genuinely unrelated intent.

## System shape

- React and TypeScript render a single React Flow plane.
- Text chunks, shapes, and connectors are flat sibling scene elements.
- FastAPI owns retrieval, interaction planning, persistence, revisions, and the Anthropic integration.
- Typed NDJSON events incrementally create, patch, connect, and focus scene elements.
- SQLite supports local development; production uses Postgres through `DATABASE_URL`.

## Persistence model

- `Artifact` is the stable identity of a composition.
- `SceneElement` and `Connector` are its current spatial projection.
- `ArtifactRevision` stores immutable snapshots after each successful interaction.
- `InteractionRun` records input, explicit focus context, resolved behavior, and completion state.
- `Relationship` stores typed artifact links independently from visible canvas edges.

The scene schema belongs to No Notes. React Flow is an adapter for viewport and interaction behavior, so library-specific node and edge records are not persisted.

## Focus and retrieval

Every request carries the viewport, focused artifact, selected elements, and recent focus history. Retrieval gives the explicit focus a strong prior, combines it with lexical candidates, and supplies only the most relevant artifact summaries and elements to the planner.

The retrieval boundary is intentionally replaceable. Postgres full-text search and pgvector embeddings can be added behind `retrieve_artifacts` without changing the canvas or streaming contracts.

## Model contract

Claude is forced to call a validated `render_canvas` tool. Its result describes targeted updates, additions, connections, and intent behavior. The backend owns stable IDs, placement, validation, event sequencing, and commits; the model never writes React Flow records directly.

Without a configured Anthropic key the same contract is exercised by a deterministic local planner, keeping development and tests fully functional.

