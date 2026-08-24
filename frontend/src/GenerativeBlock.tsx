import { memo, type CSSProperties } from 'react'
import type { ArtifactBlock } from './types'

type Props = { block: ArtifactBlock; isStreaming: boolean; isFocused: boolean }

export const GenerativeBlock = memo(function GenerativeBlock({ block, isStreaming, isFocused }: Props) {
  const outline = block.content._outline as { item_count?: number; size?: string } | undefined
  const style = { '--outline-items': outline?.item_count ?? 0 } as CSSProperties

  return (
    <section
      className={`gen-block kind-${block.kind} variant-${block.variant} ${isStreaming ? 'is-streaming' : ''} ${isFocused ? 'is-focused' : ''}`}
      data-block-id={block.id}
      data-size={outline?.size ?? 'standard'}
      aria-busy={isStreaming}
      style={style}
      dangerouslySetInnerHTML={{ __html: block.html }}
    />
  )
})
