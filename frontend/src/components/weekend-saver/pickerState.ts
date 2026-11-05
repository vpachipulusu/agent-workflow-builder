import type { FoundResource, SelectedRow } from '../../api/weekendSaver'

export const ORDER_LIMIT = 1000

/** One ticked resource. */
export interface Picked {
  id: string
  name: string
  type: string
  resource_group: string
  subscription_id: string
  // Kept as typed, so "-" and an empty box are possible on the way to a number
  order: string
}

/**
 * Everything that is ticked, keyed by lower-cased resource id.
 *
 * It starts as the saved list and changes only where the user ticks or unticks, so a
 * group that was never opened keeps its selection when the list is saved.
 */
export type Selection = Readonly<Record<string, Picked>>

const keyOf = (id: string) => id.toLowerCase()

export const isPicked = (selection: Selection, id: string) => keyOf(id) in selection

export const pickOf = (selection: Selection, id: string): Picked | undefined =>
  selection[keyOf(id)]

export const fromSaved = (rows: SelectedRow[]): Selection =>
  Object.fromEntries(rows.map(row => [keyOf(row.id), { ...row, order: String(row.order) }]))

export const toPick = (resource: FoundResource): Picked => ({
  id: resource.resource_id,
  name: resource.name,
  type: resource.resource_type,
  resource_group: resource.resource_group,
  subscription_id: resource.subscription_id,
  order: '0',
})

export const withPick = (selection: Selection, pick: Picked): Selection =>
  isPicked(selection, pick.id) ? selection : { ...selection, [keyOf(pick.id)]: pick }

export const without = (selection: Selection, id: string): Selection =>
  Object.fromEntries(Object.entries(selection).filter(([key]) => key !== keyOf(id)))

export const withOrder = (selection: Selection, id: string, order: string): Selection =>
  isPicked(selection, id)
    ? { ...selection, [keyOf(id)]: { ...selection[keyOf(id)], order } }
    : selection

/** What the open dialog knows: what is ticked, and what has been ticked in it before. */
export interface PickerState {
  selection: Selection
  // Unticking keeps the resource here, so ticking it again gives its order back
  remembered: Selection
}

export const startFrom = (rows: SelectedRow[]): PickerState => ({
  selection: fromSaved(rows),
  remembered: fromSaved(rows),
})

export function tick(state: PickerState, pick: Picked): PickerState {
  const known = pickOf(state.remembered, pick.id) ?? pick
  return {
    selection: withPick(state.selection, known),
    remembered: withPick(state.remembered, known),
  }
}

export const untick = (state: PickerState, id: string): PickerState =>
  isPicked(state.selection, id) ? { ...state, selection: without(state.selection, id) } : state

export const reorder = (state: PickerState, id: string, order: string): PickerState => ({
  selection: withOrder(state.selection, id, order),
  remembered: withOrder(state.remembered, id, order),
})

/** Everything ticked now or earlier in this dialog, ticked or not. */
export const listed = (state: PickerState): Picked[] =>
  Object.values({ ...state.remembered, ...state.selection })

export function parseOrder(text: string): number {
  const value = Math.round(Number(text))
  if (!Number.isFinite(value)) return 0
  return Math.max(-ORDER_LIMIT, Math.min(ORDER_LIMIT, value))
}

export const toSave = (selection: Selection): { id: string; order: number }[] =>
  Object.values(selection).map(pick => ({ id: pick.id, order: parseOrder(pick.order) }))

/** Saving now would leave nothing managed although something was. */
export const isClearing = (saved: SelectedRow[], selection: Selection): boolean =>
  saved.length > 0 && Object.keys(selection).length === 0

/** How many ticked resources sit in a subscription, or in one of its groups. */
export const countIn = (selection: Selection, subscriptionId: string, group?: string): number =>
  Object.values(selection).filter(
    pick =>
      pick.subscription_id.toLowerCase() === subscriptionId.toLowerCase() &&
      (group === undefined || pick.resource_group.toLowerCase() === group.toLowerCase()),
  ).length

/** What a subscription or group holds, in words. */
export function holdsText({ total, supported }: { total: number; supported: number }): string {
  if (total === 0) return 'empty'
  const other = total - supported
  const parts = [
    supported > 0 ? `${supported} can be managed` : '',
    other > 0 ? `${other} other` : '',
  ]
  return parts.filter(Boolean).join(' · ')
}

export function visibleResources(
  rows: FoundResource[],
  filter: string,
  showOther: boolean,
): FoundResource[] {
  const wanted = filter.trim().toLowerCase()
  return rows.filter(
    row =>
      (showOther || row.supported) &&
      (!wanted || [row.name, row.resource_type].some(text => text.toLowerCase().includes(wanted))),
  )
}
