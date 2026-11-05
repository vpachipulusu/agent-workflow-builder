import { useEffect, useMemo, useRef, useState } from 'react'

import {
  getDiscovered,
  messageOf,
  saveManaged,
  type ManagedRow,
  type PickerRow,
} from '../../api/weekendSaver'
import { classToken, shortType } from './format'

const ORDER_LIMIT = 1000

interface Props {
  rows: ManagedRow[] | null
  onSaved: () => void
}

export default function ResourcesPanel({ rows, onSaved }: Props) {
  const [picking, setPicking] = useState(false)
  const opener = useRef<HTMLButtonElement>(null)

  const closePicker = (saved: boolean) => {
    setPicking(false)
    // A closing dialog does not reliably hand focus back by itself
    opener.current?.focus()
    if (saved) onSaved()
  }

  return (
    <div className="card ws-card">
      <div className="card-header">
        <span className="card-title">Managed resources</span>
        <button
          ref={opener}
          className="btn btn-secondary btn-sm"
          onClick={() => setPicking(true)}
        >
          Manage resources
        </button>
      </div>

      {rows === null && <p className="ws-hint">Reading the current state…</p>}
      {rows?.length === 0 && (
        <p className="ws-hint">
          Nothing is managed yet. Choose the resources to switch off over the weekend.
        </p>
      )}
      {rows && rows.length > 0 && (
        <div className="ws-table-wrap" role="region" aria-label="Managed resources" tabIndex={0}>
          <table className="ws-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Group</th>
                <th>State</th>
                <th>Order</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id}>
                  <td title={row.id}>{row.name}</td>
                  <td>{shortType(row.type)}</td>
                  <td>{row.resource_group}</td>
                  <td>
                    <span className={`ws-state ws-state-${classToken(row.state)}`}>
                      {row.state}
                    </span>
                    {row.disabled_by_us && <span className="ws-flag">stopped by this tool</span>}
                    {row.skip && <span className="ws-flag">tagged to skip</span>}
                    {row.error && <span className="ws-flag ws-flag-error">{row.error}</span>}
                  </td>
                  <td>{row.order}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {picking && <Picker onClose={closePicker} />}
    </div>
  )
}

interface Choice {
  checked: boolean
  // Kept as typed, so "-" and an empty box are possible on the way to a number
  order: string
}

function parseOrder(text: string): number {
  const value = Math.round(Number(text))
  if (!Number.isFinite(value)) return 0
  return Math.max(-ORDER_LIMIT, Math.min(ORDER_LIMIT, value))
}

function Picker({ onClose }: { onClose: (saved: boolean) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [found, setFound] = useState<PickerRow[] | null>(null)
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [filter, setFilter] = useState('')
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    let cancelled = false
    getDiscovered()
      .then(rows => {
        if (cancelled) return
        setFound(rows)
        setChoices(
          Object.fromEntries(
            rows.map(row => [
              row.resource_id,
              { checked: row.managed, order: String(row.order) },
            ]),
          ),
        )
      })
      .catch(error => !cancelled && setProblem(messageOf(error)))
    return () => {
      cancelled = true
      element?.close()
    }
  }, [])

  const shown = useMemo(() => {
    const wanted = filter.trim().toLowerCase()
    if (!found || !wanted) return found ?? []
    return found.filter(row =>
      [row.name, row.resource_type, row.resource_group, row.subscription_name].some(text =>
        text.toLowerCase().includes(wanted),
      ),
    )
  }, [found, filter])

  const change = (id: string, patch: Partial<Choice>) =>
    setChoices(current => ({ ...current, [id]: { ...current[id], ...patch } }))

  const save = async () => {
    // Everything ticked is saved, including rows the filter is hiding right now
    const resources = (found ?? [])
      .filter(row => choices[row.resource_id]?.checked)
      .map(row => ({ id: row.resource_id, order: parseOrder(choices[row.resource_id].order) }))
    const clearing = resources.length === 0 && (found ?? []).some(row => row.managed)
    if (
      clearing &&
      !window.confirm('Stop managing every resource? Scheduled runs will then do nothing.')
    ) {
      return
    }
    setSaving(true)
    setProblem('')
    try {
      await saveManaged(resources)
      onClose(true)
    } catch (error) {
      setProblem(messageOf(error))
      setSaving(false)
    }
  }

  const selected = Object.values(choices).filter(choice => choice.checked).length

  return (
    <dialog
      ref={dialog}
      className="ws-dialog ws-dialog-wide"
      aria-labelledby="ws-picker-title"
      onCancel={event => {
        event.preventDefault()
        onClose(false)
      }}
    >
      <h2 id="ws-picker-title">Choose the resources to manage</h2>
      <p className="ws-hint">
        Everything your sign-in can see is listed. Greyed-out types cannot be stopped and
        started. Lower order is disabled first and enabled last.
      </p>

      {found === null && !problem && <p className="ws-hint">Looking for resources…</p>}
      {problem && (
        <div className="ws-problem" role="alert">
          {problem}
        </div>
      )}
      {found?.length === 0 && <p className="ws-hint">No resources were found.</p>}

      {found && found.length > 0 && (
        <>
          <input
            type="search"
            className="form-input ws-filter"
            aria-label="Filter the list by name, type, group or subscription"
            placeholder="Filter by name, type, group or subscription"
            value={filter}
            onChange={event => setFilter(event.target.value)}
          />
          <div className="ws-table-wrap ws-picker-list">
            <table className="ws-table">
              <thead>
                <tr>
                  <th aria-label="Managed" />
                  <th>Name</th>
                  <th>Type</th>
                  <th>Group</th>
                  <th>Subscription</th>
                  <th>Order</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(row => {
                  const choice = choices[row.resource_id] ?? { checked: false, order: '0' }
                  return (
                    <tr
                      key={row.resource_id}
                      className={row.supported ? '' : 'ws-row-unsupported'}
                    >
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Manage ${row.name}`}
                          checked={choice.checked}
                          disabled={!row.supported}
                          onChange={event =>
                            change(row.resource_id, { checked: event.target.checked })
                          }
                        />
                      </td>
                      <td title={row.resource_id}>{row.name}</td>
                      <td>{shortType(row.resource_type) || '—'}</td>
                      <td>{row.resource_group}</td>
                      <td>{row.subscription_name}</td>
                      <td>
                        {row.supported ? (
                          <input
                            type="number"
                            className="ws-order"
                            aria-label={`Order of ${row.name}`}
                            min={-ORDER_LIMIT}
                            max={ORDER_LIMIT}
                            step={1}
                            value={choice.order}
                            disabled={!choice.checked}
                            onChange={event =>
                              change(row.resource_id, { order: event.target.value })
                            }
                          />
                        ) : (
                          <span className="ws-flag">not supported</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {shown.length === 0 && <p className="ws-hint ws-empty">Nothing matches the filter.</p>}
          </div>
        </>
      )}

      <div className="ws-actions ws-actions-end">
        <span className="ws-hint">{selected} selected</span>
        <button className="btn btn-secondary" disabled={saving} onClick={() => onClose(false)}>
          Cancel
        </button>
        <button className="btn btn-primary" disabled={saving || found === null} onClick={save}>
          {saving ? 'Saving…' : 'Save selection'}
        </button>
      </div>
    </dialog>
  )
}
