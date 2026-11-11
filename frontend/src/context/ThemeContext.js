import { createContext, useContext, useEffect, useMemo, useState } from 'react';

const THEME_KEY = 'eva_theme';
const ACCENT_KEY = 'eva_accent';
const LEGACY_APPEARANCE_KEY = 'eva_appearance_settings';

// Slice 2 — named palettes. 'dark' is kept as an alias of midnight so anyone
// with the old value saved in localStorage keeps a working theme instead of
// silently falling back.
export const THEME_PRESETS = [
  { id: 'midnight', label: 'EVA Midnight', scheme: 'dark', swatch: ['#090B14', '#7C5CFF', '#38BDF8'] },
  { id: 'aurora', label: 'Aurora', scheme: 'dark', swatch: ['#0A1020', '#22D3EE', '#A78BFA'] },
  { id: 'minimal', label: 'Minimal Dark', scheme: 'dark', swatch: ['#0D0D0F', '#E5E7EB', '#9CA3AF'] },
  { id: 'neon', label: 'Neon', scheme: 'dark', swatch: ['#07060F', '#FF2E97', '#00F0FF'] },
  { id: 'nature', label: 'Nature', scheme: 'dark', swatch: ['#0C1410', '#4ADE80', '#A3E635'] },
  { id: 'light', label: 'Light', scheme: 'light', swatch: ['#F8FAFC', '#2563EB', '#0EA5E9'] },
  { id: 'system', label: 'System', scheme: 'auto', swatch: ['#090B14', '#F8FAFC', '#7C5CFF'] },
];

const themes = new Set([...THEME_PRESETS.map((t) => t.id), 'dark']);
// 'auto' means "use the palette's own accent". It must be the default,
// otherwise data-accent='blue' overrides every palette's accent and all six
// themes render identically blue.
const accents = new Set(['auto', 'blue', 'purple', 'green', 'orange', 'pink']);

// Palettes that render dark, for resolving `system` and for any caller that
// only needs to know "is this light or dark".
const DARK_THEMES = new Set(['midnight', 'aurora', 'minimal', 'neon', 'nature', 'dark']);

export function themeScheme(themeId) {
  return DARK_THEMES.has(themeId) ? 'dark' : 'light';
}

const ThemeContext = createContext(null);

function normalizeTheme(value) {
  const next = String(value || '').trim().toLowerCase();
  // 'dark' was the previous default; map it onto the named palette so old
  // saved preferences land somewhere real.
  if (next === 'dark') return 'midnight';
  return themes.has(next) ? next : 'midnight';
}

function normalizeAccent(value) {
  const next = String(value || '').trim().toLowerCase();
  return accents.has(next) ? next : 'auto';
}

function readLegacyAppearance() {
  try {
    return JSON.parse(localStorage.getItem(LEGACY_APPEARANCE_KEY) || '{}');
  } catch {
    return {};
  }
}

function readInitialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved) return normalizeTheme(saved);
  return normalizeTheme(readLegacyAppearance().theme);
}

function readInitialAccent() {
  const saved = localStorage.getItem(ACCENT_KEY);
  if (saved) return normalizeAccent(saved);
  return normalizeAccent(readLegacyAppearance().accent_color);
}

function readInitialFontScale() {
  // Mirrors the scale mapping in AppearanceSettingsPanel.applyAppearance so the
  // saved "Font size" choice is restored on load and survives reloads.
  const size = readLegacyAppearance().font_size;
  return size === 'Large' ? '1.06' : size === 'Small' ? '0.94' : '1';
}

function getSystemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'midnight';
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readInitialTheme);
  const [accent, setAccentState] = useState(readInitialAccent);
  const [systemTheme, setSystemTheme] = useState(getSystemTheme);

  const resolvedTheme = theme === 'system' ? systemTheme : theme;

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: light)');
    if (!media) return undefined;

    const handleChange = () => setSystemTheme(getSystemTheme());
    media.addEventListener?.('change', handleChange);
    media.addListener?.(handleChange);

    return () => {
      media.removeEventListener?.('change', handleChange);
      media.removeListener?.(handleChange);
    };
  }, []);

  useEffect(() => {
    // Restore the saved UI font scale once on load so the Settings > Appearance
    // "Font size" control persists across reloads, like theme and accent do.
    document.documentElement.style.setProperty('--eva-font-scale', readInitialFontScale());
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    // data-palette carries the resolved palette so CSS can key off the real
    // theme even when the user picked 'system'; data-scheme lets anything that
    // only cares about light-vs-dark branch without knowing every palette.
    root.setAttribute('data-theme', theme);
    root.setAttribute('data-palette', resolvedTheme);
    root.setAttribute('data-scheme', themeScheme(resolvedTheme));
    root.setAttribute('data-accent', accent);
    root.setAttribute('data-effective-theme', resolvedTheme);
    localStorage.setItem(THEME_KEY, theme);
    localStorage.setItem(ACCENT_KEY, accent);
  }, [theme, accent, resolvedTheme]);

  const value = useMemo(() => ({
    theme,
    accent,
    resolvedTheme,
    scheme: themeScheme(resolvedTheme),
    presets: THEME_PRESETS,
    setTheme: (nextTheme) => setThemeState(normalizeTheme(nextTheme)),
    setAccent: (nextAccent) => setAccentState(normalizeAccent(nextAccent)),
  }), [theme, accent, resolvedTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}
