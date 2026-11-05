import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { LANGUAGE_STORAGE_KEY, otherLanguage, pickLanguage, type Language } from './language'
import { MESSAGES, type Messages } from './messages'

interface I18n {
  language: Language
  /** The interface text in the current language. */
  t: Messages
  toggleLanguage: () => void
}

const I18nContext = createContext<I18n | null>(null)

function savedLanguage(): Language {
  try {
    return pickLanguage(localStorage.getItem(LANGUAGE_STORAGE_KEY))
  } catch {
    // Storage can be unavailable (private mode, blocked cookies); the default still works
    return pickLanguage(null)
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(savedLanguage)

  useEffect(() => {
    document.documentElement.lang = language
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
    } catch {
      // Not remembered across visits, but the switch itself still worked
    }
  }, [language])

  const toggleLanguage = useCallback(() => setLanguage(otherLanguage), [])
  const value = useMemo(
    () => ({ language, t: MESSAGES[language], toggleLanguage }),
    [language, toggleLanguage],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18n {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside a LanguageProvider')
  return value
}
