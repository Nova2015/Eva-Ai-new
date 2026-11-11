import { render, screen } from '@testing-library/react';
import ProvenanceDetails from './ProvenanceDetails';
import ProvenanceBadges from './ProvenanceBadges';

// The provenance rule, enforced where it can actually fail the build.
//
// This exists because the rule was previously only checkable two ways: by
// reading a four-thousand-line component, or by loading a signed-in browser
// session. Neither runs in CI. A regression that un-gates the panel would have
// shipped silently.
//
// The load-bearing assertions are the NEGATIVE ones. "It appears when asked"
// is easy; "it never appears otherwise" is the actual rule.

const AUDIT = {
  mode: 'hybrid',
  confidence: 0.87,
  sourceIds: ['handbook.pdf', 'notes.md', 'spec.txt'],
  auditId: 'aud_123',
  rewrittenQuery: 'hash table collision handling',
  channels: { bm25: 3, vector: 5 },
};

const REVIEW = { status: 'passed', score: 0.9, issues: [] };
const RUNTIME = { status: 'ok', language: 'python', durationMs: 42 };

describe('ProvenanceDetails — hidden unless asked', () => {
  test('renders nothing by default, even with a full audit payload', () => {
    const { container } = render(<ProvenanceDetails show={false} ragAudit={AUDIT} />);
    expect(container).toBeEmptyDOMElement();
  });

  test.each([undefined, null, false, 0, ''])(
    'renders nothing when show is %p',
    (show) => {
      const { container } = render(<ProvenanceDetails show={show} ragAudit={AUDIT} />);
      expect(container).toBeEmptyDOMElement();
    },
  );

  test('leaks no source name, confidence or audit id while hidden', () => {
    const { container } = render(<ProvenanceDetails show={false} ragAudit={AUDIT} />);
    const html = container.innerHTML;
    for (const secret of ['handbook.pdf', 'notes.md', 'spec.txt', 'aud_123',
      'hybrid', '87', 'bm25']) {
      expect(html).not.toContain(secret);
    }
  });

  test('renders nothing when there is no audit payload at all', () => {
    const { container } = render(<ProvenanceDetails show ragAudit={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ProvenanceDetails — shown once asked', () => {
  test('reveals mode, confidence and source count', () => {
    render(<ProvenanceDetails show ragAudit={AUDIT} />);
    expect(screen.getByText('RAG audit')).toBeInTheDocument();
    expect(screen.getByText('hybrid')).toBeInTheDocument();
    expect(screen.getByText('87% confidence')).toBeInTheDocument();
    expect(screen.getByText('3 sources')).toBeInTheDocument();
  });

  test('reveals the query, audit id and source names', () => {
    render(<ProvenanceDetails show ragAudit={AUDIT} />);
    expect(screen.getByText('hash table collision handling')).toBeInTheDocument();
    expect(screen.getByText('aud_123')).toBeInTheDocument();
    expect(screen.getByText(/handbook\.pdf/)).toBeInTheDocument();
  });

  test('opens rather than making the user click twice to see it', () => {
    const { container } = render(<ProvenanceDetails show ragAudit={AUDIT} />);
    expect(container.querySelector('details')).toHaveAttribute('open');
  });

  test('a missing sourceIds array does not crash the panel', () => {
    render(<ProvenanceDetails show ragAudit={{ mode: 'bm25', confidence: 0.5 }} />);
    expect(screen.getByText('0 sources')).toBeInTheDocument();
  });
});

describe('ProvenanceBadges — hidden unless asked', () => {
  test('renders nothing by default even with review and runtime present', () => {
    const { container } = render(
      <ProvenanceBadges show={false} review={REVIEW} runtime={RUNTIME} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test('renders nothing while the answer is still streaming', () => {
    const { container } = render(
      <ProvenanceBadges show review={REVIEW} runtime={RUNTIME} streaming />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test('renders nothing when there is no metadata to show', () => {
    const { container } = render(<ProvenanceBadges show />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ProvenanceBadges — shown once asked', () => {
  test('renders something when revealed with a review', () => {
    const { container } = render(<ProvenanceBadges show review={REVIEW} />);
    expect(container).not.toBeEmptyDOMElement();
  });

  test('renders something when revealed with a runtime result', () => {
    const { container } = render(<ProvenanceBadges show runtime={RUNTIME} />);
    expect(container).not.toBeEmptyDOMElement();
  });
});
