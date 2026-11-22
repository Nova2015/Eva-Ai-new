import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { GoogleLogin } from '@react-oauth/google';
import { ensureLocalAuth } from '../localAuth';

const API = process.env.REACT_APP_API_BASE || 'http://127.0.0.1:3000';
const IS_ADMIN_WORKSPACE = window.location.port === '8003' && process.env.REACT_APP_ADMIN_MODE === 'true';

// ── Token helpers ─────────────────────────────────────────
export const saveToken = (token, user) => {
  localStorage.setItem('aria_token', token);
  localStorage.setItem('aria_user', JSON.stringify(user));
};

export const getToken = () => localStorage.getItem('aria_token');

export const getUser = () => {
  try {
    return JSON.parse(localStorage.getItem('aria_user') || 'null');
  } catch {
    return null;
  }
};

export const clearAuth = () => {
  localStorage.removeItem('aria_token');
  localStorage.removeItem('aria_user');
};

export const isLoggedIn = () => !!getToken();

export default function Login({ initialScreen = 'home' }) {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || (IS_ADMIN_WORKSPACE ? '/update-intelligence' : '/chat');

  const [screen, setScreen] = useState(initialScreen); // home | login | signup | forgot
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');

  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPw, setShowPw] = useState(false);

  useEffect(() => {
    if (ensureLocalAuth()) {
      navigate(from, { replace: true });
      return;
    }
    if (isLoggedIn()) navigate(from);
  }, [navigate, from]);

  const clearMessages = () => {
    setError('');
    setInfo('');
  };

  // ── EMAIL LOGIN ─────────────────────────────────────────
  const handleLogin = async (e) => {
    e?.preventDefault();

    if (!email || !password) {
      setError('Enter email and password');
      return;
    }

    setLoading(true);
    clearMessages();

    try {
      const loginPayload = {
        username: email,
        password,
        ...(email.includes('@') ? { email } : {}),
      };

      const res = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify(loginPayload),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Invalid email or password');
      }

      const token = data.access_token || data.token;

      if (!token) {
        throw new Error('Login token missing from backend response');
      }

      saveToken(token, data.user || {
        email,
        name: data.name || email.split('@')[0],
        role: data.role || 'user',
        provider: 'email',
      });

      navigate(from);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  // ── SIGNUP ──────────────────────────────────────────────
  const handleSignup = async (e) => {
    e?.preventDefault();

    if (!name || !email || !password) {
      setError('All fields required');
      return;
    }

    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }

    setLoading(true);
    clearMessages();

    try {
      const res = await fetch(`${API}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({
          name,
          full_name: name,
          username: email,
          email,
          password,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Registration failed');
      }

      const token = data.access_token || data.token;

      if (!token) {
        throw new Error('Register token missing from backend response');
      }

      saveToken(token, data.user || {
        name,
        email,
        role: 'user',
        provider: 'email',
      });

      navigate(from);
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  // ── FORGOT PASSWORD ─────────────────────────────────────
  const handleForgot = async (e) => {
    e?.preventDefault();

    if (!email) {
      setError('Enter your email');
      return;
    }

    setLoading(true);
    clearMessages();

    try {
      const res = await fetch(`${API}/auth/forgot-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({ email }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Reset request failed');
      }

      setInfo(`Reset link sent to ${email}`);
    } catch (err) {
      setError(err.message || 'Reset failed');
    } finally {
      setLoading(false);
    }
  };

  // ── REAL GOOGLE LOGIN ───────────────────────────────────
  const handleGoogleSuccess = async (credentialResponse) => {
    if (!credentialResponse?.credential) {
      setError('Google credential missing');
      return;
    }

    setLoading(true);
    clearMessages();

    try {
      const res = await fetch(`${API}/auth/google`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({
          credential: credentialResponse.credential,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Google login failed');
      }

      const token = data.access_token || data.token;

      if (!token) {
        throw new Error('Google token missing from backend response');
      }

      saveToken(token, data.user || {
        name: 'Google User',
        email: 'google@demo.com',
        role: 'user',
        provider: 'google',
      });

      navigate(from);
    } catch (err) {
      setError(err.message || 'Google login failed');
    } finally {
      setLoading(false);
    }
  };

  // ── STYLES ──────────────────────────────────────────────
  const S = {
    page: {
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '"Inter", -apple-system, sans-serif',
      padding: 20,
    },
    card: {
      background: 'rgba(255,255,255,0.04)',
      backdropFilter: 'blur(20px)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 20,
      padding: '40px 36px',
      width: '100%',
      maxWidth: 420,
      boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
    },
    logo: {
      width: 48,
      height: 48,
      borderRadius: 14,
      background: 'linear-gradient(135deg,#2563eb,#06b6d4)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontWeight: 800,
      fontSize: 20,
      color: '#fff',
      margin: '0 auto 16px',
    },
    title: {
      fontSize: 24,
      fontWeight: 700,
      color: '#f1f5f9',
      textAlign: 'center',
      marginBottom: 4,
    },
    sub: {
      fontSize: 13,
      color: '#64748b',
      textAlign: 'center',
      marginBottom: 28,
    },
    input: {
      width: '100%',
      padding: '12px 14px',
      background: 'rgba(255,255,255,0.06)',
      border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 10,
      color: '#f1f5f9',
      fontSize: 14,
      outline: 'none',
      marginBottom: 10,
      boxSizing: 'border-box',
      transition: '.2s',
    },
    btn: {
      width: '100%',
      padding: '12px',
      borderRadius: 10,
      border: 'none',
      background: 'linear-gradient(135deg,#2563eb,#06b6d4)',
      color: '#fff',
      fontSize: 14,
      fontWeight: 600,
      cursor: 'pointer',
      marginBottom: 10,
      transition: '.18s',
    },
    divider: {
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      margin: '16px 0',
      color: '#334155',
      fontSize: 12,
    },
    link: {
      color: '#60a5fa',
      cursor: 'pointer',
      fontSize: 13,
      textDecoration: 'none',
    },
    error: {
      background: 'rgba(239,68,68,0.12)',
      border: '1px solid rgba(239,68,68,0.25)',
      borderRadius: 8,
      padding: '10px 12px',
      color: '#f87171',
      fontSize: 13,
      marginBottom: 12,
    },
    info: {
      background: 'rgba(59,130,246,0.12)',
      border: '1px solid rgba(59,130,246,0.25)',
      borderRadius: 8,
      padding: '10px 12px',
      color: '#93c5fd',
      fontSize: 13,
      marginBottom: 12,
    },
    pwWrap: {
      position: 'relative',
      marginBottom: 10,
    },
    eye: {
      position: 'absolute',
      right: 12,
      top: '50%',
      transform: 'translateY(-50%)',
      background: 'none',
      border: 'none',
      color: '#64748b',
      cursor: 'pointer',
      fontSize: 16,
      padding: 2,
    },
    back: {
      background: 'none',
      border: 'none',
      color: '#64748b',
      cursor: 'pointer',
      fontSize: 13,
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      marginBottom: 16,
    },
    googleWrap: {
      width: '100%',
      marginBottom: 8,
      display: 'flex',
      justifyContent: 'center',
    },
  };

  const DividerLine = () => (
    <div style={S.divider}>
      <div style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.08)' }} />
      <span>or</span>
      <div style={{ flex: 1, height: 1, background: 'rgba(255,255,255,0.08)' }} />
    </div>
  );

  const SocialButtons = () => (
    <div style={S.googleWrap}>
      <GoogleLogin
        onSuccess={handleGoogleSuccess}
        onError={() => setError('Google login failed')}
        theme="filled_black"
        size="large"
        text="continue_with"
        shape="rectangular"
        width="356"
      />
    </div>
  );

  return (
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.logo}>E</div>

        {screen === 'home' && (
          <>
            <div style={S.title}>Welcome to EVA</div>
            <div style={S.sub}>Your AI assistant — powered by RAG + Groq LLM</div>

            {error && <div style={S.error}>⚠️ {error}</div>}
            {info && <div style={S.info}>ℹ️ {info}</div>}

            <SocialButtons />
            <DividerLine />

            <button
              type="button"
              style={S.btn}
              onClick={() => {
                clearMessages();
                setScreen('login');
              }}
            >
              Sign in with Email
            </button>

            <div style={{ textAlign: 'center', fontSize: 13, color: '#64748b' }}>
              No account?{' '}
              <span
                style={S.link}
                onClick={() => {
                  clearMessages();
                  setScreen('signup');
                }}
              >
                Create one
              </span>
            </div>
          </>
        )}

        {screen === 'login' && (
          <>
            <button
              type="button"
              style={S.back}
              onClick={() => {
                clearMessages();
                setScreen('home');
              }}
            >
              ← Back
            </button>

            <div style={S.title}>Sign in</div>
            <div style={S.sub}>Welcome back</div>

            {error && <div style={S.error}>⚠️ {error}</div>}
            {info && <div style={S.info}>ℹ️ {info}</div>}

            <form onSubmit={handleLogin}>
              <input
                style={S.input}
                type="text"
                placeholder="Username or email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
              />

              <div style={S.pwWrap}>
                <input
                  style={{ ...S.input, marginBottom: 0, paddingRight: 40 }}
                  type={showPw ? 'text' : 'password'}
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
                />

                <button
                  type="button"
                  style={S.eye}
                  onClick={() => setShowPw((v) => !v)}
                >
                  {showPw ? '🙈' : '👁️'}
                </button>
              </div>

              <div style={{ textAlign: 'right', marginBottom: 14 }}>
                <span
                  style={S.link}
                  onClick={() => {
                    clearMessages();
                    setScreen('forgot');
                  }}
                >
                  Forgot password?
                </span>
              </div>

              <button
                type="submit"
                style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}
                disabled={loading}
              >
                {loading ? 'Signing in…' : 'Sign in'}
              </button>
            </form>

            <DividerLine />
            <SocialButtons />

            <div style={{ textAlign: 'center', fontSize: 13, color: '#64748b', marginTop: 8 }}>
              No account?{' '}
              <span
                style={S.link}
                onClick={() => {
                  clearMessages();
                  setScreen('signup');
                }}
              >
                Sign up
              </span>
            </div>
          </>
        )}

        {screen === 'signup' && (
          <>
            <button
              type="button"
              style={S.back}
              onClick={() => {
                clearMessages();
                setScreen('home');
              }}
            >
              ← Back
            </button>

            <div style={S.title}>Create account</div>
            <div style={S.sub}>Start using EVA for free</div>

            {error && <div style={S.error}>⚠️ {error}</div>}
            {info && <div style={S.info}>ℹ️ {info}</div>}

            <form onSubmit={handleSignup}>
              <input
                style={S.input}
                type="text"
                placeholder="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
              />

              <input
                style={S.input}
                type="text"
                placeholder="Username or email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
              />

              <div style={S.pwWrap}>
                <input
                  style={{ ...S.input, marginBottom: 0, paddingRight: 40 }}
                  type={showPw ? 'text' : 'password'}
                  placeholder="Password (min 6 chars)"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                  onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
                />

                <button
                  type="button"
                  style={S.eye}
                  onClick={() => setShowPw((v) => !v)}
                >
                  {showPw ? '🙈' : '👁️'}
                </button>
              </div>

              <div style={{ height: 10 }} />

              <button
                type="submit"
                style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}
                disabled={loading}
              >
                {loading ? 'Creating account…' : 'Create account'}
              </button>
            </form>

            <DividerLine />
            <SocialButtons />

            <div style={{ textAlign: 'center', fontSize: 13, color: '#64748b', marginTop: 8 }}>
              Already have an account?{' '}
              <span
                style={S.link}
                onClick={() => {
                  clearMessages();
                  setScreen('login');
                }}
              >
                Sign in
              </span>
            </div>
          </>
        )}

        {screen === 'forgot' && (
          <>
            <button
              type="button"
              style={S.back}
              onClick={() => {
                clearMessages();
                setScreen('login');
              }}
            >
              ← Back
            </button>

            <div style={S.title}>Reset password</div>
            <div style={S.sub}>We'll send a reset link to your email</div>

            {error && <div style={S.error}>⚠️ {error}</div>}
            {info && <div style={S.info}>✅ {info}</div>}

            <form onSubmit={handleForgot}>
              <input
                style={S.input}
                type="text"
                placeholder="Username or email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = 'rgba(255,255,255,0.1)'; }}
              />

              <button
                type="submit"
                style={{ ...S.btn, opacity: loading ? 0.7 : 1 }}
                disabled={loading}
              >
                {loading ? 'Sending…' : 'Send reset link'}
              </button>
            </form>
          </>
        )}

        <div style={{ marginTop: 20, fontSize: 11, color: '#334155', textAlign: 'center' }}>
          By continuing you agree to our Terms of Service &amp; Privacy Policy
        </div>
      </div>
    </div>
  );
}
