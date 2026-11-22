import {
  isProvenanceRequest,
  describeProvenance,
  lastAnsweredMessage,
} from './provenance';

// The rule: EVA never shows where information came from by default, and
// reveals it only when explicitly asked.
//
// Most of this file is about the detector, and most of THAT is about what must
// not fire. A false positive is worse than a miss: it swallows a real question
// and answers it with a metadata dump instead of an answer.

describe('isProvenanceRequest — asks that must fire', () => {
  test.each([
    'what are your sources',
    'What are your sources?',
    'which sources did you use',
    'cite your sources',
    'list the sources',
    'show sources',
    'show me the sources',
    'where did this come from',
    'where did you get that',
    'where does this come from?',
    'how do you know that',
    'what is this based on',
    'based on what?',
    'any sources for that',
    'source for that?',
    // "sources of" still asks about the answer when what follows refers to it.
    'what are the sources of this',
    'sources of that answer?',
    'हे कुठून मिळालं',
    'याचा स्रोत काय',
    'यह कहाँ से आया',
  ])('fires on %j', (text) => {
    expect(isProvenanceRequest(text)).toBe(true);
  });
});

describe('isProvenanceRequest — questions about the world that must NOT fire', () => {
  test.each([
    'what is the source of the Nile',
    // The plural is the one that got through: an earlier version excluded only
    // "source of" and let "sources of" fire, hijacking a real question.
    'what are the sources of the Nile',
    'what are the sources of energy',
    'which are the sources of vitamin D',
    'what are the sources of open source software',
    'list the sources in the source code',
    'show me the source code',
    'what is open source software',
    'explain the source of income tax',
    'where is Paris',
    'what is the capital of France',
    'how do you know when bread is done',
    'summarize the report',
    'write a function that reads a data source config',
    '',
    '   ',
  ])('does not fire on %j', (text) => {
    expect(isProvenanceRequest(text)).toBe(false);
  });

  test('a long message that merely mentions sources is a task, not a question', () => {
    const essay = 'Please write a 500 word essay about renewable energy and '
      + 'make sure you list the sources at the end in APA format, including '
      + 'journal names, and keep the tone academic throughout the piece.';
    expect(essay.length).toBeGreaterThan(160);
    expect(isProvenanceRequest(essay)).toBe(false);
  });

  test('null and undefined are safe', () => {
    expect(isProvenanceRequest(null)).toBe(false);
    expect(isProvenanceRequest(undefined)).toBe(false);
  });
});

describe('describeProvenance', () => {
  test('says plainly when nothing was retrieved', () => {
    const out = describeProvenance({ sourceIds: [] });
    expect(out).toMatch(/general knowledge/);
    expect(out).not.toMatch(/undefined|NaN/);
  });

  // Update 31. `sources` is the GROUNDED subset, so an empty list means
  // "nothing was cited" — not "nothing was searched". Live, an answer that
  // named three of the user's documents in prose came back with sources: []
  // and retrievers_used: ["bm25"], and EVA told the user it had answered from
  // general knowledge seconds after quoting their files.
  test('does not claim general knowledge when retrieval actually ran', () => {
    const out = describeProvenance({ sourceIds: [], retrieversUsed: ['bm25'] });
    expect(out).not.toMatch(/general knowledge/);
    expect(out).toMatch(/search of your documents/);
  });

  test('retrieved documents that went uncited still count as a search', () => {
    const out = describeProvenance({ sourceIds: [], retrievedCount: 3 });
    expect(out).not.toMatch(/general knowledge/);
    expect(out).toMatch(/did not cite a specific one/);
  });

  test('general knowledge is still said when nothing searched at all', () => {
    for (const meta of [
      { sourceIds: [] },
      { sourceIds: [], retrieversUsed: [] },
      { sourceIds: [], retrievedCount: 0 },
    ]) {
      expect(describeProvenance(meta)).toMatch(/general knowledge/);
    }
  });

  test('cited sources still win over both', () => {
    const out = describeProvenance({ sourceIds: ['a.pdf'], retrieversUsed: ['bm25'] });
    expect(out).toContain('a.pdf');
    expect(out).not.toMatch(/general knowledge|search of your documents/);
  });

  test('a single source reads as one, not "1 sources"', () => {
    const out = describeProvenance({ sourceIds: ['handbook.pdf'] });
    expect(out).toContain('one source: handbook.pdf.');
    expect(out).not.toContain('1 sources');
  });

  test('lists several with an and', () => {
    const out = describeProvenance({ sourceIds: ['a.pdf', 'b.pdf', 'c.md'] });
    expect(out).toContain('3 sources');
    expect(out).toContain('a.pdf, b.pdf and c.md');
  });

  test('caps a long list and counts the remainder', () => {
    const ids = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
    const out = describeProvenance({ sourceIds: ids });
    expect(out).toContain('9 sources');
    expect(out).toContain('and 3 more');
    expect(out).not.toContain('9.');
  });

  test('confidence is reported as a percentage when present', () => {
    expect(describeProvenance({ sourceIds: ['x'], confidence: 0.87 }))
      .toContain('87%');
  });

  test('a zero or missing confidence is omitted rather than shown as 0%', () => {
    expect(describeProvenance({ sourceIds: ['x'] })).not.toContain('%');
    expect(describeProvenance({ sourceIds: ['x'], confidence: 0 })).not.toContain('%');
    expect(describeProvenance({ sourceIds: ['x'], confidence: null })).not.toContain('%');
  });

  test('junk metadata does not produce a broken sentence', () => {
    for (const meta of [null, undefined, {}, { sourceIds: null }, { sourceIds: 'x' }]) {
      const out = describeProvenance(meta);
      expect(typeof out).toBe('string');
      expect(out).not.toMatch(/undefined|NaN|\[object/);
    }
  });
});

describe('lastAnsweredMessage', () => {
  const user = { role: 'user', text: 'hi' };
  const bot = (text, extra = {}) => ({ role: 'assistant', text, ...extra });

  test('finds the most recent completed assistant message', () => {
    const msgs = [user, bot('first'), user, bot('second')];
    expect(lastAnsweredMessage(msgs).text).toBe('second');
  });

  test('skips a message still streaming', () => {
    const msgs = [bot('done'), user, bot('half', { streaming: true })];
    expect(lastAnsweredMessage(msgs).text).toBe('done');
  });

  test('ignores the user turn that asked the question', () => {
    const msgs = [bot('answer'), { role: 'user', text: 'what are your sources' }];
    expect(lastAnsweredMessage(msgs).text).toBe('answer');
  });

  test('returns null when there is nothing to describe', () => {
    expect(lastAnsweredMessage([])).toBeNull();
    expect(lastAnsweredMessage([user])).toBeNull();
    expect(lastAnsweredMessage(null)).toBeNull();
  });
});
