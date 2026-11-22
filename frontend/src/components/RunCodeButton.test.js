import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import RunCodeButton, { extractRunnableBlock } from './RunCodeButton';

const pyMessage = 'Here is the script:\n```python\nprint("hi")\n```\nEnjoy!';

const successResult = {
  status: 'SUCCESS', language: 'python', stdout: 'hi\n', stderr: '',
  exit_code: 0, execution_ms: 42, timed_out: false, truncated: false,
  runtime_source: 'piston', error: null,
};

afterEach(() => {
  delete global.fetch;
});

test('eligible true -> Run button present', () => {
  render(<RunCodeButton messageText={pyMessage} runnable={{ eligible: true, language: 'python' }} apiBase="http://x" token="" />);
  expect(screen.getByTestId('run-code-btn')).toHaveTextContent('Run python');
});

test('eligible false / absent / malformed -> no button, no crash', () => {
  const cases = [
    { eligible: false, language: null },
    undefined,
    null,
    'garbage',
    { eligible: 'yes' },
  ];
  for (const runnable of cases) {
    const { container, unmount } = render(
      <RunCodeButton messageText={pyMessage} runnable={runnable} apiBase="http://x" token="" />
    );
    expect(container).toBeEmptyDOMElement();
    unmount();
  }
  // Eligible flag but message has two blocks -> client mirror refuses too.
  const twoBlocks = '```python\nprint(1)\n```\n```js\nconsole.log(2)\n```';
  const { container } = render(
    <RunCodeButton messageText={twoBlocks} runnable={{ eligible: true, language: 'python' }} apiBase="http://x" token="" />
  );
  expect(container).toBeEmptyDOMElement();
});

test('click + mocked execute SUCCESS -> "Executed" + stdout; nothing before click', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => successResult });
  render(<RunCodeButton messageText={pyMessage} runnable={{ eligible: true, language: 'python' }} apiBase="http://x" token="tok" />);

  // Never "Executed" without a real click + SUCCESS result.
  expect(screen.queryByTestId('runtime-badge')).toBeNull();

  fireEvent.click(screen.getByTestId('run-code-btn'));
  await waitFor(() => expect(screen.getByTestId('runtime-badge')).toHaveTextContent('Executed'));
  expect(screen.getByTestId('runtime-stdout')).toHaveTextContent('hi');

  const [url, opts] = global.fetch.mock.calls[0];
  expect(url).toBe('http://x/runtime/execute');
  expect(JSON.parse(opts.body)).toEqual({ language: 'python', code: 'print("hi")' });
});

test('click + mocked RUNTIME_ERROR -> red badge, stderr shown', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ...successResult, status: 'RUNTIME_ERROR', exit_code: 1, stdout: '', stderr: 'ZeroDivisionError' }),
  });
  render(<RunCodeButton messageText={pyMessage} runnable={{ eligible: true, language: 'python' }} apiBase="http://x" token="" />);
  fireEvent.click(screen.getByTestId('run-code-btn'));
  const badge = await screen.findByTestId('runtime-badge');
  expect(badge).toHaveTextContent('Runtime Error');
  expect(badge).toHaveStyle({ color: '#ef4444' });
  expect(screen.getByTestId('runtime-stderr')).toHaveTextContent('ZeroDivisionError');
});

test('execute endpoint disabled (403) -> gray Execution Unknown, no crash', async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({}) });
  render(<RunCodeButton messageText={pyMessage} runnable={{ eligible: true, language: 'python' }} apiBase="http://x" token="" />);
  fireEvent.click(screen.getByTestId('run-code-btn'));
  const badge = await screen.findByTestId('runtime-badge');
  expect(badge).toHaveTextContent('Execution Unknown');
});

test('extractRunnableBlock mirrors backend policy', () => {
  expect(extractRunnableBlock(pyMessage)).toEqual({ language: 'python', code: 'print("hi")' });
  expect(extractRunnableBlock('no code here')).toBeNull();
  expect(extractRunnableBlock('```bash\nls\n```')).toBeNull();
  // chart/mermaid fences do not count as code blocks
  const mixed = '```chart\n{"type":"pie","data":[]}\n```\n```js\nconsole.log(1)\n```';
  expect(extractRunnableBlock(mixed)).toEqual({ language: 'javascript', code: 'console.log(1)' });
});
