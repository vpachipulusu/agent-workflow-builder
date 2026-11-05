import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { Definition, StepDef } from '../../api/weekendSaver'
import { layoutDefinition, stepKind, type EdgeKind, type StepKind } from './graphLayout'

const KIND_LABELS: Record<StepKind, string> = {
  builtin: 'Built-in',
  note: 'AI note',
  gate: 'AI gate',
  function: 'Pass-through',
}

const STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  waiting: 'Waiting for you',
  done: 'Done',
  failed: 'Failed',
}

// The main path runs top to bottom. Early exits leave and arrive on the right and the
// re-plan loop on the left, so they do not hide behind the steps in between.
const HANDLES: Record<EdgeKind, { source: string; target: string }> = {
  main: { source: 'bottom', target: 'top' },
  skip: { source: 'right-out', target: 'right-in' },
  loop: { source: 'left-out', target: 'left-in' },
}
// How far a side line swings out: longer jumps go further, so they do not overlap
const SIDE_OFFSET = 26
const SIDE_OFFSET_PER_ROW = 16

interface StepData extends Record<string, unknown> {
  step: StepDef
  kind: StepKind
  isStart: boolean
  status?: string
  note?: string
}

type StepNodeType = Node<StepData, 'step'>

const NODE_TYPES = { step: StepNode }

interface Props {
  definition: Definition
  statuses: Record<string, string>
  notes: Record<string, string>
}

export default function WorkflowGraph({ definition, statuses, notes }: Props) {
  const theme = useTheme()
  const layout = useMemo(() => layoutDefinition(definition), [definition])

  // Derived, not kept in state: the graph is a picture of the definition and the run,
  // so there is nothing for the canvas to own
  const nodes = useMemo<StepNodeType[]>(
    () =>
      definition.executors.map(step => ({
        id: step.name,
        type: 'step' as const,
        position: layout.positions[step.name],
        data: {
          step,
          kind: stepKind(step, definition),
          isStart: step.name === definition.start,
          status: statuses[step.name],
          note: notes[step.name],
        },
      })),
    [definition, layout, statuses, notes],
  )

  const edges = useMemo<Edge[]>(() => {
    // `theme` is a dependency because the colours are read from CSS variables
    const colors = edgeColors(theme)
    return definition.edges.map((edge, index) => {
      const kind = layout.edgeKinds[index]
      const travelled = statuses[edge.source] === 'done' && statuses[edge.target] !== undefined
      const stroke = travelled ? colors.travelled : colors[kind]
      const rows = Math.abs(layout.ranks[edge.target] - layout.ranks[edge.source])
      return {
        id: `edge-${index}`,
        source: edge.source,
        target: edge.target,
        sourceHandle: HANDLES[kind].source,
        targetHandle: HANDLES[kind].target,
        ...(kind === 'main'
          ? {}
          : {
              type: 'smoothstep',
              pathOptions: { offset: SIDE_OFFSET + SIDE_OFFSET_PER_ROW * rows, borderRadius: 8 },
            }),
        label: edge.condition ?? '',
        labelStyle: { fill: colors.label, fontSize: 11 },
        labelBgStyle: { fill: colors.labelBackground },
        labelBgPadding: [4, 2] as [number, number],
        style: {
          stroke,
          strokeWidth: travelled ? 2.5 : 1.5,
          strokeDasharray: kind === 'main' ? undefined : '6 4',
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      }
    })
  }, [definition, layout, statuses, theme])

  // A new key remounts the canvas, which is what makes it fit a changed graph again
  const shape = useMemo(
    () =>
      [
        definition.start,
        ...definition.executors.map(step => step.name),
        ...definition.edges.map(edge => `${edge.source}>${edge.target}`),
      ].join('|'),
    [definition],
  )

  return (
    <ReactFlow
      key={shape}
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      colorMode={theme === 'dark' ? 'dark' : 'light'}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      fitView
      proOptions={{ hideAttribution: true }}
      style={{ background: 'var(--bg-panel-body)' }}
    >
      <Background color="var(--border)" gap={20} />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

function StepNode({ data }: NodeProps<StepNodeType>) {
  const { step, kind, isStart, status, note } = data
  return (
    <div
      className={`workflow-node ws-node ws-node-${kind} ${status ? `ws-node-${status}` : ''}`}
      title={step.instructions}
    >
      <Handle type="target" position={Position.Top} id="top" />
      <Handle type="target" position={Position.Right} id="right-in" style={{ top: '70%' }} />
      <Handle type="target" position={Position.Left} id="left-in" style={{ top: '70%' }} />
      <div className="workflow-node-label">
        {status === 'running' && <span className="wf-node-pulse" />}
        {step.name}
      </div>
      <div className="workflow-node-type">
        {KIND_LABELS[kind]}
        {isStart && ' · start'}
        {status && ` · ${STATUS_LABELS[status] ?? status}`}
      </div>
      {note && (
        <div className="ws-node-text" title={note}>
          {note}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} id="bottom" />
      <Handle type="source" position={Position.Right} id="right-out" style={{ top: '30%' }} />
      <Handle type="source" position={Position.Left} id="left-out" style={{ top: '30%' }} />
    </div>
  )
}

/** Re-render when the app switches between light and dark. */
function useTheme(): string {
  const read = () => document.documentElement.getAttribute('data-theme') ?? 'light'
  const [theme, setTheme] = useState(read)
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  return theme
}

// SVG markers take their colour as an attribute, where var() does not resolve, so
// the theme's values are read here instead of being repeated as hex codes.
function edgeColors(
  _theme: string,
): Record<EdgeKind | 'travelled' | 'label' | 'labelBackground', string> {
  const style = getComputedStyle(document.documentElement)
  const value = (name: string) => style.getPropertyValue(name).trim()
  return {
    main: value('--text-secondary'),
    skip: value('--text-muted'),
    loop: value('--accent'),
    travelled: value('--success'),
    label: value('--text-secondary'),
    labelBackground: value('--bg-elevated'),
  }
}
