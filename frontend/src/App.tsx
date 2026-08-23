import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, CornerDownLeft, LoaderCircle, LocateFixed, Sparkles } from 'lucide-react'
import { loadCanvas, runInteraction } from './api'
import { SpatialCanvas } from './SpatialCanvas'
import type { Artifact, ArtifactBlock, InteractionContext, StreamEvent, Viewport } from './types'

const suggestions = [
  'How does No Notes work?',
  'Add a privacy layer to this architecture',
  'Start a separate topic: plan a two-week Japan trip',
]

function cameraForArtifact(artifact: Artifact): Viewport {
  const viewportWidth = window.innerWidth
  const topInset = 68
  const bottomInset = 170
  const availableHeight = window.innerHeight - topInset - bottomInset
  const zoom = Math.min(1.05, Math.max(0.3, Math.min((viewportWidth - 140) / artifact.width, availableHeight / artifact.height) * 0.96))
  return {
    x: viewportWidth / 2 - (artifact.x + artifact.width / 2) * zoom,
    y: topInset + availableHeight / 2 - (artifact.y + artifact.height / 2) * zoom,
    zoom,
  }
}

export default function App() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [blocks, setBlocks] = useState<ArtifactBlock[]>([])
  const [canvasId, setCanvasId] = useState('main')
  const [camera, setCamera] = useState<Viewport>({ x: 0, y: 0, zoom: 1 })
  const [focusedArtifactId, setFocusedArtifactId] = useState<string>()
  const [focusedBlockIds, setFocusedBlockIds] = useState<string[]>([])
  const [focusHistory, setFocusHistory] = useState<string[]>([])
  const [streamingIds, setStreamingIds] = useState(new Set<string>())
  const [transitionPhase, setTransitionPhase] = useState<'idle' | 'blur' | 'moving'>('idle')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('Loading your space…')
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string>()
  const abortRef = useRef<AbortController | undefined>(undefined)
  const timersRef = useRef<number[]>([])
  const artifactsRef = useRef<Artifact[]>([])

  useEffect(() => {
    loadCanvas()
      .then((snapshot) => {
        setCanvasId(snapshot.id)
        setArtifacts(snapshot.artifacts)
        artifactsRef.current = snapshot.artifacts
        setBlocks(snapshot.blocks)
        const first = snapshot.artifacts[0]
        if (first) {
          setFocusedArtifactId(first.id)
          setFocusedBlockIds(snapshot.blocks.filter((block) => block.artifact_id === first.id).slice(0, 1).map((block) => block.id))
          setCamera(cameraForArtifact(first))
        }
        setStatus('Ready')
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : 'Could not load your space')
        setStatus('Offline')
      })
    return () => timersRef.current.forEach(window.clearTimeout)
  }, [])

  const upsertArtifact = useCallback((artifact: Artifact) => {
    setArtifacts((current) => {
      const next = [...current.filter((item) => item.id !== artifact.id), artifact]
      artifactsRef.current = next
      return next
    })
  }, [])

  const focusArtifact = useCallback((artifactId: string, remember = true) => {
    const artifact = artifactsRef.current.find((item) => item.id === artifactId)
    if (!artifact) return
    if (remember) {
      setFocusedArtifactId((current) => {
        if (current && current !== artifactId) setFocusHistory((history) => [...history.slice(-7), current])
        return artifactId
      })
    } else {
      setFocusedArtifactId(artifactId)
    }
    setCamera(cameraForArtifact(artifact))
  }, [])

  const requestFocus = useCallback((artifactId: string, blockIds: string[], transition: string) => {
    setFocusedBlockIds(blockIds)
    if (transition === 'topic-shift') {
      setTransitionPhase('blur')
      const moveTimer = window.setTimeout(() => {
        setTransitionPhase('moving')
        focusArtifact(artifactId)
      }, 180)
      const revealTimer = window.setTimeout(() => setTransitionPhase('idle'), 820)
      timersRef.current.push(moveTimer, revealTimer)
    } else {
      setTransitionPhase('idle')
      focusArtifact(artifactId, false)
    }
  }, [focusArtifact])

  const handleEvent = useCallback((message: StreamEvent) => {
    const payload = message.payload
    switch (message.event) {
      case 'context.selected':
        setStatus(String(payload.label ?? 'Found the relevant work'))
        break
      case 'artifact.started': {
        const artifact = payload.artifact as Artifact
        upsertArtifact(artifact)
        if (payload.transition === 'topic-shift') setTransitionPhase('blur')
        break
      }
      case 'block.started': {
        const block = payload.block as ArtifactBlock
        setBlocks((current) => [...current.filter((item) => item.id !== block.id), block])
        setStreamingIds((current) => new Set(current).add(block.id))
        break
      }
      case 'block.html_delta': {
        const id = String(payload.block_id)
        const html = String(payload.html ?? '')
        setBlocks((current) => current.map((block) => block.id === id ? { ...block, html: block.html + html } : block))
        break
      }
      case 'block.committed': {
        const id = String(payload.block_id)
        setStreamingIds((current) => {
          const next = new Set(current)
          next.delete(id)
          return next
        })
        break
      }
      case 'artifact.committed':
        upsertArtifact(payload.artifact as Artifact)
        break
      case 'viewport.focus_requested':
        requestFocus(String(payload.artifact_id), payload.block_ids as string[], String(payload.transition ?? 'continuation'))
        break
      case 'run.completed':
        setStatus(String(payload.label ?? 'Ready'))
        break
      case 'run.failed':
        setError(String(payload.message ?? 'Something went wrong'))
        setStatus('Could not complete')
        setTransitionPhase('idle')
        break
    }
  }, [requestFocus, upsertArtifact])

  const submit = useCallback(async (value = query) => {
    const message = value.trim()
    if (!message || isRunning) return
    setQuery('')
    setError(undefined)
    setIsRunning(true)
    setStatus('Understanding where this belongs…')
    const controller = new AbortController()
    abortRef.current = controller
    const context: InteractionContext = {
      canvas_id: canvasId,
      viewport: camera,
      focused_artifact_id: focusedArtifactId,
      focused_block_ids: focusedBlockIds,
      recent_focus_history: focusHistory,
    }
    try {
      await runInteraction(message, context, handleEvent, controller.signal)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Something went wrong')
      setTransitionPhase('idle')
    } finally {
      setIsRunning(false)
      abortRef.current = undefined
    }
  }, [camera, canvasId, focusHistory, focusedArtifactId, focusedBlockIds, handleEvent, isRunning, query])

  const goBack = useCallback(() => {
    const artifactId = focusHistory.at(-1)
    if (!artifactId) return
    setFocusHistory((history) => history.slice(0, -1))
    focusArtifact(artifactId, false)
    setFocusedBlockIds(blocks.filter((block) => block.artifact_id === artifactId).slice(0, 1).map((block) => block.id))
  }, [blocks, focusArtifact, focusHistory])

  const focusedArtifact = useMemo(() => artifacts.find((artifact) => artifact.id === focusedArtifactId), [artifacts, focusedArtifactId])

  return (
    <main className="app-shell" data-artifact-count={artifacts.length} data-block-count={blocks.length} data-transition={transitionPhase}>
      <SpatialCanvas
        artifacts={artifacts}
        blocks={blocks}
        camera={camera}
        focusedArtifactId={focusedArtifactId}
        focusedBlockIds={focusedBlockIds}
        streamingIds={streamingIds}
        transitionPhase={transitionPhase}
        onCameraChange={setCamera}
        onFocusArtifact={focusArtifact}
      />

      <header className="topbar">
        <div className="brand"><span>No Notes</span><i /></div>
        <div className="focus-chip">
          {focusHistory.length > 0 ? <button onClick={goBack} aria-label="Return to previous focus"><ArrowLeft size={14} /></button> : null}
          <LocateFixed size={13} />
          <span>{focusedArtifact?.title ?? 'Your knowledge space'}</span>
        </div>
        <div className={`status ${isRunning ? 'working' : ''}`}>
          {isRunning ? <LoaderCircle size={13} /> : null}{status}
        </div>
      </header>

      <section className="composer-wrap" aria-label="Ask No Notes">
        {!blocks.length && !isRunning ? (
          <div className="empty-state"><Sparkles size={20} /><h1>Ask for what you remember.</h1><p>Your work will appear here and remain connected.</p></div>
        ) : null}
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
        {!isRunning ? <div className="suggestions">{suggestions.map((suggestion) => <button key={suggestion} onClick={() => void submit(suggestion)}>{suggestion}</button>)}</div> : null}
        {error ? <div className="error-toast">{error}</div> : null}
      </section>
    </main>
  )
}
