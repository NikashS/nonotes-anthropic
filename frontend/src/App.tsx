import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useUpdateNodeInternals,
  type Edge,
  type Node,
  type NodeChange,
  applyNodeChanges,
} from '@xyflow/react'
import { ArrowLeft, CornerDownLeft, LoaderCircle, LocateFixed, Sparkles } from 'lucide-react'
import '@xyflow/react/dist/style.css'
import { loadCanvas, runInteraction, updateElementPosition } from './api'
import { ShapeNode, TextNode } from './SceneNodes'
import type { Artifact, Connector, InteractionContext, SceneElement, StreamEvent } from './types'

const nodeTypes = { text: TextNode, shape: ShapeNode }
const suggestions = [
  'How does No Notes work?',
  'Add a privacy layer to this architecture',
  'Make the focused explanation simpler',
]

function elementToNode(element: SceneElement, streamingIds: Set<string>): Node {
  return {
    id: element.id,
    type: element.kind,
    position: { x: element.x, y: element.y },
    width: element.width,
    height: element.height,
    handles: [
      { id: null, type: 'target', position: Position.Left, x: -1, y: element.height / 2 - 1, width: 2, height: 2 },
      { id: null, type: 'source', position: Position.Right, x: element.width - 1, y: element.height / 2 - 1, width: 2, height: 2 },
    ],
    style: { width: element.width, height: element.height },
    data: { ...element, isStreaming: streamingIds.has(element.id) },
  }
}

function connectorToEdge(connector: Connector): Edge {
  return {
    id: connector.id,
    source: connector.source_id,
    target: connector.target_id,
    type: 'straight',
    label: connector.label ?? undefined,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: '#5c5a54' },
    style: { stroke: '#5c5a54', strokeWidth: 1.35 },
    labelStyle: { fill: '#6f6c64', fontSize: 12 },
    labelBgStyle: { fill: '#f8f7f3', fillOpacity: 0.92 },
    labelBgPadding: [5, 3],
    labelBgBorderRadius: 5,
  }
}

function CanvasApp() {
  const flow = useReactFlow()
  const updateNodeInternals = useUpdateNodeInternals()
  const [elements, setElements] = useState<SceneElement[]>([])
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [canvasId, setCanvasId] = useState('main')
  const [focusedArtifactId, setFocusedArtifactId] = useState<string>()
  const [selectedElementIds, setSelectedElementIds] = useState<string[]>([])
  const [focusHistory, setFocusHistory] = useState<string[]>([])
  const [streamingIds, setStreamingIds] = useState(new Set<string>())
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('Loading your space…')
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string>()
  const abortRef = useRef<AbortController | undefined>(undefined)
  const hasFitInitial = useRef(false)

  useEffect(() => {
    loadCanvas()
      .then((snapshot) => {
        setCanvasId(snapshot.id)
        setElements(snapshot.elements)
        setConnectors(snapshot.connectors)
        setArtifacts(snapshot.artifacts)
        setFocusedArtifactId(snapshot.artifacts[0]?.id)
        setStatus('Ready')
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : 'Could not load your space')
        setStatus('Offline')
      })
  }, [])

  useEffect(() => {
    if (!hasFitInitial.current && elements.length) {
      hasFitInitial.current = true
      requestAnimationFrame(() => {
        updateNodeInternals(elements.map((element) => element.id))
        flow.fitView({ padding: 0.22, duration: 700 })
      })
    }
  }, [elements, flow, updateNodeInternals])

  const nodes = useMemo(() => elements.map((element) => elementToNode(element, streamingIds)), [elements, streamingIds])
  const edges = useMemo(() => connectors.map(connectorToEdge), [connectors])

  const focusElements = useCallback((ids: string[]) => {
    const targets = ids.map((id) => ({ id }))
    if (targets.length) requestAnimationFrame(() => flow.fitView({ nodes: targets, padding: 0.32, duration: 650, maxZoom: 1.15 }))
  }, [flow])

  const handleEvent = useCallback((message: StreamEvent) => {
    const payload = message.payload
    switch (message.event) {
      case 'context.selected':
        setStatus(String(payload.label ?? 'Found the relevant work'))
        break
      case 'artifact.upserted': {
        const artifact = payload.artifact as Artifact
        setArtifacts((current) => [...current.filter((item) => item.id !== artifact.id), artifact])
        setFocusedArtifactId(artifact.id)
        break
      }
      case 'element.created': {
        const element = payload.element as SceneElement
        setElements((current) => [...current.filter((item) => item.id !== element.id), element])
        setStreamingIds((current) => new Set(current).add(element.id))
        break
      }
      case 'element.content_delta': {
        const id = String(payload.element_id)
        const delta = String(payload.delta ?? '')
        setElements((current) => current.map((item) => item.id === id ? { ...item, content: item.content + delta } : item))
        break
      }
      case 'element.patched': {
        const element = payload.element as SceneElement
        setElements((current) => current.map((item) => item.id === element.id ? element : item))
        setStreamingIds((current) => new Set(current).add(element.id))
        break
      }
      case 'element.committed': {
        const id = String(payload.element_id)
        setStreamingIds((current) => {
          const next = new Set(current)
          next.delete(id)
          return next
        })
        break
      }
      case 'connector.created':
        setConnectors((current) => [...current.filter((item) => item.id !== (payload.connector as Connector).id), payload.connector as Connector])
        break
      case 'canvas.focus_requested': {
        const ids = payload.element_ids as string[]
        const artifactId = payload.artifact_id ? String(payload.artifact_id) : undefined
        if (artifactId) {
          setFocusedArtifactId((current) => {
            if (current && current !== artifactId) setFocusHistory((history) => [...history.slice(-7), current])
            return artifactId
          })
        }
        setSelectedElementIds(ids)
        focusElements(ids)
        break
      }
      case 'run.completed':
        setStatus(String(payload.label ?? 'Ready'))
        break
      case 'run.failed':
        setError(String(payload.message ?? 'Something went wrong'))
        setStatus('Could not complete')
        break
    }
  }, [focusElements])

  const submit = useCallback(async (value = query) => {
    const message = value.trim()
    if (!message || isRunning) return

    setQuery('')
    setError(undefined)
    setIsRunning(true)
    setStatus('Understanding where this belongs…')
    const controller = new AbortController()
    abortRef.current = controller
    const viewport = flow.getViewport()
    const context: InteractionContext = {
      canvas_id: canvasId,
      viewport,
      focused_artifact_id: focusedArtifactId,
      selected_element_ids: selectedElementIds,
      recent_focus_history: focusHistory,
    }

    try {
      await runInteraction(message, context, handleEvent, controller.signal)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Something went wrong')
    } finally {
      setIsRunning(false)
      abortRef.current = undefined
    }
  }, [canvasId, flow, focusHistory, focusedArtifactId, handleEvent, isRunning, query, selectedElementIds])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setElements((current) => {
      const changedNodes = applyNodeChanges(changes, current.map((element) => elementToNode(element, streamingIds)))
      const positions = new Map(changedNodes.map((node) => [node.id, node.position]))
      return current.map((element) => ({ ...element, ...(positions.get(element.id) ?? {}) }))
    })
  }, [streamingIds])

  const goBack = useCallback(() => {
    const artifactId = focusHistory.at(-1)
    if (!artifactId) return
    setFocusHistory((history) => history.slice(0, -1))
    setFocusedArtifactId(artifactId)
    focusElements(elements.filter((element) => element.artifact_id === artifactId).map((element) => element.id))
  }, [elements, focusElements, focusHistory])

  const onSelectionChange = useCallback(({ nodes: selected }: { nodes: Node[] }) => {
    const nextIds = selected.map((node) => node.id)
    setSelectedElementIds((current) => {
      if (current.length === nextIds.length && current.every((id, index) => id === nextIds[index])) return current
      return nextIds
    })
  }, [])

  const focusedArtifact = artifacts.find((artifact) => artifact.id === focusedArtifactId)

  return (
    <main className="app-shell" data-node-count={nodes.length} data-edge-count={edges.length}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => {
          const element = elements.find((item) => item.id === node.id)
          if (!element) return
          if (focusedArtifactId && focusedArtifactId !== element.artifact_id) setFocusHistory((history) => [...history.slice(-7), focusedArtifactId])
          setFocusedArtifactId(element.artifact_id)
          setSelectedElementIds([element.id])
        }}
        onSelectionChange={onSelectionChange}
        onNodeDragStop={(_, node) => void updateElementPosition(node.id, node.position.x, node.position.y)}
        defaultEdgeOptions={{ selectable: false }}
        minZoom={0.16}
        maxZoom={1.8}
        selectionOnDrag
        panOnDrag={[1, 2]}
        panOnScroll
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: false }}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={0.75} color="#d9d6ce" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>

      <header className="topbar">
        <div className="brand"><span>No Notes</span><i /></div>
        <div className="focus-chip">
          {focusHistory.length > 0 && <button onClick={goBack} aria-label="Return to previous focus"><ArrowLeft size={14} /></button>}
          <LocateFixed size={13} />
          <span>{focusedArtifact?.title ?? 'Your knowledge space'}</span>
        </div>
        <div className={`status ${isRunning ? 'working' : ''}`}>
          {isRunning && <LoaderCircle size={13} />}{status}
        </div>
      </header>

      <section className="composer-wrap" aria-label="Ask No Notes">
        {!elements.length && !isRunning && (
          <div className="empty-state">
            <Sparkles size={20} />
            <h1>Ask for what you remember.</h1>
            <p>No chats to find. Your work will appear here and remain connected.</p>
          </div>
        )}
        <form className="composer" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void submit()
              }
            }}
            placeholder={focusedArtifact ? `Build on “${focusedArtifact.title}”…` : 'Ask anything…'}
            aria-label="Ask anything"
            rows={1}
            disabled={isRunning}
          />
          <button type="submit" disabled={!query.trim() || isRunning} aria-label="Send">
            {isRunning ? <LoaderCircle size={17} /> : <CornerDownLeft size={17} />}
          </button>
        </form>
        {!isRunning && (
          <div className="suggestions">
            {suggestions.map((suggestion) => <button key={suggestion} onClick={() => void submit(suggestion)}>{suggestion}</button>)}
          </div>
        )}
        {error && <div className="error-toast">{error}</div>}
      </section>
    </main>
  )
}

export default function App() {
  return <ReactFlowProvider><CanvasApp /></ReactFlowProvider>
}
