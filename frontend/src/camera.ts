import type { Viewport } from './types'

export type WorldBounds = { left: number; top: number; width: number; height: number }

export function cameraForWorldBounds(
  bounds: WorldBounds,
  viewportWidth: number,
  viewportHeight: number,
  minZoom = 0.3,
  fitRatio = 0.9,
): Viewport {
  const topInset = 68
  const bottomInset = 170
  const horizontalPadding = 140
  const availableWidth = Math.max(240, viewportWidth - horizontalPadding)
  const availableHeight = Math.max(180, viewportHeight - topInset - bottomInset)
  const contentWidth = Math.max(280, bounds.width)
  const contentHeight = Math.max(160, bounds.height)
  const zoom = Math.min(1.05, Math.max(minZoom, Math.min(availableWidth / contentWidth, availableHeight / contentHeight) * fitRatio))

  return {
    x: viewportWidth / 2 - (bounds.left + bounds.width / 2) * zoom,
    y: topInset + availableHeight / 2 - (bounds.top + bounds.height / 2) * zoom,
    zoom,
  }
}
