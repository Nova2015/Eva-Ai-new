import { useMemo, useState } from 'react';
import { apiFetch, authFetch } from '../api';

// EVA Support Center â” Slice 1 (tickets + FAQ + contact).
// Backend: /api/support/* on the eva-ml-service (same host Chat.js uses for RAG).
// NOTE: no status/health widget on this page by design (later slice).
const SUPPORT_API = (process.env.REACT_APP_RAG_API_BASE || 'http://127.0.0.1:7860').replace(/\/+$/, '');

const CATEGORIES = [
  { value: 'bug_report',        label: 'Bug report' },
  { value: 'billing_issue',     label: 'Billing issue' },
  { value: 'feature_request',   label: 'Feature request' },
  { value: 'technical_support', label: 'Technical support' },
  { value: 'account_support',   label: 'Account support' },
];

const STATUS_COLORS = {
  open:        { color: '#60a5fa', bg: 'rgba(96,165,250,.14)' },   // blue
  in_progress: { color: '#f59e0b', bg: 'rgba(245,158,11,.14)' },   // amber
  resolved:    { color: '#22c55e', bg: 'rgba(34,197,94,.14)' },    // green
  closed:      { color: '#9ca3af', bg: 'rgba(156,163,175,.14)' },  // gray
};

const DESC_MIN = 20;
const DESC_MAX = 5000;

const FAQ = [
  {
    q: 'How does EVA answer questions from my documents (RAG)?',
    a: 'Uploaded documents are split into chunks and embedded into a Supabase Postgres database using pgvector. When you ask a question, EVA runs a hybrid search (BM25 keyword matching plus vector similarity), reranks the best chunks, and passes them as context to Groq openai/gpt-oss-120b (with a Gemini fallback), which writes the answer and cites the retrieved sources.',
  },
  {
    q: 'How do I upload files?',
    a: 'Use the Knowledge page (Upload) inside the app. Files are chunked and indexed into your workspace knowledge base, and become searchable in Chat immediately after indexing finishes.',
  },
  {
    q: 'Which file types are supported?',
    a: 'PDF and DOCX are the primary formats (PDFs are parsed with Poppler, with OCR for scanned pages). Plain text and Markdown also work. Spreadsheets and images are not indexed into the knowledge base yet.',
  },
  {
    q: 'Where is my data stored?',
    a: 'Document chunks and their embeddings live in a Supabase Postgres database (pgvector), scoped to your workspace. Chat history and memory are stored in the application database. Code you explicitly execute with the Run button is sent to the Piston execution API.',
  },
  {
    q: 'How does billing work?',
    a: 'EVA is currently in active development and the core features are free to use. If you see a charge you do not recognize or have a billing question, open a ticket with the "Billing issue" category below and we will investigate â” include the email associated with your account.',
  },
];

const card = {
  background: '#12092b',
  border: '1px solid #2d1b5e',
  borderRadius: 14,
  padding: 20,
  marginBottom: 18,
};
const label = { display: 'block', fontSize: 12, fontWeight: 600, color: '#b29dd9', marginBottom: 5 };
const input = {
  width: '100%', boxSizing: 'border-box', padding: '9px 12px', fontSize: 13,
  background: '#0e0820', color: '#f0e8ff', border: '1px solid #2d1b5e',
  borderRadius: 8, outline: 'none',
};
const sectionTitle = { fontSize: 15, fontWeight: 700, color: '#d8b4fe', marginBottom: 12 };

function StatusBadge({ status }) {
  const s = STATUS_COLORS[status] || STATUS_COLORS.closed;
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 999, color: s.color, background: s.bg, border: `1px solid ${s.color}44`, whiteSpace: 'nowrap' }}>
      {String(status || 'unknown').replace('_', ' ')}
    </span>
  );
}

function serverMessage(err) {
  // apiFetch throws Error(detail); detail may be our field-error object stringified upstream.
  return err?.message || 'Request failed';
}

export default function Support() {
  // Contact form state
  const [form, setForm] = useState({ name: '', email: '', subject: '', category: '', description: '' });
  const [submitState, setSubmitState] = useState('idle'); // idle | submitting | success | error
  const [submitMsg, setSubmitMsg] = useState('');
  const [ticketId, setTicketId] = useState('');

  //  My Tickets state
  const [ticketsState, setTicketsState] = useState('idle'); // idle | loading | loaded | error
  const [tickets, setTickets] = useState([]);
  const [ticketsErr, setTicketsErr] = useState('');

  const descLen = form.description.length;
  const descOk = descLen >= DESC_MIN && descLen <= DESC_MAX;
  const formOk = useMemo(
    () => form.name.trim() && form.email.includes('@') && form.subject.trim() && form.category && descOk,
    [form, descOk]
  );

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (submitState === 'submitting') return;
    setSubmitState('submitting');
    setSubmitMsg('');
    try {
      const data = await apiFetch(`${SUPPORT_API}/api/support/ticket`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      // Success ONLY on a real 2xx (apiFetch throws otherwise) â” never optimistic.
      setTicketId(data?.ticket?.id || '');
      setSubmitState('success');
      setForm({ name: '', email: '', subject: '', category: '', description: '' });
    } catch (err) {
      setSubmitState('error');
      setSubmitMsg(serverMessage(err));
    }
  };

  const loadTickets = async () => {
    setTicketsState('loading');
    setTicketsErr('');
    try {
      const data = await authFetch(`${SUPPORT_API}/api/support/tickets`);
      setTickets(Array.isArray(data?.tickets) ? data.tickets : []);
      setTicketsState('loaded');
    } catch (err) {
      setTickets([]);
      setTicketsState('error');
      setTicketsErr(serverMessage(err));
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '8px 4px 40px', color: '#f0e8ff' }}>
      {/* 1  Header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: '#d8b4fe' }}>EVA AI Support</div>
        <div style={{ fontSize: 13, color: '#8b6fc7', marginTop: 4 }}>
          Questions, bugs, or feature ideas â” open a ticket and we'll get back to you by email.
        </div>
      </div>

      {/* 2  Contact form */}
      <div style={card}>
        <div style={sectionTitle}>Open a ticket</div>
        <form onSubmit={submit}>
          <div className="eva-support-grid">
            <div>
              <label style={label} htmlFor="sup-name">Name</label>
              <input id="sup-name" style={input} value={form.name} onChange={set('name')} placeholder="Your name" />
            </div>
            <div>
              <label style={label} htmlFor="sup-email">Email</label>
              <input id="sup-email" style={input} type="email" value={form.email} onChange={set('email')} placeholder="you@example.com" />
            </div>
            <div>
              <label style={label} htmlFor="sup-subject">Subject</label>
              <input id="sup-subject" style={input} value={form.subject} onChange={set('subject')} placeholder="Short summary" />
            </div>
            <div>
              <label style={label} htmlFor="sup-category">Category</label>
              <select id="sup-category" style={{ ...input, appearance: 'auto' }} value={form.category} onChange={set('category')}>
                <option value="">Select a categoryâ”¦</option>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
          </div>

          <div style={{ marginTop: 12 }}>
            <label style={label} htmlFor="sup-desc">Description</label>
            <textarea
              id="sup-desc" rows={6} style={{ ...input, resize: 'vertical' }}
              value={form.description} onChange={set('description')}
              placeholder={`Describe the issue (${DESC_MIN}-${DESC_MAX} characters)â”¦`}
            />
            <div style={{ fontSize: 11, marginTop: 4, color: descOk ? '#8b6fc7' : '#f59e0b' }}>
              {descLen} / {DESC_MAX} characters{descLen > 0 && descLen < DESC_MIN ? ` â”” at least ${DESC_MIN} needed` : ''}
            </div>
          </div>

          <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button
              type="submit"
              disabled={submitState === 'submitting' || !formOk}
              style={{
                padding: '9px 22px', fontSize: 13, fontWeight: 700, borderRadius: 9,
                border: '1px solid rgba(139,92,246,.5)',
                background: submitState === 'submitting' ? 'rgba(124,58,237,.15)' : 'rgba(124,58,237,.35)',
                color: '#e9d5ff', cursor: submitState === 'submitting' || !formOk ? 'not-allowed' : 'pointer',
                opacity: formOk ? 1 : 0.55,
              }}
            >
              {submitState === 'submitting' ? (
                <span>
                  <span style={{ display: 'inline-block', width: 11, height: 11, border: '2px solid #c4b5fd', borderTopColor: 'transparent', borderRadius: '50%', marginRight: 7, verticalAlign: 'middle', animation: 'eva-sup-spin 0.8s linear infinite' }} />
                  Submittingâ”¦
                </span>
              ) : 'Submit ticket'}
            </button>

            {submitState === 'success' && (
              <span style={{ fontSize: 12, color: '#22c55e' }}>
                âœ“ Ticket created â”” ID <code style={{ color: '#a7f3d0' }}>{ticketId}</code>. Keep it for reference.
              </span>
            )}
            {submitState === 'error' && (
              <span style={{ fontSize: 12, color: '#ef4444' }}>âœ— {submitMsg}</span>
            )}
          </div>
        </form>
      </div>

      {/* 3  My Tickets */}
      <div style={card}>
        <div style={sectionTitle}>My tickets</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            type="button" onClick={loadTickets} disabled={ticketsState === 'loading'}
            style={{ padding: '9px 18px', fontSize: 13, fontWeight: 700, borderRadius: 9, border: '1px solid #2d1b5e', background: '#1a0f3a', color: '#d8b4fe', cursor: 'pointer' }}
          >
            {ticketsState === 'loading' ? 'Loading¦' : 'Load my tickets'}
          </button>
          <span style={{ fontSize: 11, color: '#8b6fc7' }}>
            Sign in to view tickets linked to your account.
          </span>
        </div>

        <div style={{ marginTop: 14 }}>
          {ticketsState === 'error' && (
            <div style={{ fontSize: 12, color: '#ef4444' }}>âœ— {ticketsErr}</div>
          )}
          {ticketsState === 'loaded' && tickets.length === 0 && (
            <div style={{ fontSize: 12, color: '#8b6fc7' }}>No tickets found for this email.</div>
          )}
          {ticketsState === 'loaded' && tickets.map((t) => (
            <div key={t.id} style={{ padding: '10px 12px', border: '1px solid #2d1b5e', borderRadius: 10, marginBottom: 8, background: '#0e0820' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f0e8ff' }}>{t.subject}</div>
                <StatusBadge status={t.status} />
              </div>
              <div style={{ fontSize: 11, color: '#8b6fc7', marginTop: 4 }}>
                {CATEGORIES.find((c) => c.value === t.category)?.label || t.category}
                {' Â· '}{t.created_at ? new Date(t.created_at).toLocaleString() : ''}
                {' Â· '}<code style={{ fontSize: 10 }}>{t.id}</code>
              </div>
              <div style={{ fontSize: 12, color: '#cbb8f0', marginTop: 6, whiteSpace: 'pre-wrap' }}>{t.description}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 4  FAQ */}
      <div style={card}>
        <div style={sectionTitle}>Frequently asked questions</div>
        {FAQ.map((f, i) => (
          <details key={i} style={{ borderBottom: i < FAQ.length - 1 ? '1px solid #2d1b5e' : 'none', padding: '10px 2px' }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#e9d5ff' }}>{f.q}</summary>
            <div style={{ fontSize: 12.5, color: '#b29dd9', lineHeight: 1.7, padding: '8px 2px 2px' }}>{f.a}</div>
          </details>
        ))}
      </div>

      {/* 5  Contact card */}
      <div style={card}>
        <div style={sectionTitle}>Contact us directly</div>
        <div style={{ fontSize: 13, color: '#cbb8f0', lineHeight: 2 }}>
          ðŸ“§ <a href="mailto:support@eva-ai.com" style={{ color: '#c084fc' }}>support@eva-ai.com</a><br />
          ðŸ“§ <a href="mailto:evaaidashbord@gmail.com" style={{ color: '#c084fc' }}>evaaidashbord@gmail.com</a>
        </div>
      </div>

      <style>{`
        @keyframes eva-sup-spin { to { transform: rotate(360deg); } }
        .eva-support-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        @media (max-width: 768px) { .eva-support-grid { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}






