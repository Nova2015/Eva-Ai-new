/**
 * EVA — Centralized API Utility
 * Handles all fetch calls, JSON parsing, auth errors, and local API headers
 */


/**
 * Core fetch wrapper — safe JSON parsing, error handling, logging
 */
export async function apiFetch(url, options = {}) {
  try {
    // Merge request headers
    const headers = { ...(options.headers || {}) };

    const res = await fetch(url, { ...options, headers });

    // Read raw text first (prevents "body used already" crash)
    const text = await res.text();

    // Log raw response for debugging
    if (process.env.NODE_ENV === 'development') {
      console.log(`[API] ${options.method || 'GET'} ${url}`, res.status, text.slice(0, 200));
    }

    // Parse JSON safely
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      // Backend returned HTML (ngrok warning page, 502, etc.)
      if (text.includes('<!DOCTYPE') || text.includes('<html')) {
        throw new Error('Backend returned an HTML page — is the local server running?');
      }
      throw new Error(`Invalid JSON from ${url}: ${text.slice(0, 100)}`);
    }

    // Handle HTTP errors
    if (!res.ok) {
      if (res.status === 401) throw new AuthError(data.detail || 'Session expired');
      if (res.status === 429) throw new Error('Rate limit hit — please wait a moment');
      if (res.status === 500) throw new Error(data.detail || 'Server error');
      throw new Error(data.detail || `Request failed (${res.status})`);
    }

    return data;

  } catch (err) {
    if (err instanceof AuthError) throw err;
    console.error('[API ERROR]', err.message);
    throw err;
  }
}

/** Special error class for 401 — lets callers handle auth separately */
export class AuthError extends Error {
  constructor(msg) { super(msg); this.name = 'AuthError'; }
}

/**
 * Authenticated fetch — auto-injects Bearer token from localStorage
 */
export async function authFetch(url, options = {}) {
  const token = localStorage.getItem('aria_token');
  return apiFetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
}

/**
 * POST helper — shorthand for JSON POST requests
 */
export async function apiPost(url, body, token) {
  return apiFetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token && token !== 'offline' ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
}

/**
 * Safe array helper — prevents ".map is not a function" crashes
 */
export function safeArray(val) {
  return Array.isArray(val) ? val : [];
}

/**
 * Safe string helper
 */
export function safeString(val, fallback = '') {
  return typeof val === 'string' ? val : fallback;
}
