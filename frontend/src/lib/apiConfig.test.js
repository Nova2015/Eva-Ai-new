import { resolveServiceBase } from './apiConfig';

describe('resolveServiceBase', () => {
  const defaults = {
    localFallback: 'http://127.0.0.1:8000',
    hostedFallback: 'https://api.example.com',
  };

  test('explicit build-time URL wins and is normalized', () => {
    expect(resolveServiceBase({
      ...defaults, configured: 'https://custom.example.com///',
      hostname: 'eva.vercel.app',
    })).toBe('https://custom.example.com');
  });

  test('localhost and Electron file URLs use loopback defaults', () => {
    expect(resolveServiceBase({ ...defaults, hostname: 'localhost' }))
      .toBe('http://127.0.0.1:8000');
    expect(resolveServiceBase({ ...defaults, hostname: '' }))
      .toBe('http://127.0.0.1:8000');
  });

  test('Render-hosted frontend uses its own origin', () => {
    expect(resolveServiceBase({
      ...defaults, hostname: 'eva-dashboard.onrender.com',
      origin: 'https://eva-dashboard.onrender.com/',
    })).toBe('https://eva-dashboard.onrender.com');
  });

  test('other hosted frontends use the production service fallback', () => {
    expect(resolveServiceBase({
      ...defaults, hostname: 'eva-ai-rho.vercel.app',
      origin: 'https://eva-ai-rho.vercel.app',
    })).toBe('https://api.example.com');
  });
});
