import { describe, expect, it } from 'vitest'
import type { FoundResource, SelectedRow } from '../../api/weekendSaver'
import { changeText } from './format'
import {
  countIn,
  fromSaved,
  holdsText,
  isClearing,
  listed,
  parseOrder,
  reorder,
  startFrom,
  tick,
  toPick,
  toSave,
  untick,
  visibleResources,
  withOrder,
  withPick,
  without,
} from './pickerState'

const SUB = '00000000-0000-0000-0000-000000000001'
const OTHER_SUB = '00000000-0000-0000-0000-000000000002'

const idOf = (name: string, group = 'rg-app', subscription = SUB) =>
  `/subscriptions/${subscription}/resourceGroups/${group}/providers/Microsoft.Compute/virtualMachines/${name}`

const saved = (name: string, order = 0, group = 'rg-app', subscription = SUB): SelectedRow => ({
  id: idOf(name, group, subscription),
  name,
  order,
  type: 'microsoft.compute/virtualmachines',
  resource_group: group,
  subscription_id: subscription,
})

const found = (name: string, overrides: Partial<FoundResource> = {}): FoundResource => ({
  resource_id: idOf(name),
  name,
  resource_type: 'microsoft.compute/virtualmachines',
  resource_group: 'rg-app',
  subscription_id: SUB,
  location: 'westeurope',
  supported: true,
  ...overrides,
})

describe('the selection', () => {
  it('starts as what was saved, whatever the case of an id', () => {
    const selection = fromSaved([saved('App', 10)])

    expect(Object.keys(selection)).toEqual([idOf('App').toLowerCase()])
    expect(selection[idOf('App').toLowerCase()].order).toBe('10')
  })

  it('keeps a saved resource whose group was never opened', () => {
    const selection = withPick(
      fromSaved([saved('app'), saved('db', 10, 'rg-data')]),
      toPick(found('web')),
    )

    expect(toSave(selection)).toEqual([
      { id: idOf('app'), order: 0 },
      { id: idOf('db', 'rg-data'), order: 10 },
      { id: idOf('web'), order: 0 },
    ])
  })

  it('adds and removes without changing the selection it was given', () => {
    const before = fromSaved([saved('app')])

    const added = withPick(before, toPick(found('web')))
    const removed = without(added, idOf('APP'))

    expect(Object.keys(before)).toHaveLength(1)
    expect(toSave(removed)).toEqual([{ id: idOf('web'), order: 0 }])
  })

  it('does not add the same resource twice', () => {
    const selection = withPick(fromSaved([saved('app', 5)]), toPick(found('APP')))

    expect(toSave(selection)).toEqual([{ id: idOf('app'), order: 5 }])
  })

  it('keeps an order as typed until it is saved', () => {
    const selection = withOrder(fromSaved([saved('app')]), idOf('app'), '-')

    expect(selection[idOf('app').toLowerCase()].order).toBe('-')
    expect(toSave(selection)).toEqual([{ id: idOf('app'), order: 0 }])
  })

  it('ignores an order for something that is not selected', () => {
    const selection = fromSaved([saved('app')])

    expect(withOrder(selection, idOf('web'), '3')).toEqual(selection)
  })

  it.each([
    ['7', 7],
    ['2.6', 3],
    ['', 0],
    ['abc', 0],
    ['5000', 1000],
    ['-5000', -1000],
  ])('reads the order %j as %i', (text, order) => {
    expect(parseOrder(text)).toBe(order)
  })

  it('knows when saving would stop managing everything', () => {
    expect(isClearing([saved('app')], {})).toBe(true)
    expect(isClearing([saved('app')], fromSaved([saved('app')]))).toBe(false)
    expect(isClearing([], {})).toBe(false)
  })
})

describe('ticking and unticking while the dialog is open', () => {
  const app = idOf('app')

  it('gives a resource its saved order back when it is ticked again in the tree', () => {
    const unticked = untick(startFrom([saved('app', 10)]), app)

    const again = tick(unticked, toPick(found('app')))

    expect(toSave(unticked.selection)).toEqual([])
    expect(toSave(again.selection)).toEqual([{ id: app, order: 10 }])
  })

  it('keeps an order that was changed before the resource was unticked', () => {
    const changed = reorder(startFrom([saved('app', 10)]), app, '25')

    const again = tick(untick(changed, app), toPick(found('app')))

    expect(toSave(again.selection)).toEqual([{ id: app, order: 25 }])
  })

  it('keeps listing what was unticked, so a slip can be undone', () => {
    const state = untick(tick(startFrom([saved('app')]), toPick(found('web'))), idOf('web'))

    expect(listed(state).map(pick => pick.name)).toEqual(['app', 'web'])
    expect(toSave(state.selection)).toEqual([{ id: app, order: 0 }])
  })

  it('leaves the state it was given as it was', () => {
    const before = startFrom([saved('app', 10)])

    untick(reorder(before, app, '3'), app)

    expect(toSave(before.selection)).toEqual([{ id: app, order: 10 }])
    expect(listed(before)).toHaveLength(1)
  })

  it('unticking something that is not ticked changes nothing', () => {
    const before = startFrom([saved('app')])

    expect(untick(before, idOf('web'))).toBe(before)
  })
})

describe('what a level holds', () => {
  const selection = fromSaved([
    saved('app'),
    saved('db', 0, 'RG-Data'),
    saved('far', 0, 'rg-app', OTHER_SUB),
  ])

  it('counts the selection inside a subscription', () => {
    expect(countIn(selection, SUB)).toBe(2)
    expect(countIn(selection, OTHER_SUB.toUpperCase())).toBe(1)
  })

  it('counts the selection inside one group, whatever the case of its name', () => {
    expect(countIn(selection, SUB, 'rg-data')).toBe(1)
    expect(countIn(selection, SUB, 'rg-none')).toBe(0)
  })

  it.each([
    [{ total: 0, supported: 0 }, 'empty'],
    [{ total: 3, supported: 3 }, '3 can be managed'],
    [{ total: 5, supported: 2 }, '2 can be managed · 3 other'],
    [{ total: 4, supported: 0 }, '4 other'],
  ])('describes %j as %j', (summary, text) => {
    expect(holdsText(summary)).toBe(text)
  })
})

describe('the resources shown in an open group', () => {
  const rows = [
    found('shop-web'),
    found('shop-db', { resource_type: 'microsoft.dbforpostgresql/flexibleservers' }),
    found('shop-kv', { resource_type: 'microsoft.keyvault/vaults', supported: false }),
  ]

  it('leaves out what cannot be stopped unless asked for', () => {
    expect(visibleResources(rows, '', false).map(row => row.name)).toEqual(['shop-web', 'shop-db'])
    expect(visibleResources(rows, '', true)).toHaveLength(3)
  })

  it('filters by name or type, ignoring case and spaces around', () => {
    expect(visibleResources(rows, '  WEB ', true).map(row => row.name)).toEqual(['shop-web'])
    expect(visibleResources(rows, 'postgres', true).map(row => row.name)).toEqual(['shop-db'])
    expect(visibleResources(rows, 'nothing', true)).toEqual([])
  })
})

describe('what the workflow last did', () => {
  it.each([
    ['disable', 'succeeded', 'Disabled'],
    ['enable', 'succeeded', 'Enabled'],
    ['disable', 'failed', 'Disable failed'],
    ['enable', 'failed', 'Enable failed'],
  ])('words %s %s as %j', (action, outcome, text) => {
    expect(changeText({ action, outcome })).toBe(text)
  })
})
