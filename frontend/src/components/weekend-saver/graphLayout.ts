// Lay the workflow out top to bottom along its longest path.
//
// The builder's own layout uses breadth-first depth, which puts `report` on the second
// row here because every early exit points at it, and is thrown off by the loop back
// from approval. Ranking by the longest path from the start (ignoring edges that
// close a loop) keeps the main pipeline in one column, in order.

import type { Definition, StepDef } from '../../api/weekendSaver'

export type EdgeKind = 'main' | 'skip' | 'loop'
export type StepKind = 'builtin' | 'note' | 'gate' | 'function'

/** An AI step with a conditional edge can end the run, which makes it a gate. */
export function stepKind(step: StepDef, definition: Definition): StepKind {
  if (step.type !== 'agent') return step.type
  const stops = definition.edges.some(edge => edge.source === step.name && edge.condition)
  return stops ? 'gate' : 'note'
}

export interface Layout {
  positions: Record<string, { x: number; y: number }>
  ranks: Record<string, number>
  edgeKinds: EdgeKind[]
}

export const ROW_HEIGHT = 132
export const COLUMN_WIDTH = 240

export function layoutDefinition(definition: Definition): Layout {
  const names = definition.executors.map(step => step.name)
  const outgoing: Record<string, string[]> = Object.fromEntries(names.map(name => [name, []]))
  for (const edge of definition.edges) {
    if (outgoing[edge.source] && outgoing[edge.target]) outgoing[edge.source].push(edge.target)
  }

  const loops = findLoopEdges(definition.start, outgoing)
  const ranks = longestPathRanks(definition.start, outgoing, loops)
  // Steps the start cannot reach go below everything else, so they stay visible
  const lowest = Math.max(0, ...Object.values(ranks))
  for (const name of names) if (ranks[name] === undefined) ranks[name] = lowest + 1

  const rows: Record<number, string[]> = {}
  for (const name of names) (rows[ranks[name]] ??= []).push(name)

  const positions: Layout['positions'] = {}
  for (const [rank, row] of Object.entries(rows)) {
    row.forEach((name, index) => {
      positions[name] = {
        x: (index - (row.length - 1) / 2) * COLUMN_WIDTH,
        y: Number(rank) * ROW_HEIGHT,
      }
    })
  }

  const edgeKinds = definition.edges.map((edge): EdgeKind => {
    if (loops.has(key(edge.source, edge.target))) return 'loop'
    return ranks[edge.target] - ranks[edge.source] === 1 ? 'main' : 'skip'
  })
  return { positions, ranks, edgeKinds }
}

const key = (source: string, target: string) => `${source}->${target}`

function findLoopEdges(start: string, outgoing: Record<string, string[]>): Set<string> {
  const loops = new Set<string>()
  const done = new Set<string>()
  const onPath = new Set<string>()

  const visit = (name: string) => {
    onPath.add(name)
    for (const next of outgoing[name] ?? []) {
      if (onPath.has(next)) loops.add(key(name, next))
      else if (!done.has(next)) visit(next)
    }
    onPath.delete(name)
    done.add(name)
  }
  if (outgoing[start]) visit(start)
  return loops
}

function longestPathRanks(
  start: string,
  outgoing: Record<string, string[]>,
  loops: Set<string>,
): Record<string, number> {
  const ranks: Record<string, number> = {}
  if (!outgoing[start]) return ranks
  ranks[start] = 0
  // Without the loop edges the graph has no cycles, so pushing ranks forward ends
  const queue = [start]
  while (queue.length) {
    const name = queue.shift()!
    for (const next of outgoing[name]) {
      if (loops.has(key(name, next))) continue
      if (ranks[next] === undefined || ranks[next] < ranks[name] + 1) {
        ranks[next] = ranks[name] + 1
        queue.push(next)
      }
    }
  }
  return ranks
}
