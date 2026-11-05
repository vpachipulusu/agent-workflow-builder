import { describe, expect, it } from 'vitest'
import type { Plan, RunRecord, RunSnapshot } from '../../api/weekendSaver'
import { NO_RUNS, applyEvent, notesByStep, stepStatuses } from './runState'

const run = (overrides: Partial<RunSnapshot> = {}): RunSnapshot => ({
  id: 'run-1',
  action: 'disable',
  dry_run: false,
  trigger: 'manual',
  started_at: '2026-11-06T18:00:00',
  steps: {},
  pending_plan: null,
  ...overrides,
})

const plan: Plan = {
  action: 'disable',
  actionable: 1,
  total: 1,
  items: [],
  notes: [{ step: 'explain', text: 'Stops one VM.' }],
}

const record: RunRecord = {
  id: 'run-1',
  action: 'disable',
  trigger: 'manual',
  dry_run: false,
  started_at: '2026-11-06T18:00:00',
  finished_at: '2026-11-06T18:01:00',
  status: 'completed',
  failed: false,
  error: '',
  results: [],
  notes: [{ step: 'summary', text: 'All quiet.' }],
}

describe('applyEvent', () => {
  it('takes the run in progress from a snapshot', () => {
    const state = applyEvent(NO_RUNS, { type: 'snapshot', run: run() })

    expect(state.current?.id).toBe('run-1')
  })

  it('forgets the previous result when a new run starts', () => {
    const state = applyEvent({ current: null, last: record }, { type: 'run_started', run: run() })

    expect(state).toEqual({ current: run(), last: null })
  })

  it('records each step as it reports', () => {
    let state = applyEvent(NO_RUNS, { type: 'run_started', run: run() })
    state = applyEvent(state, { type: 'step', step: 'load_targets', status: 'done' })
    state = applyEvent(state, { type: 'step', step: 'resolve_state', status: 'running' })

    expect(state.current?.steps).toEqual({ load_targets: 'done', resolve_state: 'running' })
  })

  it('ignores a step event when no run is known', () => {
    expect(applyEvent(NO_RUNS, { type: 'step', step: 'apply', status: 'done' })).toBe(NO_RUNS)
  })

  it('shows the plan when approval is needed', () => {
    let state = applyEvent(NO_RUNS, { type: 'run_started', run: run() })
    state = applyEvent(state, { type: 'approval_required', run_id: 'run-1', plan })

    expect(state.current?.pending_plan).toBe(plan)
    expect(state.current?.steps.approval).toBe('waiting')
  })

  it('takes the plan away once the approval was answered', () => {
    let state = applyEvent(NO_RUNS, { type: 'run_started', run: run() })
    state = applyEvent(state, { type: 'approval_required', run_id: 'run-1', plan })
    state = applyEvent(state, { type: 'approval_answered', run_id: 'run-1', approved: true })

    expect(state.current?.pending_plan).toBeNull()
    expect(state.current?.steps.approval).toBe('running')
  })

  it('ignores an answer that belongs to another run', () => {
    let state = applyEvent(NO_RUNS, { type: 'run_started', run: run() })
    state = applyEvent(state, { type: 'approval_required', run_id: 'run-1', plan })

    expect(applyEvent(state, { type: 'approval_answered', run_id: 'other', approved: true })).toBe(
      state,
    )
  })

  it('ignores an approval request for another run', () => {
    const started = applyEvent(NO_RUNS, { type: 'run_started', run: run() })

    expect(applyEvent(started, { type: 'approval_required', run_id: 'other', plan })).toBe(started)
  })

  it('keeps the outcome once the run has finished', () => {
    const started = applyEvent(NO_RUNS, { type: 'run_started', run: run() })

    expect(applyEvent(started, { type: 'run_finished', run: record })).toEqual({
      current: null,
      last: record,
    })
  })

  it('does not change the state it was given', () => {
    const started = applyEvent(NO_RUNS, { type: 'run_started', run: run() })
    const before = JSON.stringify(started)

    applyEvent(started, { type: 'step', step: 'apply', status: 'running' })

    expect(JSON.stringify(started)).toBe(before)
  })
})

describe('stepStatuses', () => {
  it('is empty when nothing is running', () => {
    expect(stepStatuses({ current: null, last: record })).toEqual({})
  })

  it('shows approval as waiting while the plan is pending', () => {
    const state = { current: run({ steps: { approval: 'waiting' }, pending_plan: plan }), last: null }

    expect(stepStatuses(state)).toEqual({ approval: 'waiting' })
  })

  it('returns the same object while nothing changes, so the graph is not redrawn', () => {
    const idle = { current: null, last: null }

    expect(stepStatuses(idle)).toBe(stepStatuses({ current: null, last: record }))
  })
})

describe('notesByStep', () => {
  it('uses the notes that came with the pending plan', () => {
    const state = { current: run({ pending_plan: plan }), last: null }

    expect(notesByStep(state)).toEqual({ explain: 'Stops one VM.' })
  })

  it('uses the notes of the last finished run', () => {
    expect(notesByStep({ current: null, last: record })).toEqual({ summary: 'All quiet.' })
  })

  it('copes with runs recorded before notes existed', () => {
    const old = { ...record, notes: undefined }

    expect(notesByStep({ current: null, last: old })).toEqual({})
  })
})
