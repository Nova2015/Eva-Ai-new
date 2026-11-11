/**
 * Response languages.
 *
 * One source of truth for the label shown in Settings and the ISO code sent to
 * the backend. They were going to be written in two places — the Select options
 * and whatever maps them for the request — and a mismatch there fails silently:
 * the user picks a language and simply keeps getting English.
 *
 * This is display + mapping only. It is NOT UI localisation: EVA has no i18n
 * system and this update deliberately does not add one, so the interface stays
 * English and only EVA's replies change language.
 */

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'mr', label: 'मराठी — Marathi' },
  { code: 'hi', label: 'हिन्दी — Hindi' },
  { code: 'de', label: 'Deutsch — German' },
  { code: 'es', label: 'Español — Spanish' },
  { code: 'ja', label: '日本語 — Japanese' },
  { code: 'it', label: 'Italiano — Italian' },
];

// Kept as a selectable option because it is the value already stored for
// existing users. It resolves to English, which is what it has always
// effectively done — dropping it would silently change their language.
export const AUTO_DETECT = 'Auto detect';

export const LANGUAGE_OPTIONS = [AUTO_DETECT, ...LANGUAGES.map((l) => l.label)];

export const DEFAULT_LANGUAGE_CODE = 'en';

/**
 * Settings label -> ISO code. Tolerates the older short labels
 * ("Marathi", "Hindi") that are already saved in some browsers from the
 * previous three-option list, so upgrading does not reset anyone's choice.
 */
export function languageCodeFromLabel(label) {
  const value = String(label || '').trim();
  if (!value || value === AUTO_DETECT) return DEFAULT_LANGUAGE_CODE;

  const exact = LANGUAGES.find((l) => l.label === value);
  if (exact) return exact.code;

  // Older saved values, and any label matched on its English name alone.
  const lower = value.toLowerCase();
  const byEnglishName = LANGUAGES.find((l) => {
    const english = l.label.includes('—') ? l.label.split('—')[1].trim() : l.label;
    return english.toLowerCase() === lower;
  });
  if (byEnglishName) return byEnglishName.code;

  const byCode = LANGUAGES.find((l) => l.code === lower);
  return byCode ? byCode.code : DEFAULT_LANGUAGE_CODE;
}

/** The saved response language, read from the existing general settings blob. */
export function getSelectedLanguageCode() {
  try {
    const general = JSON.parse(localStorage.getItem('eva_general_settings') || '{}');
    return languageCodeFromLabel(general.language);
  } catch {
    return DEFAULT_LANGUAGE_CODE;
  }
}
