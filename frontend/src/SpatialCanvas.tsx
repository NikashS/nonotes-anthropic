import { memo, useCallback, useMemo, useRef, type PointerEvent, type WheelEvent } from 'react'
import { Minus, Plus, Scan } from 'lucide-react'
import { GenerativeBlock } from './GenerativeBlock'
import type { Artifact, ArtifactBlock, Viewport } from './types'

type Props = {
  artifacts: Artifact[]
  blocks: ArtifactBlock[]
  camera: Viewport
  focusedArtifactId?: string
  focusedBlockIds: string[]
  streamingIds: Set<string>
  transitionPhase: 'idle' | 'blur' | 'moving'
  onCameraChange: (camera: Viewport) => void
  onFocusArtifact: (artifactId: string) => void
}

export const SpatialCanvas = memo(function SpatialCanvas({
  artifacts, blocks, camera, focusedArtifactId, focusedBlockIds, streamingIds,
  transitionPhase, onCameraChange, onFocusArtifact,
}: Props) {
  const drag = useRef<{ pointerId: number; x: number; y: number; cameraX: number; cameraY: number } | undefined>(undefined)
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

  const onWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (event.ctrlKey || event.metaKey) {
      const nextZoom = Math.min(1.45, Math.max(0.28, camera.zoom * Math.exp(-event.deltaY * 0.002)))
      const ratio = nextZoom / camera.zoom
      onCameraChange({ x: event.clientX - (event.clientX - camera.x) * ratio, y: event.clientY - (event.clientY - camera.y) * ratio, zoom: nextZoom })
    } else {
      onCameraChange({ ...camera, x: camera.x - event.deltaX, y: camera.y - event.deltaY })
    }
  }, [camera, onCameraChange])

  const zoomBy = useCallback((factor: number) => {
    onCameraChange({ ...camera, zoom: Math.min(1.45, Math.max(0.28, camera.zoom * factor)) })
  }, [camera, onCameraChange])

  return (
    <div
      className="canvas-viewport"
      aria-label="Spatial knowledge canvas"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stopDrag}
      onPointerCancel={stopDrag}
      onWheel={onWheel}
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
            <div className="artifact-corner" aria-hidden="true">{artifact.title}</div>
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
