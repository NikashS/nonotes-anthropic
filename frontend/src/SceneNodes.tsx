import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { SceneElement } from './types'

type SceneNodeData = SceneElement & { isStreaming?: boolean }

const handleStyle = { opacity: 0, width: 2, height: 2, pointerEvents: 'none' as const }

function ConnectionHandles() {
  return (
    <>
      <Handle type="target" position={Position.Left} style={handleStyle} />
      <Handle type="source" position={Position.Right} style={handleStyle} />
    </>
  )
}

function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ ...props }) => <a {...props} target="_blank" rel="noreferrer" /> }}>
      {children}
    </ReactMarkdown>
  )
}

export const TextNode = memo(function TextNode({ data, selected }: NodeProps) {
  const node = data as SceneNodeData
  return (
    <article className={`scene-node text-node ${selected ? 'selected' : ''} ${node.isStreaming ? 'streaming' : ''}`}>
      <ConnectionHandles />
      <div className="markdown"><Markdown>{node.content}</Markdown></div>
    </article>
  )
})

export const ShapeNode = memo(function ShapeNode({ data, selected }: NodeProps) {
  const node = data as SceneNodeData
  return (
    <article className={`scene-node shape-node shape-${node.shape ?? 'rectangle'} ${selected ? 'selected' : ''} ${node.isStreaming ? 'streaming' : ''}`}>
      <ConnectionHandles />
      <div className="markdown"><Markdown>{node.content}</Markdown></div>
    </article>
  )
})
