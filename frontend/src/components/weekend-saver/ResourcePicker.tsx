import { useEffect, useRef, useState } from 'react'

import {
  getSelection,
  getSubscriptions,
  messageOf,
  saveManaged,
  type FoundResource,
  type SelectedRow,
  type SubscriptionSummary,
} from '../../api/weekendSaver'
import ResourceTree from './ResourceTree'
import { shortType } from './format'
import { Loaded, type Lazy } from './lazy'
import {
  ORDER_LIMIT,
  isClearing,
  isPicked,
  listed,
  reorder,
  startFrom,
  tick,
  toPick,
  toSave,
  untick,
  type Picked,
  type PickerState,
} from './pickerState'

interface Start {
  saved: SelectedRow[]
  subscriptions: SubscriptionSummary[]
}

/** Choose what to manage by opening subscriptions and groups; nothing loads unasked. */
export default function ResourcePicker({ onClose }: { onClose: (saved: boolean) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [start, setStart] = useState<Lazy<Start>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<PickerState>(() => startFrom([]))
  const [filter, setFilter] = useState('')
  const [showOther, setShowOther] = useState(false)
  const [problem, setProblem] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
    return () => element?.close()
  }, [])

  useEffect(() => {
    let cancelled = false
    setStart({ status: 'loading' })
    Promise.all([getSelection(), getSubscriptions()]).then(
      ([saved, subscriptions]) => {
        if (cancelled) return
        setState(startFrom(saved))
        setStart({ status: 'ready', data: { saved, subscriptions } })
      },
      error => !cancelled && setStart({ status: 'failed', error: messageOf(error) }),
    )
    return () => {
      cancelled = true
    }
  }, [attempt])

  const toggle = (pick: Picked, checked: boolean) =>
    setState(current => (checked ? tick(current, pick) : untick(current, pick.id)))
  const toggleFound = (resource: FoundResource, checked: boolean) =>
    toggle(toPick(resource), checked)
  const setOrder = (id: string, order: string) =>
    setState(current => reorder(current, id, order))

  const save = async (saved: SelectedRow[]) => {
    if (
      isClearing(saved, state.selection) &&
      !window.confirm('Stop managing every resource? Scheduled runs will then do nothing.')
    ) {
      return
    }
    setSaving(true)
    setProblem('')
    try {
      await saveManaged(toSave(state.selection))
      onClose(true)
    } catch (error) {
      setProblem(messageOf(error))
      setSaving(false)
    }
  }

  const ready = start.status === 'ready' ? start.data : null

  return (
    <dialog
      ref={dialog}
      className="ws-dialog ws-dialog-wide"
      aria-labelledby="ws-picker-title"
      onCancel={event => {
        event.preventDefault()
        // Escape does what Cancel does, and Cancel is off while a save is under way
        if (!saving) onClose(false)
      }}
    >
      <h2 id="ws-picker-title">Choose the resources to manage</h2>
      <p className="ws-hint">
        Open a subscription, then a resource group, and tick what to switch off over the
        weekend. Lower order is disabled first and enabled last.
      </p>

      {problem && (
        <div className="ws-problem" role="alert">
          {problem}
        </div>
      )}

      <Loaded entry={start} what="your subscriptions" onRetry={() => setAttempt(n => n + 1)}>
        {({ subscriptions }) => (
          <>
            <div className="ws-picker-tools">
              <input
                type="search"
                className="form-input ws-filter"
                aria-label="Filter the resources of the open groups by name or type"
                placeholder="Filter open groups by name or type"
                value={filter}
                onChange={event => setFilter(event.target.value)}
              />
              <label className="ws-check">
                <input
                  type="checkbox"
                  checked={showOther}
                  onChange={event => setShowOther(event.target.checked)}
                />
                Show other types
              </label>
            </div>
            <div className="ws-picker-list">
              <SelectedList state={state} onToggle={toggle} onOrder={setOrder} />
              <ResourceTree
                subscriptions={subscriptions}
                selection={state.selection}
                filter={filter}
                showOther={showOther}
                onToggle={toggleFound}
                onOrder={setOrder}
              />
            </div>
          </>
        )}
      </Loaded>

      <div className="ws-actions ws-actions-end">
        <span className="ws-hint">{Object.keys(state.selection).length} selected</span>
        <button className="btn btn-secondary" disabled={saving} onClick={() => onClose(false)}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={saving || ready === null}
          onClick={() => ready && save(ready.saved)}
        >
          {saving ? 'Saving…' : 'Save selection'}
        </button>
      </div>
    </dialog>
  )
}

interface SelectedListProps {
  state: PickerState
  onToggle: (pick: Picked, checked: boolean) => void
  onOrder: (id: string, order: string) => void
}

/**
 * What is ticked, wherever it is, so it can be changed without opening its group.
 * Something unticked stays listed until the dialog closes, so a slip can be undone.
 */
function SelectedList({ state, onToggle, onOrder }: SelectedListProps) {
  const picks = listed(state)
  if (picks.length === 0) return null
  return (
    <details className="ws-selected" open>
      <summary>Selected ({Object.keys(state.selection).length})</summary>
      <table className="ws-table">
        <thead>
          <tr>
            <th aria-label="Managed" />
            <th>Name</th>
            <th>Type</th>
            <th>Group</th>
            <th>Order</th>
          </tr>
        </thead>
        <tbody>
          {picks.map(pick => {
            const checked = isPicked(state.selection, pick.id)
            return (
              <tr key={pick.id} className={checked ? '' : 'ws-row-unsupported'}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Manage ${pick.name}`}
                    checked={checked}
                    onChange={event => onToggle(pick, event.target.checked)}
                  />
                </td>
                <td title={pick.id}>{pick.name}</td>
                <td>{shortType(pick.type) || '—'}</td>
                <td>{pick.resource_group || '—'}</td>
                <td>
                  <input
                    type="number"
                    className="ws-order"
                    aria-label={`Order of ${pick.name}`}
                    min={-ORDER_LIMIT}
                    max={ORDER_LIMIT}
                    step={1}
                    value={pick.order}
                    disabled={!checked}
                    onChange={event => onOrder(pick.id, event.target.value)}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </details>
  )
}
