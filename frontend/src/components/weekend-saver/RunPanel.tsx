import { useEffect, useRef, useState } from 'react'

import {
  answerApproval,
  messageOf,
  startRun,
  type Action,
  type RunRecord,
  type RunSnapshot,
} from '../../api/weekendSaver'
import { NoteList, ResultTable, outcomeText } from './format'
import type { RunState } from './runState'

interface Props {
  runs: RunState
  managedCount: number
  onError: (message: string) => void
}

export default function RunPanel({ runs, managedCount, onError }: Props) {
  const [starting, setStarting] = useState(false)
  const [everythingStopped, setEverythingStopped] = useState(false)
  const busy = starting || runs.current !== null
  const nothingManaged = managedCount === 0

  const start = async (action: Action, dryRun: boolean) => {
    setStarting(true)
    try {
      await startRun(action, dryRun, action === 'enable' && everythingStopped)
    } catch (error) {
      onError(messageOf(error))
    } finally {
      setStarting(false)
    }
  }

  const last = runs.last

  return (
    <div className="card ws-card">
      <div className="card-header">
        <span className="card-title">Run</span>
        {runs.current && (
          <span className="badge badge-workflow" role="status">
            {runs.current.dry_run ? 'Dry run' : `${title(runs.current.action)} run`} in progress
          </span>
        )}
      </div>

      <div className="ws-actions">
        <button
          className="btn btn-secondary btn-sm"
          disabled={busy || nothingManaged}
          onClick={() => start('disable', true)}
        >
          Dry run
        </button>
        <button
          className="btn btn-accent btn-sm"
          disabled={busy || nothingManaged}
          onClick={() => start('disable', false)}
        >
          Disable now
        </button>
        <button
          className="btn btn-primary btn-sm"
          disabled={busy || nothingManaged}
          onClick={() => start('enable', false)}
        >
          Enable now
        </button>
      </div>
      <label className="ws-check">
        <input
          type="checkbox"
          checked={everythingStopped}
          onChange={event => setEverythingStopped(event.target.checked)}
        />
        Enable every managed resource that is stopped, even if this tool did not stop it
      </label>

      {nothingManaged && (
        <p className="ws-hint">Choose resources to manage first; a run has nothing to do yet.</p>
      )}

      {last && (
        <div className={`ws-result ${last.failed ? 'ws-result-failed' : ''}`}>
          <strong role="status">{headline(last)}</strong>
          {last.error && <p>{last.error}</p>}
          <NoteList notes={last.notes} />
          <ResultTable rows={last.results} label="Results of the last run" />
        </div>
      )}

      {runs.current?.pending_plan && <ApprovalDialog run={runs.current} />}
    </div>
  )
}

const title = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

function headline(record: RunRecord): string {
  if (record.dry_run) return outcomeText(record)
  return `${title(record.action)}: ${outcomeText(record).toLowerCase()}`
}

// Shown only while the run waits for an answer: the page takes the plan away again
// when the server says the approval was answered (here or in another tab).
function ApprovalDialog({ run }: { run: RunSnapshot }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [answering, setAnswering] = useState(false)
  const [problem, setProblem] = useState('')
  const plan = run.pending_plan!

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    return () => element?.close()
  }, [])

  const answer = async (approved: boolean) => {
    setAnswering(true)
    setProblem('')
    try {
      await answerApproval(run.id, approved)
    } catch (error) {
      // Said here, because the page behind a modal dialog cannot be read
      setProblem(messageOf(error))
      setAnswering(false)
    }
  }

  // Closing without an answer would leave the run waiting, so Escape is refused, and
  // if the browser closes the dialog anyway it is opened again.
  const reopen = () => {
    const element = dialog.current
    if (element?.isConnected && !element.open) element.showModal()
  }

  return (
    <dialog
      ref={dialog}
      className="ws-dialog"
      aria-labelledby="ws-approval-title"
      onCancel={event => event.preventDefault()}
      onClose={reopen}
    >
      <h2 id="ws-approval-title">
        {title(plan.action)} {plan.actionable} of {plan.total} resources?
      </h2>
      <p className="ws-hint">
        The plan is worked out again from the current state of Azure once you approve it.
      </p>
      <NoteList notes={plan.notes} />
      <ResultTable rows={plan.items} label="The plan" />
      {problem && (
        <div className="ws-problem" role="alert">
          {problem}
        </div>
      )}
      <div className="ws-actions ws-actions-end">
        <button className="btn btn-secondary" disabled={answering} onClick={() => answer(false)}>
          Reject
        </button>
        <button className="btn btn-primary" disabled={answering} onClick={() => answer(true)}>
          Approve and {plan.action}
        </button>
      </div>
    </dialog>
  )
}
