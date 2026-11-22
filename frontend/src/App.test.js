import fs from 'fs';
import path from 'path';

const source = fs.readFileSync(path.join(__dirname, 'App.js'), 'utf8');

describe('application API configuration wiring', () => {
  test('the app uses the shared environment-aware API base', () => {
    expect(source).toContain("import { API_BASE_URL } from './lib/apiConfig';");
    expect(source).toContain('const API = API_BASE_URL;');
  });

  test('the application retains its hash-based route container', () => {
    expect(source).toMatch(/<HashRouter[\s>]/);
  });
});
