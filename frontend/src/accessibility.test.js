import fs from 'fs';
import path from 'path';

// Accessibility regressions are invisible in review: nothing looks broken, and
// the people affected are the least likely to be in the room to report it. So
// the ones that can be asserted from source are asserted here.

const read = (...p) => fs.readFileSync(path.join(__dirname, ...p), 'utf8');

describe('viewport allows zooming', () => {
  const html = read('..', 'public', 'index.html');
  const viewport = (html.match(/<meta\s+name="viewport"[^>]*>/) || [''])[0];

  test('the tag exists', () => {
    expect(viewport).toContain('width=device-width');
  });

  test('does not disable user scaling', () => {
    // user-scalable=no is honoured by iOS and simply refuses to zoom. Someone
    // who needs 200% text cannot read the page at all.
    expect(viewport).not.toMatch(/user-scalable\s*=\s*no/i);
  });

  test('does not cap the maximum scale', () => {
    // maximum-scale=1 has the same effect by another route.
    expect(viewport).not.toMatch(/maximum-scale\s*=\s*1\b/i);
  });
});

describe('contrast choices that were measured, not guessed', () => {
  const css = read('App.css');

  test('the skip link does not use the accent that failed', () => {
    // White on var(--accent) #7c5cff measures 4.35:1, under the 4.5 minimum.
    // This is the first control a keyboard user reaches.
    const rule = (css.match(/\.eva-skip-link\{[^}]*\}/) || [''])[0];
    expect(rule).toBeTruthy();
    expect(rule).toContain('background:#6d4ce0');
    expect(rule).not.toMatch(/background:\s*var\(--accent\)/);
  });

  test('the sidebar width is defined once', () => {
    // It was 260px in the stylesheet and hardcoded again as calc(260px + 16px)
    // for the Workflow button, so widening one left the other overlapping.
    expect(css).toMatch(/--eva-sidebar-w:/);
    expect(css).toMatch(/width:\s*var\(--eva-sidebar-w\)/);
  });
});

describe('text is large enough to read', () => {
  const css = read('App.css');

  // Root scale for every rem-sized piece of text. Read here so the composer
  // check below is in real pixels rather than assuming 16px per rem.
  const rootPx = Number(
    (css.match(/html\s*\{[^}]*font-size:\s*([\d.]+)px/) || [])[1] || 16,
  );

  // Every font-size the composer is given inside a narrow-screen media query,
  // in source order. Written this way because checking ONE rule has now failed
  // twice: first the desktop rule (overridden on mobile), then the
  // max-width:767px block (overridden by a max-width:768px block later in the
  // file, equal specificity, both !important, so the last one wins). A test
  // that inspects a rule which does not win is indistinguishable from no test.
  const mobileComposerSizes = () => {
    const sizes = [];
    const re = /@media[^{]*max-width:\s*(\d+)px[^{]*\{/g;
    let m;
    while ((m = re.exec(css))) {
      if (Number(m[1]) > 900) continue; // not a phone breakpoint
      // Walk to the end of this media block, counting braces.
      let i = re.lastIndex, depth = 1;
      while (i < css.length && depth > 0) {
        if (css[i] === '{') depth++;
        else if (css[i] === '}') depth--;
        i++;
      }
      const block = css.slice(re.lastIndex, i);
      const ruleRe = /([^{}]*\.eva-chat-textarea[^{}]*)\{([^}]*)\}/g;
      let r;
      while ((r = ruleRe.exec(block))) {
        const f = r[2].match(/font-size:\s*([\d.]+)(px|rem)/);
        if (f) {
          sizes.push({
            breakpoint: Number(m[1]),
            px: f[2] === 'px' ? Number(f[1]) : Number(f[1]) * rootPx,
          });
        }
      }
    }
    return sizes;
  };

  test('every mobile composer rule is at least 16px so iOS does not auto-zoom', () => {
    const sizes = mobileComposerSizes();
    expect(sizes.length).toBeGreaterThan(0);
    // ALL of them, not the last: which one wins depends on source order and
    // overlapping breakpoints, and that is exactly what went wrong.
    for (const s of sizes) {
      expect(s.px).toBeGreaterThanOrEqual(16);
    }
  });

  test('the root scale does not drag rem text to an unreadable size', () => {
    // The floor was 14 and is now 12, lowered deliberately when the scale was
    // reduced to 13.5px — not because the guard was inconvenient. Two things
    // make small text defensible here that were not true before: pinch-zoom
    // and text scaling now work (the viewport no longer blocks them), and
    // every colour on the page clears 4.5:1, so size is the only variable
    // left. 12 is the point below which this stops being a size preference
    // and starts being a legibility problem, so the guard stays.
    expect(rootPx).toBeGreaterThanOrEqual(12);
  });
});

describe('breakpoints do not shadow each other', () => {
  const css = read('App.css');

  const widths = (kind) => {
    const re = new RegExp(`@media[^{]*${kind}-width:\\s*(\\d+)px`, 'g');
    const out = new Set();
    let m;
    while ((m = re.exec(css))) out.add(Number(m[1]));
    return [...out].sort((a, b) => a - b);
  };

  test('no two max-width breakpoints sit within 8px of each other', () => {
    // 767px and 768px both matched every phone, so which rule won came down to
    // source order between two values that look interchangeable. The composer
    // fix was applied to the 767px block three times while a 768px block later
    // in the file overrode it — and a viewport of exactly 768px got a
    // half-applied mobile layout, since only one of the two matched.
    const w = widths('max');
    const tooClose = [];
    for (let i = 1; i < w.length; i += 1) {
      if (w[i] - w[i - 1] <= 8) tooClose.push(`${w[i - 1]}px / ${w[i]}px`);
    }
    expect(tooClose).toEqual([]);
  });

  test('min-width breakpoints do not overlap the max-width ones', () => {
    // A min-width:768px beside a max-width:768px applies BOTH at exactly 768.
    const overlap = widths('min').filter((n) => widths('max').includes(n));
    expect(overlap).toEqual([]);
  });
});

describe('health warnings are announced accessibly', () => {
  const topbar = read('components', 'Topbar.js');

  test('the trouble indicator uses a live status role and visible wording', () => {
    expect(topbar).toMatch(/role="status"/);
    expect(topbar).toMatch(/EVA is having trouble/);
    expect(topbar).toMatch(/EVA is running slowly/);
  });

  test('the AI indicator probes the configured ML service health endpoint', () => {
    expect(topbar).toContain("import { RAG_API_BASE_URL } from '../lib/apiConfig';");
    expect(topbar).toContain("healthStatus(RAG_API, '/ml/health')");
  });
});
