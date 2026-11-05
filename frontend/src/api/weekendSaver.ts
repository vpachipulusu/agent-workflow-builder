// Client for the protected Weekend Saver app mounted at /ws.
//
// Unlike the builder's open /api, these calls need the session cookie set by the
// one-time link printed in the backend terminal, and every change must carry the
// X-Weekend-Saver header (a cross-site page cannot send it).

const BASE = '/ws/api'

export type StepType = 'builtin' | 'agent' | 'function'

export interface StepDef {
  name: string
  type: StepType
  instructions: string
  ref?: string
  config?: Record<string, boolean | number>
}

export interface EdgeDef {
  source: string
  target: string
  condition: string | null
  fan_in: boolean
}

export interface Definition {
  name: string
  description: string
  start: string
  executors: StepDef[]
  edges: EdgeDef[]
}

export interface CatalogStep {
  name: string
  ref: string
  description: string
  outcomes: Record<string, string>
  settings: {
    name: string
    type: string
    default: boolean | number
    description: string
    minimum: number | null
    maximum: number | null
  }[]
}

export interface DefinitionView {
  definition: Definition
  errors: string[]
  is_default: boolean
  catalog: CatalogStep[]
}

export interface SignIn {
  signed_in: boolean
  account: string | null
  tenant_id: string | null
  source: string | null
  demo: boolean
}

export interface Note {
  step: string
  text: string
}

export interface ResultRow {
  resource_id: string
  name: string
  outcome: 'planned' | 'succeeded' | 'skipped' | 'failed'
  detail: string
  state: string
}

export type Action = 'disable' | 'enable'
export type StepStatus = 'running' | 'done' | 'failed' | 'waiting'

export interface Plan {
  action: Action
  actionable: number
  total: number
  items: ResultRow[]
  notes: Note[]
}

export interface RunSnapshot {
  id: string
  action: Action
  dry_run: boolean
  trigger: string
  started_at: string
  steps: Record<string, StepStatus>
  pending_plan: Plan | null
}

export interface RunRecord {
  id: string
  action: Action
  trigger: string
  dry_run: boolean
  started_at: string
  finished_at: string
  status: string
  failed: boolean
  error: string
  results: ResultRow[]
  notes?: Note[]
}

export type RunEvent =
  | { type: 'snapshot'; run: RunSnapshot | null }
  | { type: 'run_started'; run: RunSnapshot }
  | { type: 'step'; step: string; status: StepStatus }
  | { type: 'approval_required'; run_id: string; plan: Plan }
  | { type: 'approval_answered'; run_id: string; approved: boolean }
  | { type: 'run_finished'; run: RunRecord }

export interface ManagedRow {
  id: string
  name: string
  order: number
  type: string
  resource_group: string
  subscription_id: string
  state: string
  skip: boolean
  disabled_by_us: boolean
  error: string
  // What the workflow last did to it; null when it never changed it
  last_change: LastChange | null
}

export interface LastChange {
  action: string
  outcome: string
  at: string
  detail: string
}

/** One attempt of the workflow to switch a resource off or on. */
export interface Change extends LastChange {
  resource_id: string
  name: string
  state: string
}

/** A subscription or resource group, with how much it holds. */
export interface SubscriptionSummary {
  subscription_id: string
  name: string
  total: number
  // How many of them can be stopped and started
  supported: number
}

export interface GroupSummary {
  subscription_id: string
  resource_group: string
  total: number
  supported: number
}

export interface FoundResource {
  resource_id: string
  name: string
  resource_type: string
  resource_group: string
  subscription_id: string
  location: string
  supported: boolean
}

/** A saved resource as it is on disk, without its live state. */
export interface SelectedRow {
  id: string
  name: string
  order: number
  type: string
  resource_group: string
  subscription_id: string
}

export interface WeeklyTime {
  weekday: number
  time: string
}

export interface Schedule {
  enabled: boolean
  disable_at: WeeklyTime
  enable_at: WeeklyTime
  next: { disable: string | null; enable: string | null }
  notices: string[]
}

/** The page has no session yet: it was not opened through the one-time link. */
export class NotUnlockedError extends Error {}

/** The server refused the request; `errors` lists every reason when there are several. */
export class ApiError extends Error {
  errors: string[]

  constructor(message: string, errors: string[] = []) {
    super(message)
    this.errors = errors
  }
}

export const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error)

async function call<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Weekend-Saver': '1' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let envelope: { success: boolean; data: unknown; error: string | null }
  try {
    envelope = await response.json()
  } catch {
    throw new ApiError(`The server did not answer properly (HTTP ${response.status}).`)
  }
  if (response.status === 401) throw new NotUnlockedError(envelope.error ?? 'Not unlocked')
  if (!envelope.success) {
    const errors = (envelope.data as { errors?: string[] } | null)?.errors ?? []
    throw new ApiError(envelope.error ?? `Request failed (HTTP ${response.status}).`, errors)
  }
  return envelope.data as T
}

export const getSignIn = () => call<SignIn>('/auth')
export const signIn = () => call<SignIn>('/auth/login', 'POST')

export const getDefinition = () => call<DefinitionView>('/definition')
export const saveDefinition = (definition: Definition) =>
  call<DefinitionView>('/definition', 'PUT', { definition })
export const editDefinition = (prompt: string) =>
  call<DefinitionView>('/definition/edit', 'POST', { prompt })
export const resetDefinition = () => call<DefinitionView>('/definition/reset', 'POST')

export const getManaged = () => call<ManagedRow[]>('/resources')
export const getSelection = () => call<SelectedRow[]>('/selection')
export const saveManaged = (resources: { id: string; order: number }[]) =>
  call<{ saved: number }>('/resources', 'PUT', { resources })

const query = (values: Record<string, string>) => new URLSearchParams(values).toString()

// Azure is looked through one level at a time; nothing is loaded before it is opened
export const getSubscriptions = () => call<SubscriptionSummary[]>('/discovery/subscriptions')
export const getGroups = (subscription: string) =>
  call<GroupSummary[]>(`/discovery/groups?${query({ subscription })}`)
export const getGroupResources = (subscription: string, group: string) =>
  call<FoundResource[]>(`/discovery/resources?${query({ subscription, group })}`)

export const getActivity = (resource: string, limit: number) =>
  call<Change[]>(`/activity?${query({ resource, limit: String(limit) })}`)

export const getRuns = () => call<{ current: RunSnapshot | null; recent: RunRecord[] }>('/runs')
export const startRun = (action: Action, dryRun: boolean, ignorePriorState = false) =>
  call<{ run_id: string }>('/runs', 'POST', {
    action,
    dry_run: dryRun,
    ignore_prior_state: ignorePriorState,
  })
export const answerApproval = (runId: string, approved: boolean) =>
  call<{ approved: boolean }>('/runs/approval', 'POST', { run_id: runId, approved })

export const getSchedule = () => call<Schedule>('/schedule')
export const saveSchedule = (schedule: Pick<Schedule, 'enabled' | 'disable_at' | 'enable_at'>) =>
  call<Schedule>('/schedule', 'PUT', schedule)

/**
 * Follow runs live. The first event, and the first after every reconnect, is a
 * snapshot of the run in progress. `onClosed` is called when the browser gives up on
 * the stream (for example because the session is gone), which it does not undo itself.
 */
export function subscribe(onEvent: (event: RunEvent) => void, onClosed: () => void): () => void {
  const source = new EventSource(`${BASE}/events`)
  source.onmessage = message => {
    let event: RunEvent
    try {
      event = JSON.parse(message.data) as RunEvent
    } catch {
      return
    }
    onEvent(event)
  }
  source.onerror = () => {
    // While it is only CONNECTING the browser is retrying on its own
    if (source.readyState === EventSource.CLOSED) onClosed()
  }
  return () => source.close()
}
