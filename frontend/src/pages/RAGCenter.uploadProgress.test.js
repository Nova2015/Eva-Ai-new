/* Tests for the RAG upload-progress stage animation (component-level).
 * Verifies honest labelling and progress rendering for the REAL 9-state
 * backend job machine, including CHUNKING/VALIDATING (which are real states),
 * indeterminate-vs-determinate bars, no fabricated %, and malformed payloads. */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { UploadProgress, stageLabel, STAGE_LABELS } from './RAGCenter';

const ALL_STATES = [
  'QUEUED', 'PARSING', 'CHUNKING', 'VALIDATING',
  'EMBEDDING', 'INDEXING', 'COMPLETE', 'FAILED', 'CANCELLED',
];

describe('stageLabel mapping', () => {
  test('every real backend state has a friendly label (incl. CHUNKING & VALIDATING)', () => {
    ALL_STATES.forEach((s) => {
      expect(STAGE_LABELS[s]).toBeTruthy();
      expect(stageLabel({ status: s })).toBe(STAGE_LABELS[s]);
    });
    // The two states the original spec claimed didn't exist ARE covered:
    expect(STAGE_LABELS.CHUNKING).toMatch(/chunk/i);
    expect(STAGE_LABELS.VALIDATING).toMatch(/validat/i);
  });

  test('unknown status falls back to backend current_step — never an invented label', () => {
    expect(stageLabel({ status: 'SOMETHING_NEW', current_step: 'Doing a thing' })).toBe('Doing a thing');
  });

  test('unknown status with no current_step falls back to generic Processing', () => {
    expect(stageLabel({ status: 'WAT' })).toBe('Processing…');
  });
});

describe('UploadProgress rendering', () => {
  test('renders the correct label for each state', () => {
    ALL_STATES.forEach((s) => {
      const { unmount } = render(<UploadProgress job={{ status: s, progress: 50 }} />);
      expect(screen.getByText(new RegExp(STAGE_LABELS[s].replace('…', ''), 'i'))).toBeInTheDocument();
      unmount();
    });
  });

  test('numeric progress renders a percentage and sets bar width', () => {
    const { container } = render(<UploadProgress job={{ status: 'EMBEDDING', progress: 55 }} />);
    expect(screen.getByText('55%')).toBeInTheDocument();
    const fill = container.querySelector('.eva-up__fill');
    expect(fill).toHaveStyle({ width: '55%' });
    expect(container.querySelector('.eva-up__track--indeterminate')).toBeNull();
  });

  test('absent progress → indeterminate shimmer and NO fabricated percentage', () => {
    const { container } = render(<UploadProgress job={{ status: 'EMBEDDING' }} />);
    expect(container.querySelector('.eva-up__track--indeterminate')).not.toBeNull();
    // No "%" text anywhere — we never invent a number the backend didn't send.
    expect(screen.queryByText(/%$/)).toBeNull();
    const fill = container.querySelector('.eva-up__fill');
    expect(fill.getAttribute('style')).toBeNull();
  });

  test('COMPLETE shows checkmark + chunk count and a full/complete bar', () => {
    const { container } = render(<UploadProgress job={{ status: 'COMPLETE', progress: 100, chunk_count: 42 }} />);
    expect(screen.getByText(/Upload complete/i)).toBeInTheDocument();
    expect(screen.getByText(/42 chunks/)).toBeInTheDocument();
    expect(container.querySelector('.eva-up__fill--complete')).not.toBeNull();
  });

  test('FAILED shows error text and error styling', () => {
    const { container } = render(<UploadProgress job={{ status: 'FAILED', progress: 100, error: 'boom' }} />);
    expect(screen.getByText(/Upload failed/i)).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(container.querySelector('.eva-up__row--error')).not.toBeNull();
  });

  test('stall notice shows only while non-terminal', () => {
    const { rerender } = render(<UploadProgress job={{ status: 'EMBEDDING', progress: 55 }} stalled />);
    expect(screen.getByText(/Taking longer than expected/i)).toBeInTheDocument();
    rerender(<UploadProgress job={{ status: 'COMPLETE', progress: 100 }} stalled />);
    expect(screen.queryByText(/Taking longer than expected/i)).toBeNull();
  });

  test('status text region is an aria-live polite region', () => {
    const { container } = render(<UploadProgress job={{ status: 'PARSING', progress: 5 }} />);
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  test('malformed payloads do not crash', () => {
    expect(() => render(<UploadProgress job={{}} />)).not.toThrow();
    expect(() => render(<UploadProgress job={{ status: 'EMBEDDING', progress: 'oops' }} />)).not.toThrow();
    expect(() => render(<UploadProgress job={null} />)).not.toThrow();
  });

  test('null job renders nothing', () => {
    const { container } = render(<UploadProgress job={null} />);
    expect(container.firstChild).toBeNull();
  });
});
