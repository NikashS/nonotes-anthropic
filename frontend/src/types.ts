export type Point = { x: number; y: number }

export type SceneElement = {
  id: string
  artifact_id: string
  kind: 'text' | 'shape'
  shape: 'rectangle' | 'ellipse' | 'pill' | null
  content: string
  x: number
  y: number
  width: number
  height: number
  style: Record<string, string>
  revision: number
}

export type Connector = {
  id: string
  artifact_id: string
  source_id: string
  target_id: string
  label: string | null
  style: Record<string, string>
}

export type Artifact = {
  id: string
  title: string
  summary: string
  kind: string
  created_at: string
  updated_at: string
}

export type CanvasSnapshot = {
  id: string
  name: string
  artifacts: Artifact[]
  elements: SceneElement[]
  connectors: Connector[]
}

export type StreamEvent = {
  event: string
  seq: number
  run_id: string
  payload: Record<string, unknown>
}

export type InteractionContext = {
  canvas_id: string
  viewport: { x: number; y: number; zoom: number }
  focused_artifact_id?: string
  selected_element_ids: string[]
  recent_focus_history: string[]
}

