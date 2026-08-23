export type Viewport = { x: number; y: number; zoom: number }

export type Artifact = {
  id: string
  title: string
  summary: string
  kind: string
  x: number
  y: number
  width: number
  height: number
  layout: 'editorial' | 'board' | 'report'
  accent: string
  created_at: string
  updated_at: string
}

export type ArtifactBlock = {
  id: string
  artifact_id: string
  kind: 'hero' | 'rich_text' | 'process' | 'comparison' | 'timeline' | 'diagram' | 'callout' | 'metrics' | 'list'
  variant: 'plain' | 'paper' | 'sketch' | 'ink' | 'accent' | 'quiet'
  content: Record<string, unknown>
  html: string
  order: number
  revision: number
}

export type CanvasSnapshot = {
  id: string
  name: string
  artifacts: Artifact[]
  blocks: ArtifactBlock[]
}

export type StreamEvent = {
  event: string
  seq: number
  run_id: string
  payload: Record<string, unknown>
}

export type InteractionContext = {
  canvas_id: string
  viewport: Viewport
  focused_artifact_id?: string
  focused_block_ids: string[]
  recent_focus_history: string[]
}
