import { render, screen } from '@testing-library/react';
import RuntimeBadge, { adaptRuntime, isExecuted } from './RuntimeBadge';
import ReviewBadge from './ReviewBadge';

const base = {
  status: 'SUCCESS', language: 'python', stdout: 'hello\n', stderr: '',
  exit_code: 0, execution_ms: 123, timed_out: false, truncated: false,
  runtime_source: 'piston', error: null,
};

test('1. SUCCESS -> green "Executed"', () => {
  render(<RuntimeBadge runtime={base} />);
  const pill = screen.getByTestId('runtime-badge');
  expect(pill).toHaveTextContent('Executed');
  expect(pill).toHaveStyle({ color: '#22c55e' });
});

test('2. RUNTIME_ERROR -> red', () => {
  render(<RuntimeBadge runtime={{ ...base, status: 'RUNTIME_ERROR', exit_code: 1, stderr: 'Traceback...' }} />);
  const pill = screen.getByTestId('runtime-badge');
  expect(pill).toHaveTextContent('Runtime Error');
  expect(pill).toHaveStyle({ color: '#ef4444' });
});

test('3. TIMEOUT -> orange', () => {
  render(<RuntimeBadge runtime={{ ...base, status: 'TIMEOUT', timed_out: true }} />);
  const pill = screen.getByTestId('runtime-badge');
  expect(pill).toHaveTextContent('Timeout');
  expect(pill).toHaveStyle({ color: '#f97316' });
});

test('4. UNKNOWN -> gray "Execution Unknown", no output panel', () => {
  render(<RuntimeBadge runtime={{ ...base, status: 'UNKNOWN', error: 'piston http 503' }} />);
  const pill = screen.getByTestId('runtime-badge');
  expect(pill).toHaveTextContent('Execution Unknown');
  expect(pill).toHaveStyle({ color: '#9ca3af' });
  // UNKNOWN means the code never ran -> executed is false -> no panel.
  expect(screen.queryByTestId('runtime-panel')).toBeNull();
});

test('5. no runtime object -> no runtime badge', () => {
  const { container } = render(<RuntimeBadge runtime={undefined} />);
  expect(container).toBeEmptyDOMElement();
  const { container: c2 } = render(<RuntimeBadge runtime={null} />);
  expect(c2).toBeEmptyDOMElement();
});

test('6. large output -> collapsed by default, expandable', () => {
  const big = 'y'.repeat(5000);
  render(<RuntimeBadge runtime={{ ...base, stdout: big, truncated: true }} />);
  const details = screen.getByTestId('runtime-stdout');
  expect(details.tagName).toBe('DETAILS');
  expect(details).not.toHaveAttribute('open');       // collapsed by default
  expect(details.querySelector('summary')).toBeTruthy(); // expandable
  expect(screen.getByTestId('runtime-meta')).toHaveTextContent('output truncated');
});

test('7. review VALID -> "Validated" (relabelled per slice 5 spec)', () => {
  render(<ReviewBadge review={{ status: 'VALID', badge: true }} />);
  expect(screen.getByTestId('review-badge')).toHaveTextContent('Validated');
});

test('8. runtime + review both present -> both badges render independently', () => {
  render(
    <div>
      <ReviewBadge review={{ status: 'WARNING', badge: true }} />
      <RuntimeBadge runtime={base} />
    </div>
  );
  expect(screen.getByTestId('review-badge')).toHaveTextContent('Warning');
  expect(screen.getByTestId('runtime-badge')).toHaveTextContent('Executed');
});

test('9. empty stdout -> "(no stdout)"; empty stderr -> stderr section absent', () => {
  render(<RuntimeBadge runtime={{ ...base, stdout: '', stderr: '' }} />);
  expect(screen.getByTestId('runtime-stdout')).toHaveTextContent('(no stdout)');
  expect(screen.queryByTestId('runtime-stderr')).toBeNull();
});

test('10. lowercase/garbage status -> safe default, no crash, nothing rendered', () => {
  for (const status of ['success', 'Success', 'EXPLODED', 42, null, {}]) {
    const { container, unmount } = render(<RuntimeBadge runtime={{ ...base, status }} />);
    expect(container).toBeEmptyDOMElement(); // never "Executed" unless exactly "SUCCESS"
    unmount();
  }
});

test('adapter maps real backend fields and derives executed', () => {
  const a = adaptRuntime(base);
  expect(a.duration_ms).toBe(123);      // <- execution_ms
  expect(a.source).toBe('piston');      // <- runtime_source
  expect(isExecuted(a)).toBe(true);
  expect(isExecuted(adaptRuntime({ ...base, status: 'UNKNOWN' }))).toBe(false);
  expect(isExecuted(null)).toBe(false);
  expect(adaptRuntime('garbage')).toBeNull();
});

test('stderr section renders when stderr non-empty', () => {
  render(<RuntimeBadge runtime={{ ...base, status: 'RUNTIME_ERROR', stderr: 'boom' }} />);
  expect(screen.getByTestId('runtime-stderr')).toHaveTextContent('boom');
});
