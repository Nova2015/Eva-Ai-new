// On-demand information provenance.
//
// EVA never shows where information came from by default — no source chips, no
// confidence badges, no RAG audit panel in normal Chat. Provenance is revealed
// only when the user explicitly asks for it, and then it describes the answer
// they are asking about: the previous one.
//
// Detection is deliberately narrow. A false positive is worse than a miss here:
// it swallows a real question and answers it with a metadata dump instead. So
// "what is the source of the Nile" and "show me the source code" must not fire,
// while "what are your sources" and "where did that come from" must.

// Asking about the answer, not about the world.
const REQUEST_PATTERNS = [
  // "what are your sources", "which sources did you use"
  /\b(what|which)\s+(are\s+|were\s+)?(your\s+|the\s+)?sources?\b/i,
  // "cite your sources", "list your sources"
  /\b(cite|list|name)\s+(your\s+|the\s+)?sources?\b/i,
  // "show sources" / "show me the sources" — but never "source code"
  /\bshow\s+(me\s+)?(the\s+)?sources?\b(?!\s*code)/i,
  // "where did this come from", "where did you get that"
  /\bwhere\s+(did|does)\s+(this|that|it|you)\b[^?]*\b(come\s+from|get|find)\b/i,
  // "how do you know that"
  /\bhow\s+do\s+you\s+know\s+(this|that)\b/i,
  // "what is this based on", "what was that based on"
  /\bbased\s+on\s+what\b/i,
  /\b(what|which)\s+.{0,20}\bbased\s+on\b/i,
  // "any sources for that", "source for that", "sources of that answer".
  // Both prepositions: the exclusion below lets "sources of this/that"
  // through precisely because it refers to the answer, so a positive pattern
  // has to exist to catch it or it falls through as an ordinary turn.
  /\bsources?\s+(of|for)\s+(this|that|it|your)\b/i,
  // Marathi / Hindi
  /कुठून/,
  /कहाँ\s*से/,
  /स्रोत|स्त्रोत/,
  /संदर्भ\s*(काय|क्या)/,
];

// Phrases that contain a trigger word but are asking about the world, or about
// something other than this answer's provenance.
const NOT_A_REQUEST = [
  /\bsource\s+code\b/i,
  /\bopen\s+source\b/i,
  // "sources of <something>" asks about the world; "sources of this/that" asks
  // about the last answer. A noun list was the first attempt and it named the
  // singular only, so "what is the source of the Nile" was excluded while
  // "what are the sources of the Nile" fired — the false positive that matters
  // most, since firing swallows a real question and answers it with metadata.
  /\bsources?\s+of\s+(?!(this|that|it|your|the\s+answer)\b)/i,
  /\bdata\s+sources?\s+(config|connection|driver|name)\b/i,
];

export function isProvenanceRequest(text) {
  const s = String(text || '').trim();
  if (!s) return false;
  // A long message that happens to mention sources is a task, not a question
  // about the last answer.
  if (s.length > 160) return false;
  if (NOT_A_REQUEST.some((re) => re.test(s))) return false;
  return REQUEST_PATTERNS.some((re) => re.test(s));
}

function pct(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return Math.round(n * 100);
}

// A plain-language answer to "where did that come from", built from the audit
// metadata the client already holds. No model call: this is a fact about the
// request, and asking a model to recall its own retrieval would invite it to
// invent one.
export function describeProvenance(meta) {
  const sources = Array.isArray(meta?.sourceIds) ? meta.sourceIds.filter(Boolean) : [];
  const retrievers = Array.isArray(meta?.retrieversUsed)
    ? meta.retrieversUsed.filter(Boolean)
    : [];
  const searched = retrievers.length > 0 || Number(meta?.retrievedCount) > 0;

  if (!sources.length) {
    // Three cases, not two. `sources` is the GROUNDED subset — the documents
    // the answer actually cited — so an empty list means "nothing was cited",
    // which is not the same as "nothing was searched".
    //
    // Live, an answer that named three documents in prose reported sources: []
    // because it wrote "Applied Metal Forming: ..." instead of [Source N], and
    // grounding keys on the marker. Collapsing both cases into one sentence
    // made EVA tell the user it had answered from general knowledge seconds
    // after it had quoted their files.
    if (searched) {
      return 'That answer came from a search of your documents, but it did not '
        + 'cite a specific one, so there is no single source to point you at.';
    }
    return "That answer wasn't drawn from any of your documents — it came from "
      + 'general knowledge, so there are no sources to cite.';
  }

  const shown = sources.slice(0, 6);
  const rest = sources.length - shown.length;
  const list = shown.length === 1
    ? shown[0]
    : `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}`;

  let out = sources.length === 1
    ? `That answer used one source: ${list}.`
    : `That answer used ${sources.length} sources: ${list}${rest > 0 ? `, and ${rest} more` : ''}.`;

  const confidence = pct(meta?.confidence);
  if (confidence !== null) out += ` Retrieval confidence was ${confidence}%.`;

  return out;
}

// The message whose provenance an "explicit ask" refers to: the most recent
// assistant answer, not the whole conversation.
export function lastAnsweredMessage(messages) {
  if (!Array.isArray(messages)) return null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (!m || m.streaming) continue;
    const role = m.role || m.type;
    const isAssistant = role === 'assistant' || role === 'bot' || m.bot === true;
    if (isAssistant && (m.text || m.content)) return m;
  }
  return null;
}
