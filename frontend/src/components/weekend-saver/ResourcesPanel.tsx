import { Fragment, useRef, useState } from 'react'

import type { LastChange, ManagedRow } from '../../api/weekendSaver'
import ResourceHistory from './ResourceHistory'
import ResourcePicker from './ResourcePicker'
import { changeText, classToken, formatWhen, shortType } from './format'

const COLUMNS = 4

interface Props {
  rows: ManagedRow[] | null
  onSaved: () => void
}

export default function ResourcesPanel({ rows, onSaved }: Props) {
  const [picking, setPicking] = useState(false)
  const [opened, setOpened] = useState<Record<string, boolean>>({})
  const opener = useRef<HTMLButtonElement>(null)

  const closePicker = (saved: boolean) => {
    setPicking(false)
    // A closing dialog does not reliably hand focus back by itself
    opener.current?.focus()
    if (saved) onSaved()
  }

  const toggle = (id: string) => setOpened(current => ({ ...current, [id]: !current[id] }))
  const switchedOff = rows?.filter(row => row.disabled_by_us).length ?? 0

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
        <>
          <p className="ws-hint">
            {switchedOff} of {rows.length} switched off by Weekend Saver. Open a resource to
            see what was done to it.
          </p>
          <div className="ws-table-wrap" role="region" aria-label="Managed resources" tabIndex={0}>
            <table className="ws-table">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>State</th>
                  <th>Last change</th>
                  <th>Order</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(row => (
                  <Fragment key={row.id}>
                    <tr>
                      <td title={row.id}>
                        <button
                          type="button"
                          className="ws-row-toggle"
                          aria-expanded={Boolean(opened[row.id])}
                          onClick={() => toggle(row.id)}
                        >
                          <span aria-hidden="true">{opened[row.id] ? '▾' : '▸'}</span>
                          {row.name}
                        </button>
                        {/* Under the name, so the table still fits the narrow column */}
                        <span className="ws-row-where">
                          {[shortType(row.type), row.resource_group].filter(Boolean).join(' · ')}
                        </span>
                      </td>
                      <td>
                        <span className={`ws-state ws-state-${classToken(row.state)}`}>
                          {row.state}
                        </span>
                        {row.disabled_by_us && (
                          <span className="ws-flag">stopped by this tool</span>
                        )}
                        {row.skip && <span className="ws-flag">tagged to skip</span>}
                        {row.error && <span className="ws-flag ws-flag-error">{row.error}</span>}
                      </td>
                      <td>
                        <LastChangeCell change={row.last_change} />
                      </td>
                      <td>{row.order}</td>
                    </tr>
                    {opened[row.id] && (
                      <tr className="ws-detail-row">
                        <td colSpan={COLUMNS}>
                          {/* Keyed by the last change, so a finished run reloads it */}
                          <ResourceHistory
                            key={row.last_change?.at ?? 'never'}
                            resourceId={row.id}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {picking && <ResourcePicker onClose={closePicker} />}
    </div>
  )
}

function LastChangeCell({ change }: { change: LastChange | null }) {
  if (change === null) return <>—</>
  const failed = change.outcome !== 'succeeded'
  return (
    <span title={change.detail}>
      <span className={failed ? 'ws-outcome ws-outcome-failed' : 'ws-change'}>
        {changeText(change)}
      </span>{' '}
      <span className="ws-change-when">{formatWhen(change.at)}</span>
    </span>
  )
}
