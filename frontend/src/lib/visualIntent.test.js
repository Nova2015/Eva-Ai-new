import {
  wantsDataArtifact,
  wantsStructuredDiagram,
  imageGeneratorMayHandle,
  UNVERIFIED_IMAGE_NOTE,
} from './visualIntent';

// The failure being fixed, from a real screenshot: "Creating image for excel
// sheet for all data set" produced a PNG that looks like a spreadsheet.
//
// The load-bearing tests are the ones that keep the image generator from
// taking a message someone else can answer verifiably — and, equally, the ones
// that stop this guard from swallowing genuine image requests. Both failures
// are silent to the user; they just get the wrong kind of thing.

describe('requests that belong to a verified artifact path', () => {
  test.each([
    'Creating image for excel sheet for all data set',   // the screenshot
    'create an image of a spreadsheet with sales data',
    'make me an excel sheet',
    'generate a csv of the results',
    'picture of a bar chart of these numbers',
    'image for chart of revenue',
    'draw a pie chart of the sales split',
  ])('the image generator must not take %j', (text) => {
    expect(imageGeneratorMayHandle(text)).toBe(false);
  });

  test('a spreadsheet is recognised however it is named', () => {
    for (const word of ['excel', 'xlsx', 'spreadsheet', 'workbook', 'csv']) {
      expect(wantsDataArtifact(`make an ${word} from this`)).toBe(true);
    }
  });
});

describe('structured diagrams beat rasters', () => {
  test.each([
    'create an image of a flowchart for sheet-metal manufacturing',
    'draw a sequence diagram for the login flow',
    'make an image of our org chart',
    'picture of the decision tree',
    'generate an architecture diagram of the system',
  ])('the image generator must not take %j', (text) => {
    // A mermaid diagram is text: its structure can be read and checked. A PNG
    // of the same thing cannot.
    expect(imageGeneratorMayHandle(text)).toBe(false);
    expect(wantsStructuredDiagram(text)).toBe(true);
  });

  test('an aesthetic request for a diagram is still an image', () => {
    // Someone asking for a poster wants a poster.
    expect(wantsStructuredDiagram('make a poster of our process flow')).toBe(false);
    expect(imageGeneratorMayHandle('make a poster of our process flow')).toBe(true);
    expect(wantsStructuredDiagram('a realistic photo of a flowchart on a wall'))
      .toBe(false);
  });
});

describe('genuine image requests still get through', () => {
  test.each([
    'create an image of a car dashboard',
    'generate an image of a mountain at sunrise',
    'draw a logo for a bakery',
    'make a poster for the show',
    'picture of a golden retriever',
    'concept art of a spaceship',
    'illustration of a cell membrane',
  ])('the image generator may take %j', (text) => {
    // Over-blocking is as bad as over-taking: the user asked for a picture and
    // would get prose instead, with no indication why.
    expect(imageGeneratorMayHandle(text)).toBe(true);
  });
});

describe('the guard is actually wired into the image path', () => {
  const fs = require('fs');
  const path = require('path');
  const chat = fs.readFileSync(
    path.join(__dirname, '..', 'pages', 'Chat.js'), 'utf8');

  test('Chat.js imports it', () => {
    expect(chat).toMatch(/import\s*\{[^}]*imageGeneratorMayHandle[^}]*\}\s*from\s*'\.\.\/lib\/visualIntent'/);
  });

  test('isImageRequest consults it before its own chain', () => {
    // A perfect module that nothing calls is indistinguishable from no module.
    // The chain below it is broad, so this has to run first or it decides
    // nothing.
    const start = chat.indexOf('const isImageRequest');
    expect(start).toBeGreaterThan(-1);
    const body = chat.slice(start, start + 1600);
    const guard = body.indexOf('imageGeneratorMayHandle');
    const chain = body.indexOf("startsWith('generate image')");
    expect(guard).toBeGreaterThan(-1);
    expect(chain).toBeGreaterThan(-1);
    expect(guard).toBeLessThan(chain);
  });
});

describe('safety of the guard itself', () => {
  test.each([null, undefined, '', '   '])('empty input is not handled: %j', (t) => {
    expect(imageGeneratorMayHandle(t)).toBe(false);
  });

  test('the guard never throws on odd input', () => {
    for (const value of [123, {}, [], true]) {
      expect(() => imageGeneratorMayHandle(value)).not.toThrow();
    }
  });

  test('the unverified note says what it cannot promise', () => {
    expect(UNVERIFIED_IMAGE_NOTE).toMatch(/not checked|unverified/i);
  });
});
