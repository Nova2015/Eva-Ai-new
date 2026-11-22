/**
 * Resolve the backend and RAG service URLs for local, desktop and hosted EVA.
 * Explicit REACT_APP_* values always win. Local browser/Electron sessions keep
 * loopback defaults. Hosted Vercel clients use the production services, while
 * a Render-hosted frontend talks to its own origin for the API.
 */
const normalizeBase = (value) => String(value || '').trim().replace(/\/+$/, '');

export function resolveServiceBase({
  configured,
  hostname = '',
  origin = '',
  localFallback,
  hostedFallback,
}) {
  const explicit = normalizeBase(configured);
  if (explicit) return explicit;

  const host = String(hostname || '').toLowerCase();
  const isLocal = !host || host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0';
  if (isLocal) return normalizeBase(localFallback);

  if (host.endsWith('.onrender.com') && origin) return normalizeBase(origin);
  return normalizeBase(hostedFallback);
}

const browserLocation = typeof window !== 'undefined' ? window.location : null;
const hostname = browserLocation?.hostname || '';
const origin = browserLocation?.origin || '';

export const API_BASE_URL = resolveServiceBase({
  configured: process.env.REACT_APP_API_BASE || process.env.REACT_APP_API_BASE_URL,
  hostname,
  origin,
  localFallback: 'http://127.0.0.1:8000',
  hostedFallback: 'https://eva-ai-1-9wfc.onrender.com',
});

export const RAG_API_BASE_URL = resolveServiceBase({
  configured: process.env.REACT_APP_RAG_API_BASE,
  hostname,
  origin,
  localFallback: 'http://127.0.0.1:7860',
  hostedFallback: 'https://keshav1212-eva-ml-service.hf.space',
});
