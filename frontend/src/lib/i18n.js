/**
 * EVA UI localisation
 * ===================
 * Built on the language the user has ALREADY chosen in Settings → General.
 * There is no second language picker and no second storage key: this reads
 * getSelectedLanguageCode() from lib/languages.js, the same value that decides
 * what language EVA answers in.
 *
 * Deliberately dependency-free. react-i18next and friends bring a loader, a
 * plugin system, interpolation and pluralisation rules; EVA needs a lookup with
 * a fallback for a fixed set of seven languages, and adding ~40KB plus a
 * provider tree to get that would cost more than it returns.
 *
 * SCOPE — the user-facing chrome only: sidebar, top bar, composer, message
 * actions, follow-up chips, settings section names. The ~42 admin/engineering
 * pages stay English on purpose. They are internal tooling, they carry hundreds
 * of dense technical strings, and machine-translating "rerank score" or
 * "embedding drift" produces something worse than English for the one person
 * who reads them.
 *
 * Any key missing from a locale falls back to English rather than rendering a
 * blank or the raw key, so a partial translation degrades to English instead of
 * breaking the interface.
 */

import { getSelectedLanguageCode } from './languages';

const en = {
  // Sidebar
  'nav.newChat': 'New Chat',
  'nav.history': 'History',
  'nav.profile': 'Profile',
  'nav.settings': 'Settings',
  'nav.chat': 'Chat',

  // Status
  'status.aiOnline': 'AI Online',
  'status.aiDegraded': 'AI Degraded',
  'status.aiOffline': 'AI Offline',
  'status.backendOnline': 'Backend Online',
  'status.backendOffline': 'Backend Offline',

  // Composer
  'composer.placeholder': 'Ask, upload a file, generate code, create an image...',
  'composer.send': 'Send',
  'composer.stop': 'Stop',

  // Message actions
  'action.readAloud': 'Read aloud',
  'action.copy': 'Copy',
  'action.regenerate': 'Regenerate',
  'action.share': 'Share',
  'action.export': 'Export',
  'action.pin': 'Pin',
  'action.unpin': 'Unpin',
  'action.goodResponse': 'Good response',
  'action.badResponse': 'Bad response',
  'action.saved': 'Saved',

  // Follow-ups
  'suggestions.title': 'Suggested follow-ups',

  // Settings section names
  'settings.profile': 'Profile',
  'settings.general': 'General',
  'settings.appearance': 'Appearance',
  'settings.voice': 'Voice',
  'settings.chats': 'Chats',
  'settings.memory': 'Memory',
  'settings.language': 'Language',

  // Chat states
  'chat.thinking': 'Thinking…',
  'chat.emptyTitle': 'How can I help you today?',
};

const mr = {
  'nav.newChat': 'नवीन संभाषण',
  'nav.history': 'इतिहास',
  'nav.profile': 'प्रोफाइल',
  'nav.settings': 'सेटिंग्ज',
  'nav.chat': 'संभाषण',
  'status.aiOnline': 'AI ऑनलाइन',
  'status.aiDegraded': 'AI मर्यादित',
  'status.aiOffline': 'AI ऑफलाइन',
  'status.backendOnline': 'बॅकएंड ऑनलाइन',
  'status.backendOffline': 'बॅकएंड ऑफलाइन',
  'composer.placeholder': 'विचारा, फाइल अपलोड करा, कोड तयार करा, प्रतिमा तयार करा...',
  'composer.send': 'पाठवा',
  'composer.stop': 'थांबा',
  'action.readAloud': 'मोठ्याने वाचा',
  'action.copy': 'कॉपी करा',
  'action.regenerate': 'पुन्हा तयार करा',
  'action.share': 'शेअर करा',
  'action.export': 'निर्यात करा',
  'action.pin': 'पिन करा',
  'action.unpin': 'पिन काढा',
  'action.goodResponse': 'चांगले उत्तर',
  'action.badResponse': 'वाईट उत्तर',
  'action.saved': 'जतन केले',
  'suggestions.title': 'सुचवलेले पुढील प्रश्न',
  'settings.profile': 'प्रोफाइल',
  'settings.general': 'सामान्य',
  'settings.appearance': 'स्वरूप',
  'settings.voice': 'आवाज',
  'settings.chats': 'संभाषणे',
  'settings.memory': 'स्मृती',
  'settings.language': 'भाषा',
  'chat.thinking': 'विचार करत आहे…',
  'chat.emptyTitle': 'मी आज तुमची कशी मदत करू?',
};

const hi = {
  'nav.newChat': 'नई चैट',
  'nav.history': 'इतिहास',
  'nav.profile': 'प्रोफ़ाइल',
  'nav.settings': 'सेटिंग्स',
  'nav.chat': 'चैट',
  'status.aiOnline': 'AI ऑनलाइन',
  'status.aiDegraded': 'AI सीमित',
  'status.aiOffline': 'AI ऑफ़लाइन',
  'status.backendOnline': 'बैकएंड ऑनलाइन',
  'status.backendOffline': 'बैकएंड ऑफ़लाइन',
  'composer.placeholder': 'पूछें, फ़ाइल अपलोड करें, कोड बनाएँ, छवि बनाएँ...',
  'composer.send': 'भेजें',
  'composer.stop': 'रोकें',
  'action.readAloud': 'ज़ोर से पढ़ें',
  'action.copy': 'कॉपी करें',
  'action.regenerate': 'फिर से बनाएँ',
  'action.share': 'साझा करें',
  'action.export': 'निर्यात करें',
  'action.pin': 'पिन करें',
  'action.unpin': 'पिन हटाएँ',
  'action.goodResponse': 'अच्छा उत्तर',
  'action.badResponse': 'ख़राब उत्तर',
  'action.saved': 'सहेजा गया',
  'suggestions.title': 'सुझाए गए अगले प्रश्न',
  'settings.profile': 'प्रोफ़ाइल',
  'settings.general': 'सामान्य',
  'settings.appearance': 'रूप',
  'settings.voice': 'आवाज़',
  'settings.chats': 'चैट',
  'settings.memory': 'स्मृति',
  'settings.language': 'भाषा',
  'chat.thinking': 'सोच रहा हूँ…',
  'chat.emptyTitle': 'आज मैं आपकी कैसे मदद करूँ?',
};

const de = {
  'nav.newChat': 'Neuer Chat',
  'nav.history': 'Verlauf',
  'nav.profile': 'Profil',
  'nav.settings': 'Einstellungen',
  'nav.chat': 'Chat',
  'status.aiOnline': 'KI online',
  'status.aiDegraded': 'KI eingeschränkt',
  'status.aiOffline': 'KI offline',
  'status.backendOnline': 'Backend online',
  'status.backendOffline': 'Backend offline',
  'composer.placeholder': 'Fragen, Datei hochladen, Code erzeugen, Bild erstellen...',
  'composer.send': 'Senden',
  'composer.stop': 'Stopp',
  'action.readAloud': 'Vorlesen',
  'action.copy': 'Kopieren',
  'action.regenerate': 'Neu generieren',
  'action.share': 'Teilen',
  'action.export': 'Exportieren',
  'action.pin': 'Anheften',
  'action.unpin': 'Lösen',
  'action.goodResponse': 'Gute Antwort',
  'action.badResponse': 'Schlechte Antwort',
  'action.saved': 'Gespeichert',
  'suggestions.title': 'Vorgeschlagene Folgefragen',
  'settings.profile': 'Profil',
  'settings.general': 'Allgemein',
  'settings.appearance': 'Darstellung',
  'settings.voice': 'Stimme',
  'settings.chats': 'Chats',
  'settings.memory': 'Gedächtnis',
  'settings.language': 'Sprache',
  'chat.thinking': 'Denkt nach…',
  'chat.emptyTitle': 'Wie kann ich Ihnen heute helfen?',
};

const es = {
  'nav.newChat': 'Nuevo chat',
  'nav.history': 'Historial',
  'nav.profile': 'Perfil',
  'nav.settings': 'Ajustes',
  'nav.chat': 'Chat',
  'status.aiOnline': 'IA en línea',
  'status.aiDegraded': 'IA degradada',
  'status.aiOffline': 'IA sin conexión',
  'status.backendOnline': 'Backend en línea',
  'status.backendOffline': 'Backend sin conexión',
  'composer.placeholder': 'Pregunta, sube un archivo, genera código, crea una imagen...',
  'composer.send': 'Enviar',
  'composer.stop': 'Detener',
  'action.readAloud': 'Leer en voz alta',
  'action.copy': 'Copiar',
  'action.regenerate': 'Regenerar',
  'action.share': 'Compartir',
  'action.export': 'Exportar',
  'action.pin': 'Fijar',
  'action.unpin': 'Dejar de fijar',
  'action.goodResponse': 'Buena respuesta',
  'action.badResponse': 'Mala respuesta',
  'action.saved': 'Guardado',
  'suggestions.title': 'Preguntas sugeridas',
  'settings.profile': 'Perfil',
  'settings.general': 'General',
  'settings.appearance': 'Apariencia',
  'settings.voice': 'Voz',
  'settings.chats': 'Chats',
  'settings.memory': 'Memoria',
  'settings.language': 'Idioma',
  'chat.thinking': 'Pensando…',
  'chat.emptyTitle': '¿Cómo puedo ayudarte hoy?',
};

const ja = {
  'nav.newChat': '新しいチャット',
  'nav.history': '履歴',
  'nav.profile': 'プロフィール',
  'nav.settings': '設定',
  'nav.chat': 'チャット',
  'status.aiOnline': 'AI オンライン',
  'status.aiDegraded': 'AI 制限あり',
  'status.aiOffline': 'AI オフライン',
  'status.backendOnline': 'バックエンド オンライン',
  'status.backendOffline': 'バックエンド オフライン',
  'composer.placeholder': '質問する、ファイルをアップロード、コードを生成、画像を作成...',
  'composer.send': '送信',
  'composer.stop': '停止',
  'action.readAloud': '読み上げ',
  'action.copy': 'コピー',
  'action.regenerate': '再生成',
  'action.share': '共有',
  'action.export': 'エクスポート',
  'action.pin': 'ピン留め',
  'action.unpin': 'ピン留めを解除',
  'action.goodResponse': '良い回答',
  'action.badResponse': '悪い回答',
  'action.saved': '保存しました',
  'suggestions.title': 'おすすめの次の質問',
  'settings.profile': 'プロフィール',
  'settings.general': '一般',
  'settings.appearance': '外観',
  'settings.voice': '音声',
  'settings.chats': 'チャット',
  'settings.memory': 'メモリ',
  'settings.language': '言語',
  'chat.thinking': '考えています…',
  'chat.emptyTitle': '今日はどのようなご用件でしょうか？',
};

const it = {
  'nav.newChat': 'Nuova chat',
  'nav.history': 'Cronologia',
  'nav.profile': 'Profilo',
  'nav.settings': 'Impostazioni',
  'nav.chat': 'Chat',
  'status.aiOnline': 'IA online',
  'status.aiDegraded': 'IA degradata',
  'status.aiOffline': 'IA offline',
  'status.backendOnline': 'Backend online',
  'status.backendOffline': 'Backend offline',
  'composer.placeholder': 'Chiedi, carica un file, genera codice, crea un\'immagine...',
  'composer.send': 'Invia',
  'composer.stop': 'Ferma',
  'action.readAloud': 'Leggi ad alta voce',
  'action.copy': 'Copia',
  'action.regenerate': 'Rigenera',
  'action.share': 'Condividi',
  'action.export': 'Esporta',
  'action.pin': 'Fissa',
  'action.unpin': 'Rimuovi',
  'action.goodResponse': 'Buona risposta',
  'action.badResponse': 'Risposta scadente',
  'action.saved': 'Salvato',
  'suggestions.title': 'Domande suggerite',
  'settings.profile': 'Profilo',
  'settings.general': 'Generale',
  'settings.appearance': 'Aspetto',
  'settings.voice': 'Voce',
  'settings.chats': 'Chat',
  'settings.memory': 'Memoria',
  'settings.language': 'Lingua',
  'chat.thinking': 'Sto pensando…',
  'chat.emptyTitle': 'Come posso aiutarti oggi?',
};

export const TRANSLATIONS = { en, mr, hi, de, es, ja, it };

/** Fired when the language changes, so open views re-render without a reload. */
export const LANGUAGE_CHANGED_EVENT = 'eva:language-changed';

export function notifyLanguageChanged(code) {
  try {
    window.dispatchEvent(new CustomEvent(LANGUAGE_CHANGED_EVENT, { detail: { code } }));
  } catch { /* SSR / very old browsers */ }
}

/**
 * Translate one key. Falls back to English, then to the key itself, so a
 * missing string is never rendered as an empty element.
 */
export function translate(key, code = getSelectedLanguageCode()) {
  const table = TRANSLATIONS[code] || TRANSLATIONS.en;
  return table[key] ?? TRANSLATIONS.en[key] ?? key;
}

export default translate;
