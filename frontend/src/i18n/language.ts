// Which language the interface uses. English unless the person chose otherwise.

export type Language = 'en' | 'ja'

export const DEFAULT_LANGUAGE: Language = 'en'
export const LANGUAGE_STORAGE_KEY = 'language'

const SUPPORTED: readonly Language[] = ['en', 'ja']

/** The saved choice if it is one we support, else the default. */
export function pickLanguage(saved: string | null | undefined): Language {
  return SUPPORTED.includes(saved as Language) ? (saved as Language) : DEFAULT_LANGUAGE
}

export const otherLanguage = (language: Language): Language => (language === 'en' ? 'ja' : 'en')
