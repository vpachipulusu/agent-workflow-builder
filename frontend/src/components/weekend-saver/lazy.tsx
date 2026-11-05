import { useEffect, useRef, useState, type ReactNode } from 'react'

import { messageOf } from '../../api/weekendSaver'

/** Something that is fetched only when it is first looked at. */
export type Lazy<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'failed'; error: string }

export const needsLoading = (entry: Lazy<unknown> | undefined) =>
  entry === undefined || entry.status === 'failed'

/** Nothing until `load` is called; then loading, and ready or failed. */
export function useLazy<T>(fetcher: () => Promise<T>) {
  const [entry, setEntry] = useState<Lazy<T> | undefined>(undefined)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = () => {
    const settle = (next: Lazy<T>) => {
      if (mounted.current) setEntry(next)
    }
    settle({ status: 'loading' })
    fetcher().then(
      data => settle({ status: 'ready', data }),
      error => settle({ status: 'failed', error: messageOf(error) }),
    )
  }

  return [entry, load] as const
}

interface LoadedProps<T> {
  entry: Lazy<T> | undefined
  // Completes "Loading …", for example "resource groups"
  what: string
  onRetry: () => void
  children: (data: T) => ReactNode
}

/** A spinner while it loads, the reason and a retry when it failed, else the content. */
export function Loaded<T>({ entry, what, onRetry, children }: LoadedProps<T>) {
  if (entry === undefined || entry.status === 'loading') {
    return (
      <p className="ws-loading" role="status">
        <span className="spinner" aria-hidden="true" />
        Loading {what}…
      </p>
    )
  }
  if (entry.status === 'failed') {
    return (
      <div className="ws-problem ws-banner" role="alert">
        {entry.error}
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      </div>
    )
  }
  return <>{children(entry.data)}</>
}
