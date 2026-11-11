import fs from 'fs';
import path from 'path';

// A Mermaid/flowchart diagram is the tallest thing EVA renders in a chat turn.
// On a narrow screen the composer is position:fixed and floats over the bottom
// of the scroll area, so the message list has to RESERVE enough bottom space for
// the whole composer or the end of a tall diagram sits underneath it and cannot
// be read. These are the two source facts that keep that reserve honest; they
// are asserted from source because the failure only shows up scrolled to the
// very bottom of a long diagram, which no render test reliably reaches.

const read = (...p) => fs.readFileSync(path.join(__dirname, ...p), 'utf8');

describe('a tall diagram clears the fixed mobile composer', () => {
  const chat = read('pages', 'Chat.js');
  const css = read('App.css');

  test('the composer really does float over the scroll area on mobile', () => {
    // The reserve below only matters because the composer is taken out of flow
    // on narrow screens. If this ever stops being fixed, revisit the reserve —
    // an in-flow composer (as on desktop) needs none.
    expect(css).toMatch(/\.eva-chat-input-area\s*\{[^}]*position:\s*fixed/);
  });

  test('the message list reserves enough bottom space for that composer', () => {
    // The mobile composer's textarea grows to at most 112px (min(scrollHeight,
    // 112)), so the whole bar occupies ~134px including its 10px offset. The
    // conversation log's mobile bottom padding must exceed that, or the last of
    // a tall diagram is hidden behind the bar. Desktop keeps its own (small)
    // value because its composer sits in flow, below the log, and never overlaps.
    const m = chat.match(
      /id="eva-conversation"[\s\S]*?padding:\s*isMobile\s*\?\s*'([^']+)'\s*:\s*'([^']+)'/,
    );
    expect(m).toBeTruthy();
    const mobileBottom = Number((m[1].trim().split(/\s+/).pop().match(/(\d+)px/) || [])[1]);
    expect(mobileBottom).toBeGreaterThanOrEqual(160);
  });
});

describe('the diagram container scrolls instead of clipping', () => {
  const chat = read('pages', 'Chat.js');

  // The style object on the rendered-diagram <div> — the only one carrying
  // WebkitOverflowScrolling, which distinguishes it from the error-fallback box
  // (that one legitimately uses overflow:hidden for its rounded border).
  const block = (() => {
    const start = chat.indexOf('function MermaidBlock');
    const rest = chat.slice(start + 1);
    const end = rest.indexOf('\nfunction ');
    const fn = end >= 0 ? chat.slice(start, start + 1 + end) : chat.slice(start);
    const m = fn.match(/<div style=\{\{([^}]*WebkitOverflowScrolling[^}]*)\}\}/);
    return m ? m[1] : '';
  })();

  test('the container is found', () => {
    expect(block).toBeTruthy();
  });

  test('wide diagrams can scroll horizontally', () => {
    expect(block).toMatch(/overflow(X)?:\s*'auto'/);
  });

  test('nothing is clipped away', () => {
    // overflow:hidden here would silently amputate anything past the edge.
    expect(block).not.toMatch(/overflow:\s*'hidden'/);
  });

  test('no fixed height caps a tall diagram', () => {
    // A pixel height (or maxHeight) would cut off a long flowchart. Vertical
    // scrolling is the message list's job, so the container must stay uncapped
    // and grow to the diagram's natural height.
    expect(block).not.toMatch(/maxHeight/);
    expect(block).not.toMatch(/height:\s*\d/);
  });
});

describe('the diagram renders at its natural size, not stretched', () => {
  const chat = read('pages', 'Chat.js');

  // The whole MermaidBlock function, where the rendered <svg> is sized.
  const fn = (() => {
    const start = chat.indexOf('function MermaidBlock');
    const rest = chat.slice(start + 1);
    const end = rest.indexOf('\nfunction ');
    return end >= 0 ? chat.slice(start, start + 1 + end) : chat.slice(start);
  })();

  test('the svg is pinned to its intrinsic viewBox width', () => {
    // Mermaid emits the svg with width="100%". Left as-is (or with an added
    // max-width:100%) it stretches a small vertical flowchart to the full column
    // width, blowing every node up several times over. The fix reads the
    // viewBox and sets an explicit pixel width so it renders at natural scale.
    expect(fn).toMatch(/viewBox/);
    expect(fn).toMatch(/baseVal/);
    expect(fn).toMatch(/\.style\.width\s*=/);
  });

  test('the svg is not force-stretched with max-width:100%', () => {
    // This exact override is what caused the giant-diagram regression; it must
    // not come back. Natural width + the container's overflow handle sizing.
    expect(fn).not.toMatch(/maxWidth\s*=\s*'100%'/);
  });
});
