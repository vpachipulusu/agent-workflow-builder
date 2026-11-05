import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import {
  NotUnlockedError,
  getDefinition,
  getManaged,
  getRuns,
  getSchedule,
  getSignIn,
  messageOf,
  signIn,
  subscribe,
  type DefinitionView,
  type ManagedRow,
  type RunRecord,
  type Schedule,
  type SignIn,
} from '../../api/weekendSaver'
import CustomizePanel from './CustomizePanel'
import ResourcesPanel from './ResourcesPanel'
import RunPanel from './RunPanel'
import SchedulePanel from './SchedulePanel'
import WorkflowGraph from './WorkflowGraph'
import { formatWhen, outcomeText } from './format'
import { NO_RUNS, applyEvent, notesByStep, stepStatuses } from './runState'
import './weekend-saver.css'

type Phase = 'loading' | 'locked' | 'ready' | 'failed'

export default function WeekendSaverPage() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [problem, setProblem] = useState('')
  const [account, setAccount] = useState<SignIn | null>(null)
  const [view, setView] = useState<DefinitionView | null>(null)
  const [managed, setManaged] = useState<ManagedRow[] | null>(null)
  const [schedule, setSchedule] = useState<Schedule | null>(null)
  const [recent, setRecent] = useState<RunRecord[]>([])
  const [runs, dispatch] = useReducer(applyEvent, NO_RUNS)
  const [signingIn, setSigningIn] = useState(false)
  const [disconnected, setDisconnected] = useState(false)
  const statuses = useMemo(() => stepStatuses(runs), [runs])
  const notes = useMemo(() => notesByStep(runs), [runs])
  const managedRequest = useRef(0)

  const refreshManaged = useCallback(() => {
    // Reading live state takes a while; only the newest request may fill the table
    const request = ++managedRequest.current
    getManaged()
      .then(rows => request === managedRequest.current && setManaged(rows))
      .catch(error => setProblem(messageOf(error)))
  }, [])

  const refreshAfterRun = useCallback(() => {
    refreshManaged()
    getRuns()
      .then(result => setRecent(result.recent))
      .catch(error => setProblem(messageOf(error)))
    getSchedule()
      .then(setSchedule)
      .catch(error => setProblem(messageOf(error)))
  }, [refreshManaged])

  useEffect(() => {
    let cancelled = false
    let stop = () => {}

    const load = async () => {
      try {
        const who = await getSignIn()
        if (cancelled) return
        setAccount(who)
        const [definition, when, history] = await Promise.all([
          getDefinition(),
          getSchedule(),
          getRuns(),
        ])
        if (cancelled) return
        setView(definition)
        setSchedule(when)
        setRecent(history.recent)
        setPhase('ready')
        refreshManaged()
        stop = subscribe(
          event => {
            setDisconnected(false)
            dispatch(event)
            // A snapshot without a run also arrives after a reconnect, when a run may
            // have finished unseen
            const idle = event.type === 'snapshot' && event.run === null
            if (event.type === 'run_finished' || idle) refreshAfterRun()
          },
          () => setDisconnected(true),
        )
      } catch (error) {
        if (cancelled) return
        if (error instanceof NotUnlockedError) {
          setPhase('locked')
        } else {
          setProblem(messageOf(error))
          setPhase('failed')
        }
      }
    }
    load()
    return () => {
      cancelled = true
      stop()
    }
  }, [refreshManaged, refreshAfterRun])

  const handleSignIn = async () => {
    setSigningIn(true)
    setProblem('')
    try {
      setAccount(await signIn())
      refreshManaged()
    } catch (error) {
      setProblem(messageOf(error))
    } finally {
      setSigningIn(false)
    }
  }

  if (phase === 'loading') {
    return (
      <div className="empty-state">
        <p>Loading Weekend Saver…</p>
      </div>
    )
  }

  if (phase === 'locked') return <Locked />

  if (phase === 'failed' || !view) {
    return (
      <div className="card ws-card">
        <span className="card-title">Weekend Saver is not available</span>
        <div className="ws-problem" role="alert">
          {problem || 'The backend did not answer.'}
        </div>
        <p className="ws-hint">Check that the backend is running, then reload this page.</p>
      </div>
    )
  }

  return (
    <div className="ws-page">
      <div className="page-header ws-header">
        <div>
          <h1 className="page-title">Weekend Saver</h1>
          <p className="ws-hint">
            Switch Azure resources off for the weekend and back on afterwards.
          </p>
        </div>
        <div className="ws-account">
          {account?.demo && <span className="badge badge-workflow">Demo data</span>}
          {account?.signed_in ? (
            <span className="badge badge-success" title={`Signed in through ${account.source}`}>
              {account.account ?? 'Signed in'}
            </span>
          ) : (
            <button className="btn btn-primary btn-sm" disabled={signingIn} onClick={handleSignIn}>
              {signingIn ? 'Waiting for sign-in…' : 'Sign in to Azure'}
            </button>
          )}
        </div>
      </div>

      {disconnected && (
        <div className="ws-problem" role="alert">
          Live updates have stopped, so what you see may be out of date. Reload the page; if it
          then says it is locked, open a new link from the backend terminal.
        </div>
      )}

      {problem && (
        <div className="ws-problem ws-banner" role="alert">
          {problem}
          <button className="btn btn-secondary btn-sm" onClick={() => setProblem('')}>
            Dismiss
          </button>
        </div>
      )}

      <div className="ws-grid">
        <div className="ws-column">
          <div className="card ws-card ws-graph-card">
            <div className="card-header">
              <span className="card-title">Workflow</span>
              <span className="ws-hint">
                {view.definition.executors.length} steps · dashed lines are early exits and the
                re-plan loop
              </span>
            </div>
            <div className="ws-graph">
              <WorkflowGraph definition={view.definition} statuses={statuses} notes={notes} />
            </div>
          </div>
          <CustomizePanel view={view} onChanged={setView} />
        </div>

        <div className="ws-column">
          <RunPanel runs={runs} managedCount={managed?.length ?? 0} onError={setProblem} />
          <ResourcesPanel rows={managed} onSaved={refreshManaged} />
          <SchedulePanel schedule={schedule} onSaved={setSchedule} />
          <History records={recent} />
        </div>
      </div>
    </div>
  )
}

function Locked() {
  return (
    <div className="card ws-card ws-locked">
      <span className="card-title">Weekend Saver is locked</span>
      <p>
        This part of the builder can really stop and start Azure resources, so it only works in
        a browser that was opened with its own link.
      </p>
      <ol>
        <li>Look at the terminal where the backend is running.</li>
        <li>
          Open the line that starts with <code>Weekend Saver: open</code>. The link works once.
        </li>
        <li>If it was already used, restart the backend to get a new one.</li>
      </ol>
    </div>
  )
}

function History({ records }: { records: RunRecord[] }) {
  return (
    <div className="card ws-card">
      <div className="card-header">
        <span className="card-title">Recent runs</span>
      </div>
      {records.length === 0 ? (
        <p className="ws-hint">No runs yet.</p>
      ) : (
        <ul className="ws-history">
          {records.slice(0, 10).map(record => (
            <li key={record.id} className={record.failed ? 'ws-history-failed' : ''}>
              <span className="ws-history-when">{formatWhen(record.finished_at)}</span>
              <span className="ws-history-what">
                {record.dry_run ? 'dry run' : record.action} · {record.trigger}
              </span>
              <span className="ws-history-status" title={record.error}>
                {outcomeText(record)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
