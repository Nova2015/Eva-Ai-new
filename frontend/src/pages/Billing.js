// EVA Billing — Slice 3: DISPLAY-ONLY pricing/plan page.
// Deliberately contains ZERO network calls: no fetch, no apiFetch, no axios
// import anywhere in this file. No payment processing, no subscription
// endpoints, no usage numbers — paid plans are not launched, and this page
// does not pretend otherwise.

const CONTACT_EMAIL = 'evaaidashboard@gmail.com';

const card = {
  background: '#12092b',
  border: '1px solid #2d1b5e',
  borderRadius: 14,
  padding: 20,
  marginBottom: 18,
};

const PLANS = [
  {
    name: 'Free',
    highlight: false,
    features: ['100 messages/day', 'Basic AI chat', 'Limited RAG'],
    button: { kind: 'current', label: 'Current Plan' },
  },
  {
    name: 'Pro',
    highlight: true,
    // No price shown — pricing is not decided yet. Do not invent one.
    features: ['Unlimited chat', 'Advanced RAG', 'File upload', 'AI coding tools'],
    button: { kind: 'soon', label: 'Coming Soon' },
  },
  {
    name: 'Enterprise',
    highlight: false,
    features: ['Team accounts', 'API access', 'Dedicated support', 'Custom deployment'],
    button: { kind: 'contact', label: 'Contact Us' },
  },
];

function PlanButton({ button }) {
  const base = {
    display: 'inline-block', width: '100%', boxSizing: 'border-box', textAlign: 'center',
    padding: '10px 0', fontSize: 13, fontWeight: 700, borderRadius: 9, marginTop: 16,
  };
  if (button.kind === 'contact') {
    return (
      <a
        href={`mailto:${CONTACT_EMAIL}?subject=EVA%20Enterprise%20inquiry`}
        style={{ ...base, color: '#e9d5ff', background: 'rgba(124,58,237,.35)', border: '1px solid rgba(139,92,246,.5)', textDecoration: 'none', cursor: 'pointer' }}
      >
        {button.label}
      </a>
    );
  }
  if (button.kind === 'current') {
    return (
      <button type="button" disabled style={{ ...base, color: '#22c55e', background: 'rgba(34,197,94,.10)', border: '1px solid rgba(34,197,94,.35)', cursor: 'default' }}>
        ✓ {button.label}
      </button>
    );
  }
  // 'soon'
  return (
    <button type="button" disabled style={{ ...base, color: '#8b6fc7', background: 'rgba(139,92,246,.08)', border: '1px dashed #3d2570', cursor: 'not-allowed' }}>
      {button.label}
    </button>
  );
}

export default function Billing() {
  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '8px 4px 40px', color: '#f0e8ff' }}>
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 22, fontWeight: 800, color: '#d8b4fe' }}>Billing & Plans</div>
        <div style={{ fontSize: 13, color: '#8b6fc7', marginTop: 4 }}>
          Your plan and what's coming next.
        </div>
      </div>

      {/* 1 ── Current Plan */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#d8b4fe' }}>Current plan</div>
          <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 999, color: '#22c55e', background: 'rgba(34,197,94,.12)', border: '1px solid rgba(34,197,94,.35)' }}>
            Free Plan
          </span>
        </div>
        <div style={{ fontSize: 12.5, color: '#8b6fc7', marginTop: 8 }}>Paid plans launching soon.</div>
      </div>

      {/* 2 ── Pricing cards */}
      <div className="eva-billing-grid">
        {PLANS.map((p) => (
          <div
            key={p.name}
            className="eva-billing-card"
            style={{
              ...card,
              marginBottom: 0,
              display: 'flex',
              flexDirection: 'column',
              border: p.highlight ? '1px solid rgba(139,92,246,.55)' : card.border,
            }}
          >
            <div style={{ fontSize: 16, fontWeight: 800, color: p.highlight ? '#c084fc' : '#d8b4fe' }}>{p.name}</div>
            <ul style={{ listStyle: 'none', padding: 0, margin: '14px 0 0', flexGrow: 1 }}>
              {p.features.map((f) => (
                <li key={f} style={{ fontSize: 12.5, color: '#cbb8f0', padding: '4px 0' }}>
                  <span style={{ color: '#8b5cf6', marginRight: 7 }}>•</span>{f}
                </li>
              ))}
            </ul>
            <PlanButton button={p.button} />
          </div>
        ))}
      </div>

      {/* 3 ── Honest empty state */}
      <div style={{ ...card, marginTop: 18, textAlign: 'center', border: '1px dashed #2d1b5e' }}>
        <div style={{ fontSize: 12.5, color: '#8b6fc7' }}>
          Billing history and usage statistics will appear here once paid plans launch.
        </div>
      </div>

      <style>{`
        .eva-billing-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        @media (max-width: 768px) { .eva-billing-grid { grid-template-columns: 1fr; } }
        .eva-billing-card { transition: transform 0.18s ease, box-shadow 0.18s ease; }
        .eva-billing-card:hover { transform: scale(1.02); box-shadow: 0 8px 28px rgba(124, 58, 237, 0.22); }
      `}</style>
    </div>
  );
}
