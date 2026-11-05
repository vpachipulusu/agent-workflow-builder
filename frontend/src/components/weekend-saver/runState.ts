// What the page knows about runs, kept up to date from the server's event stream.

import type { RunEvent, RunRecord, RunSnapshot } from '../../api/weekendSaver'

export interface RunState {
  /** The run in progress, if any. */
  current: RunSnapshot | null
  /** The most recently finished run, kept so its outcome stays on screen. */
  last: RunRecord | null
}

export const NO_RUNS: RunState = { current: null, last: null }

export function applyEvent(state: RunState, event: RunEvent): RunState {
  switch (event.type) {
    case 'snapshot':
      return { ...state, current: event.run }
    case 'run_started':
      return { current: event.run, last: null }
    case 'step': {
      if (!state.current) return state
      const steps = { ...state.current.steps, [event.step]: event.status }
      return { ...state, current: { ...state.current, steps } }
    }
    case 'approval_required': {
      if (!state.current || state.current.id !== event.run_id) return state
      const steps = { ...state.current.steps, approval: 'waiting' as const }
      return { ...state, current: { ...state.current, steps, pending_plan: event.plan } }
    }
    case 'approval_answered': {
      if (!state.current || state.current.id !== event.run_id) return state
      const steps = { ...state.current.steps, approval: 'running' as const }
      return { ...state, current: { ...state.current, steps, pending_plan: null } }
    }
    case 'run_finished':
      return { current: null, last: event.run }
    default:
      return state
  }
}

const NO_STATUSES: Record<string, string> = {}

/** The step statuses to draw: the live run's, and none once it has finished. */
export function stepStatuses(state: RunState): Record<string, string> {
  return state.current?.steps ?? NO_STATUSES
}

/** Notes to show on the graph, by step name. */
export function notesByStep(state: RunState): Record<string, string> {
  const notes = state.current?.pending_plan?.notes ?? state.last?.notes ?? []
  return Object.fromEntries(notes.map(note => [note.step, note.text]))
}
