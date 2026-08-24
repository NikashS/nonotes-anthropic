import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, type PointerEvent } from 'react'
import { Minus, Plus, Scan } from 'lucide-react'
import { cameraForWorldBounds } from './camera'
import { GenerativeBlock } from './GenerativeBlock'
import type { Artifact, ArtifactBlock, Viewport } from './types'

type Props = {
  artifacts: Artifact[]
  blocks: ArtifactBlock[]
  camera: Viewport
  focusedArtifactId?: string
  focusedBlockIds: string[]
  focusTarget?: { artifactId: string; blockIds: string[]; requestId: number }
  streamingIds: Set<string>
  transitionPhase: 'idle' | 'blur' | 'moving'
  onCameraChange: (camera: Viewport) => void
  onFocusArtifact: (artifactId: string) => void
}

export const SpatialCanvas = memo(function SpatialCanvas({
  artifacts, blocks, camera, focusedArtifactId, focusedBlockIds, focusTarget, streamingIds,
  transitionPhase, onCameraChange, onFocusArtifact,
}: Props) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointerId: number; x: number; y: number; cameraX: number; cameraY: number } | undefined>(undefined)
  const cameraRef = useRef(camera)
  const onCameraChangeRef = useRef(onCameraChange)
  const gestureStartZoomRef = useRef(camera.zoom)

  useEffect(() => { cameraRef.current = camera }, [camera])
  useEffect(() => { onCameraChangeRef.current = onCameraChange }, [onCameraChange])

  const commitCamera = useCallback((next: Viewport) => {
    cameraRef.current = next
    onCameraChangeRef.current(next)
  }, [])

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport || !focusTarget?.blockIds.length) return

    const frame = window.requestAnimationFrame(() => {
      const wanted = new Set(focusTarget.blockIds)
      const elements = [...viewport.querySelectorAll<HTMLElement>('[data-block-id]')]
        .filter((element) => (
          wanted.has(element.dataset.blockId ?? '')
          && element.closest<HTMLElement>('[data-artifact-id]')?.dataset.artifactId === focusTarget.artifactId
        ))
      if (!elements.length) return

      const viewportRect = viewport.getBoundingClientRect()
      const current = cameraRef.current
      const rects = elements.map((element) => element.getBoundingClientRect())
      const left = Math.min(...rects.map((rect) => (rect.left - viewportRect.left - current.x) / current.zoom))
      const top = Math.min(...rects.map((rect) => (rect.top - viewportRect.top - current.y) / current.zoom))
      const right = Math.max(...rects.map((rect) => (rect.right - viewportRect.left - current.x) / current.zoom))
      const bottom = Math.max(...rects.map((rect) => (rect.bottom - viewportRect.top - current.y) / current.zoom))

      commitCamera(cameraForWorldBounds(
        { left, top, width: right - left, height: bottom - top },
        viewportRect.width,
        viewportRect.height,
        0.46,
      ))
    })

    return () => window.cancelAnimationFrame(frame)
  }, [commitCamera, focusTarget])

  const zoomAtPoint = useCallback((nextZoom: number, clientX: number, clientY: number) => {
    const viewport = viewportRef.current
    if (!viewport) return
    const current = cameraRef.current
    const zoom = Math.min(1.45, Math.max(0.28, nextZoom))
    const rect = viewport.getBoundingClientRect()
    const pointX = clientX - rect.left
    const pointY = clientY - rect.top
    const ratio = zoom / current.zoom
    commitCamera({
      x: pointX - (pointX - current.x) * ratio,
      y: pointY - (pointY - current.y) * ratio,
      zoom,
    })
  }, [commitCamera])

  const zoomAtCenter = useCallback((nextZoom: number) => {
    const rect = viewportRef.current?.getBoundingClientRect()
    if (!rect) return
    zoomAtPoint(nextZoom, rect.left + rect.width / 2, rect.top + rect.height / 2)
  }, [zoomAtPoint])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return

    const onWheel = (event: globalThis.WheelEvent) => {
      const target = event.target
      const isOverCanvas = target instanceof Node && viewport.contains(target)
      const isZoomGesture = event.ctrlKey || event.metaKey
      if (!isZoomGesture && !isOverCanvas) return

      event.preventDefault()
      if (isZoomGesture) {
        zoomAtPoint(cameraRef.current.zoom * Math.exp(-event.deltaY * 0.002), event.clientX, event.clientY)
        return
      }
      const current = cameraRef.current
      commitCamera({ ...current, x: current.x - event.deltaX, y: current.y - event.deltaY })
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      if (!["+", "=", "-", "_", "0"].includes(event.key)) return
      event.preventDefault()
      if (event.key === "0") {
        zoomAtCenter(1)
      } else {
        zoomAtCenter(cameraRef.current.zoom * (["+", "="].includes(event.key) ? 1.14 : 0.88))
      }
    }

    type SafariGestureEvent = Event & { scale?: number; clientX?: number; clientY?: number }
    const onGestureStart = (event: Event) => {
      event.preventDefault()
      gestureStartZoomRef.current = cameraRef.current.zoom
    }
    const onGestureChange = (event: Event) => {
      event.preventDefault()
      const gesture = event as SafariGestureEvent
      const rect = viewport.getBoundingClientRect()
      zoomAtPoint(
        gestureStartZoomRef.current * (gesture.scale ?? 1),
        gesture.clientX ?? rect.left + rect.width / 2,
        gesture.clientY ?? rect.top + rect.height / 2,
      )
    }
    const preventGestureEnd = (event: Event) => event.preventDefault()

    window.addEventListener('wheel', onWheel, { passive: false, capture: true })
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('gesturestart', onGestureStart, { passive: false })
    window.addEventListener('gesturechange', onGestureChange, { passive: false })
    window.addEventListener('gestureend', preventGestureEnd, { passive: false })
    return () => {
      window.removeEventListener('wheel', onWheel, true)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('gesturestart', onGestureStart)
      window.removeEventListener('gesturechange', onGestureChange)
      window.removeEventListener('gestureend', preventGestureEnd)
    }
  }, [commitCamera, zoomAtCenter, zoomAtPoint])
  const blocksByArtifact = useMemo(() => {
    const grouped = new Map<string, ArtifactBlock[]>()
    for (const block of blocks) {
      const group = grouped.get(block.artifact_id) ?? []
      group.push(block)
      grouped.set(block.artifact_id, group)
    }
    for (const group of grouped.values()) group.sort((a, b) => a.order - b.order)
    return grouped
  }, [blocks])
  const focusedBlockSet = useMemo(() => new Set(focusedBlockIds), [focusedBlockIds])

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || event.target !== event.currentTarget) return
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, cameraX: camera.x, cameraY: camera.y }
  }, [camera.x, camera.y])

  const onPointerMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    onCameraChange({ ...camera, x: drag.current.cameraX + event.clientX - drag.current.x, y: drag.current.cameraY + event.clientY - drag.current.y })
  }, [camera, onCameraChange])

  const stopDrag = useCallback(() => { drag.current = undefined }, [])

  const zoomBy = useCallback((factor: number) => {
    zoomAtCenter(cameraRef.current.zoom * factor)
  }, [zoomAtCenter])

  return (
    <div
      ref={viewportRef}
      className="canvas-viewport"
      aria-label="Spatial knowledge canvas"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stopDrag}
      onPointerCancel={stopDrag}
    >
      <div
        className={`world-layer topic-${transitionPhase}`}
        style={{ transform: `translate3d(${camera.x}px, ${camera.y}px, 0) scale(${camera.zoom})` }}
      >
        {artifacts.map((artifact) => (
          <article
            key={artifact.id}
            className={`artifact-region layout-${artifact.layout} accent-${artifact.accent} ${artifact.id === focusedArtifactId ? 'is-current' : ''}`}
            style={{ left: artifact.x, top: artifact.y, width: artifact.width, minHeight: artifact.height }}
            data-artifact-id={artifact.id}
          >
            <div className="artifact-content">
              {(blocksByArtifact.get(artifact.id) ?? []).map((block) => (
                <GenerativeBlock key={block.id} block={block} isStreaming={streamingIds.has(block.id)} isFocused={focusedBlockSet.has(block.id)} />
              ))}
            </div>
          </article>
        ))}
      </div>
      <div className="canvas-controls" aria-label="Canvas controls">
        <button onClick={() => zoomBy(1.14)} aria-label="Zoom in"><Plus size={15} /></button>
        <button onClick={() => zoomBy(0.88)} aria-label="Zoom out"><Minus size={15} /></button>
        <button onClick={() => focusedArtifactId && onFocusArtifact(focusedArtifactId)} aria-label="Focus current output"><Scan size={15} /></button>
      </div>
    </div>
  )
})
