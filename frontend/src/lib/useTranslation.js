import { useCallback, useEffect, useState } from 'react';
import { getSelectedLanguageCode } from './languages';
import { translate, LANGUAGE_CHANGED_EVENT } from './i18n';

/**
 * useTranslation() -> { t, lang }
 *
 * Subscribes to language changes so an open view re-renders immediately when
 * the setting changes, rather than waiting for a reload.
 *
 * Two listeners, not one:
 *  - the custom event covers a change made in THIS tab, because localStorage
 *    does not fire `storage` to the tab that wrote it;
 *  - the storage event covers a change made in ANOTHER tab.
 * With only the custom event, a second open tab keeps the old language until
 * refreshed.
 */
export default function useTranslation() {
  const [lang, setLang] = useState(getSelectedLanguageCode);

  useEffect(() => {
    const sync = () => setLang(getSelectedLanguageCode());
    window.addEventListener(LANGUAGE_CHANGED_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(LANGUAGE_CHANGED_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const t = useCallback((key) => translate(key, lang), [lang]);
  return { t, lang };
}
