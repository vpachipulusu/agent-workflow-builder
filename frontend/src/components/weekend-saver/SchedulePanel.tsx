import { useEffect, useRef, useState } from 'react'

import {
  messageOf,
  saveSchedule,
  type Schedule,
  type WeeklyTime,
} from '../../api/weekendSaver'
import { WEEKDAYS, formatWhen } from './format'

interface Props {
  schedule: Schedule | null
  onSaved: (schedule: Schedule) => void
}

export default function SchedulePanel({ schedule, onSaved }: Props) {
  const [draft, setDraft] = useState<Schedule | null>(schedule)
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState('')

  // What the form was last filled from. The page reloads the schedule after every run
  // (for its notices), and that must not wipe out edits that are not saved yet.
  const filledFrom = useRef<Schedule | null>(schedule)

  useEffect(() => {
    setDraft(current => {
      const untouched = current === null || sameSettings(current, filledFrom.current)
      filledFrom.current = schedule
      return untouched ? schedule : current
    })
  }, [schedule])

  if (!draft) {
    return (
      <div className="card ws-card">
        <span className="card-title">Schedule</span>
        <p className="ws-hint">Loading…</p>
      </div>
    )
  }

  const changed = !sameSettings(draft, schedule)

  const save = async () => {
    setSaving(true)
    setProblem('')
    try {
      const saved = await saveSchedule({
        enabled: draft.enabled,
        disable_at: draft.disable_at,
        enable_at: draft.enable_at,
      })
      setDraft(saved)
      filledFrom.current = saved
      onSaved(saved)
    } catch (error) {
      setProblem(messageOf(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card ws-card">
      <div className="card-header">
        <span className="card-title">Schedule</span>
        <span className={`badge ${draft.enabled ? 'badge-success' : 'badge-workflow'}`}>
          {draft.enabled ? 'On' : 'Off'}
        </span>
      </div>

      <label className="ws-check">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={event => setDraft({ ...draft, enabled: event.target.checked })}
        />
        Run automatically every week
      </label>

      <WeeklyTimeRow
        label="Disable on"
        value={draft.disable_at}
        onChange={disable_at => setDraft({ ...draft, disable_at })}
      />
      <WeeklyTimeRow
        label="Enable on"
        value={draft.enable_at}
        onChange={enable_at => setDraft({ ...draft, enable_at })}
      />

      <p className="ws-hint">
        Times are this computer's local time. Scheduled runs are approved in advance, and only
        happen while the backend is running and the computer is awake.
      </p>
      {schedule?.enabled && (
        <p className="ws-hint">
          Next disable: {formatWhen(schedule.next.disable)} · Next enable:{' '}
          {formatWhen(schedule.next.enable)}
        </p>
      )}

      {schedule?.notices.map((notice, index) => (
        <div key={`${index}-${notice}`} className="ws-problem" role="status">
          {notice}
        </div>
      ))}
      {problem && (
        <div className="ws-problem" role="alert">
          {problem}
        </div>
      )}

      <div className="ws-actions">
        <button className="btn btn-primary btn-sm" disabled={saving || !changed} onClick={save}>
          {saving ? 'Saving…' : 'Save schedule'}
        </button>
      </div>
    </div>
  )
}

/** Whether two schedules ask for the same thing, ignoring what the server adds. */
function sameSettings(a: Schedule | null, b: Schedule | null): boolean {
  if (a === null || b === null) return a === b
  const settings = (s: Schedule) => [
    s.enabled,
    s.disable_at.weekday,
    s.disable_at.time,
    s.enable_at.weekday,
    s.enable_at.time,
  ]
  return settings(a).join('|') === settings(b).join('|')
}

function WeeklyTimeRow({
  label,
  value,
  onChange,
}: {
  label: string
  value: WeeklyTime
  onChange: (value: WeeklyTime) => void
}) {
  return (
    <div className="ws-weekly">
      <span className="form-label">{label}</span>
      <select
        className="form-select"
        aria-label={`${label}: day`}
        value={value.weekday}
        onChange={event => onChange({ ...value, weekday: Number(event.target.value) })}
      >
        {WEEKDAYS.map((day, index) => (
          <option key={day} value={index}>
            {day}
          </option>
        ))}
      </select>
      <input
        type="time"
        className="form-input"
        aria-label={`${label}: time`}
        value={value.time}
        onChange={event => event.target.value && onChange({ ...value, time: event.target.value })}
      />
    </div>
  )
}
