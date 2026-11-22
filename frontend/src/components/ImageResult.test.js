import { render, screen } from '@testing-library/react';
import ImageResult from './ImageResult';
import { UNVERIFIED_IMAGE_NOTE } from '../lib/visualIntent';

// Update 35c. The guard keeps the image generator off work that can be
// verified. This covers what happens when an image IS the right answer: EVA
// says plainly that its contents are not checked against anything.
//
// A generated picture is the only artifact here nothing can validate, and one
// that looks like a diagram or a screenshot invites being read as fact.

const IMAGES = [{ url: 'https://example.invalid/a.png' }];

describe('the unverified note', () => {
  test('is shown with a generated image', () => {
    render(<ImageResult images={IMAGES} prompt="a car dashboard" />);
    expect(screen.getByText(UNVERIFIED_IMAGE_NOTE)).toBeInTheDocument();
  });

  test('says what it cannot promise, not just that it is AI-made', () => {
    // "Made with AI" is a label. The useful statement is that the CONTENTS
    // were not checked, which is what a reader would otherwise assume.
    expect(UNVERIFIED_IMAGE_NOTE.toLowerCase()).toMatch(/not checked|unverified/);
    expect(UNVERIFIED_IMAGE_NOTE.toLowerCase()).toMatch(/source|detail/);
  });

  test('is rendered as text rather than hidden behind a control', () => {
    // A caveat behind a tooltip or a collapsed panel is one nobody reads.
    const { container } = render(
      <ImageResult images={IMAGES} prompt="a car dashboard" />);
    const note = container.querySelector('.eva-img-unverified');
    expect(note).toBeTruthy();
    expect(note.textContent).toBe(UNVERIFIED_IMAGE_NOTE);
    expect(note.closest('details')).toBeNull();
    expect(note.getAttribute('hidden')).toBeNull();
  });

  test('appears once, not once per image', () => {
    render(<ImageResult
      images={[{ url: 'https://example.invalid/a.png' },
               { url: 'https://example.invalid/b.png' },
               { url: 'https://example.invalid/c.png' }]}
      prompt="four variations" />);
    expect(screen.getAllByText(UNVERIFIED_IMAGE_NOTE)).toHaveLength(1);
  });
});
