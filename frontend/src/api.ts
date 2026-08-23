import type { CanvasSnapshot, InteractionContext, StreamEvent } from './types'

const API_BASE = import.meta.env.VITE_API_URL ?? '/api'

export async function loadCanvas(): Promise<CanvasSnapshot> {
  const response = await fetch(`${API_BASE}/canvas`)
  if (!response.ok) throw new Error('Could not load your canvas')
  return response.json()
}

export async function runInteraction(
  message: string,
  context: InteractionContext,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const response = await fetch(`${API_BASE}/interactions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message, context }),
    signal,
  })

  if (!response.ok || !response.body) {
    const detail = await response.text()
    throw new Error(detail || 'The request could not be completed')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line))
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer))
}
