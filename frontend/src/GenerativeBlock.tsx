import { memo } from 'react'
import type { ArtifactBlock } from './types'

type Props = { block: ArtifactBlock; isStreaming: boolean; isFocused: boolean }

export const GenerativeBlock = memo(function GenerativeBlock({ block, isStreaming, isFocused }: Props) {
  return (
    <section
      className={`gen-block kind-${block.kind} variant-${block.variant} ${isStreaming ? 'is-streaming' : ''} ${isFocused ? 'is-focused' : ''}`}
      data-block-id={block.id}
      aria-busy={isStreaming}
      dangerouslySetInnerHTML={{ __html: block.html }}
    />
  )
})
