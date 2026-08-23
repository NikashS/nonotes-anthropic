# No Notes — Product Spec

## Summary

No Notes is an AI interface without chats, threads, or tasks. Users interact through one input and never need to find an old conversation. The system retrieves the right context, takes the user to the relevant place in their knowledge space, and continues the work.

Context is stored as durable artifacts—documents, decisions, visualizations, entities, and relationships—not as message history. These artifacts live on an AI-organized infinite canvas and can be retrieved semantically.

## Product principles

- **One entry point:** Starting new work and continuing old work feel the same.
- **Ask, don't search:** Users request what they remember; the system finds it.
- **Solve context:** Retrieve the smallest useful set of artifacts for each request instead of loading entire histories.
- **Artifacts over transcripts:** Preserve useful outcomes, not conversation containers.
- **Navigation by intent:** Asking is the primary way to move through the canvas; panning and browsing are secondary.
- **Visual when helpful:** Explain ideas with approachable notebook-style diagrams and infographics when they improve understanding.
- **Legible memory:** Users can see what the AI knows, where it came from, and where its knowledge is incomplete.

## Core experience

The home view is a single input over a persistent infinite canvas. It has no chat list. For each request, the system identifies relevant entities, retrieves related artifacts, resolves ambiguity, and then answers by navigating to existing material, updating it, or creating something new.

Responses may be text, documents, diagrams, maps, or linked groups of artifacts. Related work is placed near each other. Follow-ups modify the current artifact, add nearby material, or shift focus to an existing related region. Starting an interaction never clears or resets the canvas.

## Knowledge model

Artifacts are stable, searchable objects with content, provenance, revision history, relationships, permissions, and uncertainty where relevant. Relationships such as *related to*, *depends on*, *supports*, *contradicts*, and *supersedes* guide retrieval and placement. AI-inferred relationships remain distinguishable from user-confirmed ones.

Interactions remain internal execution traces for recovery, provenance, and debugging. They are not user-facing conversation containers.

## MVP

- A single input with no chat or task list.
- A persistent infinite canvas with text, document, and simple diagram artifacts.
- Automatic artifact extraction and retrieval.
- Basic entity and relationship linking.
- Natural-language navigation to existing canvas regions.
- Follow-ups that update or extend existing work in place.
- Provenance, revision history, and user correction.

No Notes succeeds when users stop thinking in conversations and simply ask for their work, trusting the system to recover the right context and present it in a form they can understand and continue.

