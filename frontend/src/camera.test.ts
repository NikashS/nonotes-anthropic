import { describe, expect, it } from 'vitest'
import { cameraForWorldBounds } from './camera'

describe('cameraForWorldBounds', () => {
  it('centers changed blocks in the usable canvas above the composer', () => {
    const camera = cameraForWorldBounds(
      { left: 1200, top: 900, width: 720, height: 520 },
      1440,
      1000,
      0.46,
    )
    const usableCenterY = 68 + (1000 - 68 - 170) / 2

    expect(camera.x + (1200 + 720 / 2) * camera.zoom).toBeCloseTo(1440 / 2)
    expect(camera.y + (900 + 520 / 2) * camera.zoom).toBeCloseTo(usableCenterY)
    expect(camera.zoom).toBeGreaterThanOrEqual(0.46)
    expect(camera.zoom).toBeLessThanOrEqual(1.05)
  })

  it('caps zoom for a single small addition', () => {
    const camera = cameraForWorldBounds(
      { left: 200, top: 300, width: 280, height: 160 },
      1440,
      1000,
      0.46,
    )

    expect(camera.zoom).toBe(1.05)
  })
})
