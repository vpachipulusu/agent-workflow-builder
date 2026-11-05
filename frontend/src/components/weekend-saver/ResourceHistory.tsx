import { useEffect, useState } from 'react'

import { getActivity, messageOf, type Change } from '../../api/weekendSaver'
import { changeText, formatWhen } from './format'
import { Loaded, type Lazy } from './lazy'

const HISTORY_LIMIT = 10

/** What the workflow did to one resource, newest first; loaded when the row is opened. */
export default function ResourceHistory({ resourceId }: { resourceId: string }) {
  const [changes, setChanges] = useState<Lazy<Change[]>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setChanges({ status: 'loading' })
    getActivity(resourceId, HISTORY_LIMIT).then(
      data => !cancelled && setChanges({ status: 'ready', data }),
      error => !cancelled && setChanges({ status: 'failed', error: messageOf(error) }),
    )
    return () => {
      cancelled = true
    }
  }, [resourceId, attempt])

  return (
    <Loaded
      entry={changes}
      what="what Weekend Saver did here"
      onRetry={() => setAttempt(n => n + 1)}
    >
      {found =>
        found.length === 0 ? (
          <p className="ws-hint">Weekend Saver has not changed this resource yet.</p>
        ) : (
          <ul className="ws-history">
            {found.map((change, index) => (
              <li
                key={`${change.at}-${index}`}
                className={change.outcome === 'failed' ? 'ws-history-failed' : ''}
              >
                <span className="ws-history-when">{formatWhen(change.at)}</span>
                <span className="ws-history-what">{changeText(change)}</span>
                <span className="ws-history-status">{change.detail}</span>
              </li>
            ))}
          </ul>
        )
      }
    </Loaded>
  )
}
