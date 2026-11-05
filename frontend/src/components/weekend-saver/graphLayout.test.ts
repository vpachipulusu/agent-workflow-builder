import { describe, expect, it } from 'vitest'
import type { Definition, EdgeDef, StepDef } from '../../api/weekendSaver'
import { COLUMN_WIDTH, ROW_HEIGHT, layoutDefinition, stepKind } from './graphLayout'

const CORE = ['load_targets', 'resolve_state', 'approval', 'apply', 'verify', 'report']

const step = (name: string, type: StepDef['type'] = 'builtin'): StepDef => ({
  name,
  type,
  instructions: '',
})

const edge = (source: string, target: string, condition: string | null = null): EdgeDef => ({
  source,
  target,
  condition,
  fan_in: false,
})

const DEFAULT_EDGES = [
  edge('load_targets', 'resolve_state', 'valid'),
  edge('load_targets', 'report', 'invalid'),
  edge('resolve_state', 'approval', 'planned'),
  edge('resolve_state', 'report', 'invalid'),
  edge('approval', 'apply', 'approved'),
  edge('approval', 'load_targets', 'replan'),
  edge('approval', 'report', 'ended'),
  edge('apply', 'verify', 'applied'),
  edge('verify', 'report', 'verified'),
]

const definition = (executors: StepDef[], edges: EdgeDef[], start = 'load_targets'): Definition => ({
  name: 'weekend_saver',
  description: '',
  start,
  executors,
  edges,
})

const defaultDefinition = () => definition(CORE.map(name => step(name)), DEFAULT_EDGES)

describe('stepKind', () => {
  const gate = step('holiday_check', 'agent')
  const note = step('summary', 'agent')
  const custom = definition(
    [...CORE.map(name => step(name)), gate, note, step('log', 'function')],
    [edge('holiday_check', 'resolve_state'), edge('holiday_check', 'report', 'a holiday week')],
  )

  it('calls an AI step with a stop condition a gate', () => {
    expect(stepKind(gate, custom)).toBe('gate')
  })

  it('calls an AI step without one a note', () => {
    expect(stepKind(note, custom)).toBe('note')
  })

  it('keeps the type of the other steps', () => {
    expect(stepKind(step('apply'), custom)).toBe('builtin')
    expect(stepKind(step('log', 'function'), custom)).toBe('function')
  })
})

describe('layoutDefinition', () => {
  it('keeps the core pipeline in one column, in order', () => {
    const { positions, ranks } = layoutDefinition(defaultDefinition())

    expect(CORE.map(name => ranks[name])).toEqual([0, 1, 2, 3, 4, 5])
    expect(CORE.map(name => positions[name].x)).toEqual([0, 0, 0, 0, 0, 0])
    expect(positions.report.y).toBe(5 * ROW_HEIGHT)
  })

  it('tells the main path, the early exits and the loop back apart', () => {
    const { edgeKinds } = layoutDefinition(defaultDefinition())
    const kindOf = (source: string, target: string) =>
      edgeKinds[DEFAULT_EDGES.findIndex(e => e.source === source && e.target === target)]

    expect(kindOf('load_targets', 'resolve_state')).toBe('main')
    expect(kindOf('load_targets', 'report')).toBe('skip')
    expect(kindOf('approval', 'load_targets')).toBe('loop')
    expect(kindOf('verify', 'report')).toBe('main')
  })

  it('makes room for a step placed between two core steps', () => {
    const edges = [
      ...DEFAULT_EDGES.filter(e => !(e.source === 'verify' && e.target === 'report')),
      edge('verify', 'summary', 'verified'),
      edge('summary', 'report'),
    ]
    const custom = definition([...CORE.map(name => step(name)), step('summary', 'agent')], edges)

    const { ranks } = layoutDefinition(custom)

    expect(ranks.summary).toBe(5)
    expect(ranks.report).toBe(6)
  })

  it('puts steps of the same rank side by side, centred', () => {
    const custom = definition(
      [step('a'), step('left', 'agent'), step('right', 'agent'), step('z')],
      [edge('a', 'left'), edge('a', 'right'), edge('left', 'z'), edge('right', 'z')],
      'a',
    )

    const { positions } = layoutDefinition(custom)

    expect(positions.left.x).toBe(-COLUMN_WIDTH / 2)
    expect(positions.right.x).toBe(COLUMN_WIDTH / 2)
    expect(positions.left.y).toBe(positions.right.y)
  })

  it('still places steps the start cannot reach', () => {
    const custom = definition([...CORE.map(name => step(name)), step('orphan', 'agent')], [
      ...DEFAULT_EDGES,
      edge('orphan', 'report'),
    ])

    const { ranks, positions } = layoutDefinition(custom)

    expect(ranks.orphan).toBe(6)
    expect(positions.orphan).toBeDefined()
  })

  it('survives edges that point at unknown steps and an unknown start', () => {
    const custom = definition([step('a'), step('b')], [edge('a', 'ghost'), edge('a', 'b')], 'nope')

    const { positions } = layoutDefinition(custom)

    expect(Object.keys(positions).sort()).toEqual(['a', 'b'])
  })
})
