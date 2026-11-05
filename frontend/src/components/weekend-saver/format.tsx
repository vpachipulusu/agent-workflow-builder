import type { Note, ResultRow } from '../../api/weekendSaver'

export const WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

const STATUS_TEXT: Record<string, string> = {
  completed: 'Completed',
  dry_run: 'Dry run, nothing changed',
  rejected: 'Rejected, nothing changed',
  stopped: 'Stopped by a workflow step, nothing changed',
  invalid: 'Failed before any change',
  crashed: 'Stopped unexpectedly',
  not_run: 'Did not run',
}

export const statusText = (status: string) => STATUS_TEXT[status] ?? status

/** How a finished run turned out, in words; a failure is never worded as a quiet stop. */
export function outcomeText(run: { status: string; failed: boolean }): string {
  if (run.failed && run.status === 'completed') return 'Completed with failures'
  // A gate that could not get an answer, unlike a gate that decided to stop
  if (run.failed && run.status === 'stopped') return 'Failed before any change'
  return statusText(run.status)
}

export function formatWhen(iso: string | null): string {
  if (!iso) return '—'
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return iso
  return when.toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const shortType = (resourceType: string) => resourceType.split('/').pop() ?? resourceType

/** A server value made safe to use as part of a class name. */
export const classToken = (value: string) => value.toLowerCase().replace(/[^a-z0-9_-]/g, '')

export function ResultTable({ rows, label }: { rows: ResultRow[]; label: string }) {
  if (rows.length === 0) return null
  return (
    // Focusable so a keyboard user can scroll it sideways on a narrow screen
    <div className="ws-table-wrap" role="region" aria-label={label} tabIndex={0}>
      <table className="ws-table">
        <thead>
          <tr>
            <th>Resource</th>
            <th>Outcome</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.resource_id}>
              <td title={row.resource_id}>{row.name}</td>
              <td>
                <span className={`ws-outcome ws-outcome-${classToken(row.outcome)}`}>
                  {row.outcome}
                </span>
              </td>
              <td>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function NoteList({ notes }: { notes: Note[] | undefined }) {
  if (!notes || notes.length === 0) return null
  return (
    <ul className="ws-notes">
      {notes.map((note, index) => (
        <li key={`${note.step}-${index}`}>
          <span className="ws-step-name">{note.step}</span>
          <span>{note.text}</span>
        </li>
      ))}
    </ul>
  )
}
