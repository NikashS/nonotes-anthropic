import type { Artifact, ArtifactBlock } from './types'

export const starterArtifact: Artifact = {
  id: 'artifact_no_notes',
  title: 'No Notes',
  summary: 'A spatial AI workspace that retrieves durable artifacts instead of asking users to find old chats.',
  kind: 'welcome',
  x: 40,
  y: 20,
  width: 1040,
  height: 900,
  layout: 'editorial',
  accent: 'moss',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const starterBlocks: ArtifactBlock[] = [
  {
    id: 'block_vision', artifact_id: starterArtifact.id, kind: 'hero', variant: 'plain', order: 0, revision: 1,
    content: { eyebrow: 'A spatial AI workspace', title: 'No Notes', body: 'Ask for what you remember. The system finds the right work and continues it in place.' },
    html: '<p class="eyebrow">A spatial AI workspace</p><h1>No Notes</h1><p class="lede">Ask for what you remember. The system finds the right work and continues it <strong>in place</strong>.</p>',
  },
  {
    id: 'block_flow', artifact_id: starterArtifact.id, kind: 'process', variant: 'sketch', order: 1, revision: 1,
    content: { title: 'From memory to momentum', items: [{ title: 'Ask naturally', body: '' }, { title: 'Retrieve durable artifacts', body: '' }, { title: 'Continue the work', body: '' }] },
    html: '<h2>From memory to momentum</h2><div class="process-line" data-count="3"><div><strong>Ask naturally</strong></div><div><strong>Retrieve durable artifacts</strong></div><div><strong>Continue the work</strong></div></div>',
  },
  {
    id: 'block_principles', artifact_id: starterArtifact.id, kind: 'comparison', variant: 'paper', order: 2, revision: 1,
    content: { title: 'The interaction model', items: [{ label: 'Instead of', title: 'No chats to find', body: 'Intent is the navigation.' }, { label: 'Continuity', title: 'No blank canvas on follow-up', body: 'Focused work changes in place.' }, { label: 'Expression', title: 'No diagram-only answers', body: 'Text, visuals, tables, and documents coexist.' }] },
    html: '<h2>The interaction model</h2><div class="comparison-grid"><article><small>Instead of</small><strong>No chats to find</strong><p>Intent is the navigation.</p></article><article><small>Continuity</small><strong>No blank canvas on follow-up</strong><p>Focused work changes in place.</p></article><article><small>Expression</small><strong>No diagram-only answers</strong><p>Text, visuals, tables, and documents coexist.</p></article></div>',
  },
  {
    id: 'block_note', artifact_id: starterArtifact.id, kind: 'callout', variant: 'ink', order: 3, revision: 1,
    content: { title: 'The invariant', body: 'A follow-up modifies or extends the focused artifact. Only genuinely separate intent creates a new spatial region.' },
    html: '<span class="scribble">The invariant</span><p>A follow-up modifies or extends the focused artifact. Only genuinely separate intent creates a new spatial region.</p>',
  },
]
