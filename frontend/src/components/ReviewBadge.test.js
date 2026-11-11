import { render, screen } from '@testing-library/react';
import ReviewBadge from './ReviewBadge';

test('status=VALID renders the validated pill', () => {
  render(<ReviewBadge review={{ status: 'VALID', badge: true }} />);
  const pill = screen.getByTestId('review-badge');
  expect(pill).toHaveTextContent('✓ Validated');
  expect(pill).toHaveStyle({ color: '#22c55e' });
});

test('badge=false / status=null renders nothing (KEY case)', () => {
  const { container: c1 } = render(<ReviewBadge review={{ status: null, badge: false }} />);
  expect(c1).toBeEmptyDOMElement();

  const { container: c2 } = render(<ReviewBadge review={{ status: 'VALID', badge: false }} />);
  expect(c2).toBeEmptyDOMElement();

  const { container: c3 } = render(<ReviewBadge review={undefined} />);
  expect(c3).toBeEmptyDOMElement();

  // Unknown future status strings render nothing, not a broken pill.
  const { container: c4 } = render(<ReviewBadge review={{ status: 'SOMETHING_NEW', badge: true }} />);
  expect(c4).toBeEmptyDOMElement();
});

test('status=FAILED renders red pill AND message content still renders', () => {
  render(
    <div>
      <ReviewBadge review={{ status: 'FAILED', badge: true }} />
      <p>the original assistant answer</p>
    </div>
  );
  const pill = screen.getByTestId('review-badge');
  expect(pill).toHaveTextContent('✗ Invalid');
  expect(pill).toHaveStyle({ color: '#ef4444' });
  // Informational only — content is never hidden or blocked by status.
  expect(screen.getByText('the original assistant answer')).toBeInTheDocument();
});

test('status=UNKNOWN renders gray pill, not green', () => {
  render(<ReviewBadge review={{ status: 'UNKNOWN', badge: true }} />);
  const pill = screen.getByTestId('review-badge');
  expect(pill).toHaveTextContent('? Unknown');
  expect(pill).toHaveStyle({ color: '#9ca3af' });
});

test('malformed review objects never crash and render nothing', () => {
  const malformed = [
    { status: 42, badge: true },                 // non-string status
    { status: { deep: 'object' }, badge: true }, // object status
    { badge: 'yes' },                            // non-bool badge
    'not-an-object',
    [],
    { status: 'VALID', badge: true, issues: 'not-an-array' }, // bad issues -> pill only
  ];
  for (const review of malformed.slice(0, 5)) {
    const { container, unmount } = render(<ReviewBadge review={review} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
  }
  // Bad issues shape: pill still renders, list is silently skipped.
  render(<ReviewBadge review={malformed[5]} />);
  expect(screen.getByTestId('review-badge')).toHaveTextContent('✓ Validated');
  expect(screen.queryByTestId('review-issues')).toBeNull();
});

test('issues list maps codes to human labels (debug/full payload only)', () => {
  render(
    <ReviewBadge
      review={{
        status: 'FAILED',
        badge: true,
        issues: [
          { code: 'malformed_block', detail: 'x' },
          { code: 'unbalanced_brackets', detail: 'y' },
          { code: 'python_syntax_error', detail: 'z' },
          { code: 'totally_new_code', detail: 'w' }, // unmapped -> raw code shown
          { bogus: true },                            // malformed entry -> skipped
        ],
      }}
    />
  );
  const list = screen.getByTestId('review-issues');
  expect(list).toHaveTextContent('Invalid chart structure');
  expect(list).toHaveTextContent('Mermaid syntax issue');
  expect(list).toHaveTextContent('Python syntax error');
  expect(list).toHaveTextContent('totally_new_code');
  expect(list.querySelectorAll('li')).toHaveLength(4);
});

test('debug panel appears only with review_meta and labels the score', () => {
  // Minimal payload (non-debug): no panel.
  render(<ReviewBadge review={{ status: 'VALID', badge: true }} />);
  expect(screen.queryByTestId('review-debug')).toBeNull();

  // Full payload (debug): panel present, score labelled as check-ratio.
  render(
    <ReviewBadge
      review={{
        status: 'WARNING', badge: true, score: 0.5,
        issues: [{ code: 'merged_datasets', detail: 'd' }],
        review_meta: { mode: 'standard', validator_version: 'v1', execution_ms: 3, error: null },
      }}
    />
  );
  const panel = screen.getByTestId('review-debug');
  expect(panel).toHaveTextContent('check-ratio, not a quality score');
  expect(panel).toHaveTextContent('execution_ms: 3');
  expect(panel).toHaveTextContent('merged_datasets');
});
