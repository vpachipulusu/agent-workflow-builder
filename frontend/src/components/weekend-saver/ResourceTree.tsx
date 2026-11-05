import { useEffect, useState, type ReactNode } from 'react'

import {
  getGroupResources,
  getGroups,
  type FoundResource,
  type GroupSummary,
  type SubscriptionSummary,
} from '../../api/weekendSaver'
import { shortType } from './format'
import { Loaded, needsLoading, useLazy, type Lazy } from './lazy'
import {
  ORDER_LIMIT,
  countIn,
  holdsText,
  pickOf,
  visibleResources,
  type Selection,
} from './pickerState'

// A group can hold thousands of resources; more rows than this make the dialog sluggish
const MAX_ROWS_SHOWN = 300

/** What every level needs to show and change the selection. */
interface Choosing {
  selection: Selection
  filter: string
  showOther: boolean
  onToggle: (resource: FoundResource, checked: boolean) => void
  onOrder: (id: string, order: string) => void
}

interface Props extends Choosing {
  subscriptions: SubscriptionSummary[]
}

/** Subscriptions, their resource groups, their resources: each loaded when opened. */
export default function ResourceTree({ subscriptions, ...choosing }: Props) {
  if (subscriptions.length === 0) {
    return <p className="ws-hint ws-empty">Your sign-in cannot see any subscription.</p>
  }
  return (
    <ul className="ws-tree">
      {subscriptions.map(subscription => (
        <SubscriptionNode
          key={subscription.subscription_id}
          subscription={subscription}
          // With one subscription there is nothing to choose at the first level
          startOpen={subscriptions.length === 1}
          {...choosing}
        />
      ))}
    </ul>
  )
}

interface SubscriptionNodeProps extends Choosing {
  subscription: SubscriptionSummary
  startOpen: boolean
}

function SubscriptionNode({ subscription, startOpen, ...choosing }: SubscriptionNodeProps) {
  const id = subscription.subscription_id
  const [groups, load] = useLazy(() => getGroups(id))
  return (
    <TreeNode
      label={subscription.name}
      holds={holdsText(subscription)}
      picked={countIn(choosing.selection, id)}
      startOpen={startOpen}
      entry={groups}
      load={load}
      what="resource groups"
    >
      {found =>
        found.length === 0 ? (
          <p className="ws-hint">This subscription holds no resources.</p>
        ) : (
          <ul className="ws-tree">
            {found.map(group => (
              <GroupNode key={group.resource_group.toLowerCase()} group={group} {...choosing} />
            ))}
          </ul>
        )
      }
    </TreeNode>
  )
}

function GroupNode({ group, ...choosing }: Choosing & { group: GroupSummary }) {
  const [resources, load] = useLazy(() =>
    getGroupResources(group.subscription_id, group.resource_group),
  )
  return (
    <TreeNode
      label={group.resource_group}
      holds={holdsText(group)}
      picked={countIn(choosing.selection, group.subscription_id, group.resource_group)}
      startOpen={false}
      entry={resources}
      load={load}
      what="resources"
    >
      {rows => <GroupResources rows={rows} {...choosing} />}
    </TreeNode>
  )
}

interface TreeNodeProps<T> {
  label: string
  holds: string
  picked: number
  startOpen: boolean
  entry: Lazy<T> | undefined
  load: () => void
  what: string
  children: (data: T) => ReactNode
}

/** One row that opens and closes; what is under it is fetched the first time it opens. */
function TreeNode<T>(props: TreeNodeProps<T>) {
  const { label, holds, picked, startOpen, entry, load, what, children } = props
  const [open, setOpen] = useState(startOpen)

  useEffect(() => {
    if (startOpen) load()
    // Only when the node first appears; `load` is a new function on every render
  }, [])

  const toggle = () => {
    if (!open && needsLoading(entry)) load()
    setOpen(!open)
  }

  return (
    <li>
      <button type="button" className="ws-tree-row" aria-expanded={open} onClick={toggle}>
        <span className="ws-tree-chevron" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        <span className="ws-tree-name">{label}</span>
        <span className="ws-tree-holds">{holds}</span>
        {picked > 0 && <span className="ws-flag">{picked} selected</span>}
      </button>
      {/* Kept while closed, so opening it again does not load it again */}
      {entry !== undefined && (
        <div className="ws-tree-children" hidden={!open}>
          <Loaded entry={entry} what={what} onRetry={load}>
            {children}
          </Loaded>
        </div>
      )}
    </li>
  )
}

function GroupResources({ rows, ...choosing }: Choosing & { rows: FoundResource[] }) {
  const { selection, filter, showOther, onToggle, onOrder } = choosing
  const matching = visibleResources(rows, filter, showOther)
  const shown = matching.slice(0, MAX_ROWS_SHOWN)
  if (rows.length === 0) return <p className="ws-hint">This group is empty.</p>
  if (shown.length === 0) {
    return (
      <p className="ws-hint">
        {filter.trim()
          ? 'Nothing in this group matches the filter.'
          : 'Nothing in this group can be stopped and started. Tick “Show other types” to see what it holds.'}
      </p>
    )
  }
  return (
    <table className="ws-table">
      {matching.length > shown.length && (
        <caption className="ws-hint">
          Showing the first {shown.length} of {matching.length}. Filter by name or type to
          narrow it down.
        </caption>
      )}
      <thead>
        <tr>
          <th aria-label="Managed" />
          <th>Name</th>
          <th>Type</th>
          <th>Location</th>
          <th>Order</th>
        </tr>
      </thead>
      <tbody>
        {shown.map(row => (
          <ResourceRow
            key={row.resource_id}
            row={row}
            order={pickOf(selection, row.resource_id)?.order}
            onToggle={onToggle}
            onOrder={onOrder}
          />
        ))}
      </tbody>
    </table>
  )
}

interface ResourceRowProps {
  row: FoundResource
  // Undefined when the resource is not ticked
  order: string | undefined
  onToggle: Choosing['onToggle']
  onOrder: Choosing['onOrder']
}

function ResourceRow({ row, order, onToggle, onOrder }: ResourceRowProps) {
  return (
    <tr className={row.supported ? '' : 'ws-row-unsupported'}>
      <td>
        <input
          type="checkbox"
          aria-label={`Manage ${row.name}`}
          checked={order !== undefined}
          disabled={!row.supported}
          onChange={event => onToggle(row, event.target.checked)}
        />
      </td>
      <td title={row.resource_id}>{row.name}</td>
      <td>{shortType(row.resource_type) || '—'}</td>
      <td>{row.location || '—'}</td>
      <td>
        {row.supported ? (
          <input
            type="number"
            className="ws-order"
            aria-label={`Order of ${row.name}`}
            min={-ORDER_LIMIT}
            max={ORDER_LIMIT}
            step={1}
            value={order ?? '0'}
            disabled={order === undefined}
            onChange={event => onOrder(row.resource_id, event.target.value)}
          />
        ) : (
          <span className="ws-flag">not supported</span>
        )}
      </td>
    </tr>
  )
}
