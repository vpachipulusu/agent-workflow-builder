import { describe, expect, it } from 'vitest'
import { DEFAULT_LANGUAGE, otherLanguage, pickLanguage } from './language'
import { MESSAGES } from './messages'

describe('pickLanguage', () => {
  it('uses English when nothing was chosen yet', () => {
    expect(DEFAULT_LANGUAGE).toBe('en')
    expect(pickLanguage(null)).toBe('en')
    expect(pickLanguage(undefined)).toBe('en')
  })

  it('keeps a saved choice', () => {
    expect(pickLanguage('ja')).toBe('ja')
    expect(pickLanguage('en')).toBe('en')
  })

  it('falls back to English for a value it does not know', () => {
    expect(pickLanguage('fr')).toBe('en')
    expect(pickLanguage('')).toBe('en')
    expect(pickLanguage('JA')).toBe('en')
  })
})

describe('otherLanguage', () => {
  it('switches between the two languages', () => {
    expect(otherLanguage('en')).toBe('ja')
    expect(otherLanguage('ja')).toBe('en')
  })
})

describe('messages', () => {
  const japanese = /[぀-ヿ一-鿿]/

  // Text produced by a function is checked with sample arguments
  const texts = (table: object): string[] =>
    Object.values(table).flatMap(value => {
      if (typeof value === 'string') return [value]
      if (typeof value === 'function') return [String(value('sample', true, 'detail'))]
      return texts(value)
    })

  it('has no Japanese left in the English text, apart from the language switch', () => {
    const { switchLanguage, ...nav } = MESSAGES.en.nav
    const english = texts({ ...MESSAGES.en, nav })

    expect(switchLanguage).toBe('日本語')
    expect(english.filter(text => japanese.test(text))).toEqual([])
  })

  it('offers the other language by its own name', () => {
    expect(MESSAGES.ja.nav.switchLanguage).toBe('English')
  })

  it('keeps the diagram rows as wide as the box around them', () => {
    const boxWidth = '│  ┌────────────┐  ┌───────────────────┐  │'.length

    expect(MESSAGES.en.home.diagramRow1).toHaveLength(boxWidth)
    expect(MESSAGES.en.home.diagramRow2).toHaveLength(boxWidth)
  })

  it('fills in names and outcomes', () => {
    expect(MESSAGES.en.agents.saved('helper', false)).toContain('Agent "helper" was created')
    expect(MESSAGES.en.workflows.saved('flow', true)).toContain('Workflow "flow" was updated')
    expect(MESSAGES.en.workflows.condition('urgent')).toBe(' (condition: urgent)')
    expect(MESSAGES.ja.agents.saved('helper', true)).toContain('更新')
  })
})
