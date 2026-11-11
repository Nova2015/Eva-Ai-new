import { useEffect, useMemo, useState } from 'react';

const defaultApi = window.location.hostname === 'localhost'
  ? 'http://127.0.0.1:8000'
  : 'http://127.0.0.1:8000';

const organizationId = 'default-org';

export default function BillingCenter({ API = defaultApi }) {
  const storedUser = (() => {
    try {
      return JSON.parse(localStorage.getItem('aria_user') || '{}');
    } catch {
      return {};
    }
  })();
  const userId = storedUser.email || storedUser.username || storedUser.name || 'user_001';
  const token = localStorage.getItem('aria_token');
  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }), [token]);

  const [plans, setPlans] = useState([]);
  const [billing, setBilling] = useState(emptyBilling());
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadBilling = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ organization_id: organizationId });
      const [plansRes, subscriptionRes, usageRes, invoicesRes] = await Promise.all([
        fetch(`${API}/billing/plans`, { headers }),
        fetch(`${API}/billing/subscription?${params.toString()}`, { headers }),
        fetch(`${API}/billing/usage?${params.toString()}`, { headers }),
        fetch(`${API}/billing/invoices?${params.toString()}`, { headers }),
      ]);
      const [plansJson, subscriptionJson, usageJson, invoicesJson] = await Promise.all([
        plansRes.json().catch(() => ({})),
        subscriptionRes.json().catch(() => ({})),
        usageRes.json().catch(() => ({})),
        invoicesRes.json().catch(() => ({})),
      ]);
      if (!plansRes.ok) throw new Error(plansJson.detail || 'Plans failed');
      if (!subscriptionRes.ok) throw new Error(subscriptionJson.detail || 'Subscription failed');
      if (!usageRes.ok) throw new Error(usageJson.detail || 'Usage failed');
      if (!invoicesRes.ok) throw new Error(invoicesJson.detail || 'Invoices failed');

      setPlans(plansJson.plans || []);
      setBilling({
        subscription: subscriptionJson.subscription || {},
        plan: subscriptionJson.plan || {},
        usage: usageJson.usage || subscriptionJson.usage || emptyBilling().usage,
        entitlements: subscriptionJson.entitlements || {},
      });
      setInvoices(invoicesJson.invoices || []);
    } catch (err) {
      setError(err.message || 'Billing failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBilling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API, userId]);

  const changePlan = async (planId) => {
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const res = await fetch(`${API}/billing/subscription/change`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          organization_id: organizationId,
          user_id: userId,
          plan_id: planId,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Plan change failed');
      setMessage(`Plan updated to ${json.plan?.name || planId}.`);
      await loadBilling();
    } catch (err) {
      setError(err.message || 'Plan change failed');
    } finally {
      setLoading(false);
    }
  };

  const prepareCheckout = async (planId) => {
    setLoading(true);
    setError('');
    setMessage('');
    try {
      const res = await fetch(`${API}/billing/checkout-session`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          organization_id: organizationId,
          user_id: userId,
          plan_id: planId,
          success_url: `${window.location.origin}/billing?checkout=success`,
          cancel_url: `${window.location.origin}/billing?checkout=cancelled`,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json.detail || 'Checkout failed');
      if (json.checkout?.checkout_url) {
        window.location.href = json.checkout.checkout_url;
        return;
      }
      setMessage(json.checkout?.status === 'stripe_not_configured'
        ? 'Checkout is ready, but Stripe price IDs are not configured yet.'
        : 'Checkout session prepared.');
    } catch (err) {
      setError(err.message || 'Checkout failed');
    } finally {
      setLoading(false);
    }
  };

  const S = styles(loading);
  const plan = billing.plan || {};
  const usage = billing.usage || emptyBilling().usage;
  const entitlements = billing.entitlements || {};
  const totals = usage.totals || {};
  const activePlanId = billing.subscription?.plan_id || plan.id || 'free';
  const tokenPercent = clamp(Number(entitlements.tokens_percent || 0), 0, 100);

  return (
    <div style={S.page}>
      <style>{`
        @media (max-width: 1120px) {
          .billing-grid-2,
          .billing-grid-3,
          .billing-grid-4 { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 720px) {
          .billing-table { min-width: 720px; }
        }
      `}</style>
      <div style={S.shell}>
        <div style={S.header}>
          <div>
            <h1 style={S.title}>Billing Center</h1>
            <div style={S.sub}>Plans, subscription state, invoices, and usage governance for EVA Cloud.</div>
          </div>
          <button type="button" onClick={loadBilling} disabled={loading} style={S.primaryButton}>
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>

        {error && <div style={S.error}>{error}</div>}
        {message && <div style={S.notice}>{message}</div>}

        <div className="billing-grid-4" style={S.grid4}>
          <Metric label="Current Plan" value={plan.name || 'Free'} hint={billing.subscription?.status || 'active'} color="#38bdf8" />
          <Metric label="Tokens Used" value={formatNumber(totals.tokens || 0)} hint={`${formatNumber(entitlements.tokens_remaining || 0)} remaining`} color="#34d399" />
          <Metric label="Agent Run Limit" value={formatNumber(entitlements.monthly_agent_runs || 0)} hint="monthly allowance" color="#fbbf24" />
          <Metric label="Team Seats" value={formatNumber(entitlements.team_members || 1)} hint="included members" color="#a78bfa" />
        </div>

        <div className="billing-grid-2" style={S.grid2}>
          <section style={S.panel}>
            <div style={S.sectionTitle}>Usage Governance</div>
            <div style={S.infoGrid}>
              <InfoRow label="Organization" value={organizationId} />
              <InfoRow label="Billing Period" value={`${formatDate(usage.period_start)} to ${formatDate(usage.period_end)}`} />
              <InfoRow label="Monthly Token Quota" value={formatNumber(entitlements.included_tokens || 0)} />
              <InfoRow label="Usage Events" value={formatNumber(totals.events || 0)} />
            </div>
            <div style={{ marginTop: 16 }}>
              <Progress label="Token usage" value={tokenPercent} color={tokenPercent >= 90 ? '#fb7185' : tokenPercent >= 70 ? '#fbbf24' : '#34d399'} />
            </div>
            <div style={S.governanceBox}>
              <div style={{ ...S.statusDot, background: tokenPercent >= 100 ? '#fb7185' : '#34d399' }} />
              <div>
                <div style={S.strong}>{tokenPercent >= 100 ? 'Quota exceeded' : 'Workspace is within token limits'}</div>
                <div style={S.muted}>
                  EVA can use this entitlement check before expensive agent runs, RAG ingestion, and code workflows.
                </div>
              </div>
            </div>
          </section>

          <section style={S.panel}>
            <div style={S.sectionTitle}>Current Entitlements</div>
            <div style={S.entitlementList}>
              <Entitlement label="Documents" value={formatNumber(entitlements.documents_limit || 0)} S={S} />
              <Entitlement label="Marketplace publications" value={formatNumber(entitlements.marketplace_publications || 0)} S={S} />
              <Entitlement label="Included features" value={(entitlements.features || []).length} S={S} />
            </div>
            <div style={S.featureList}>
              {(entitlements.features || []).map((feature) => (
                <span key={feature} style={S.featurePill}>{feature}</span>
              ))}
              {(entitlements.features || []).length === 0 && <span style={S.muted}>No plan features loaded.</span>}
            </div>
          </section>
        </div>

        <section style={S.panel}>
          <div style={S.sectionHeader}>
            <div>
              <div style={S.sectionTitle}>Plans</div>
              <div style={S.muted}>Switch plans locally now; Stripe checkout is prepared for production price IDs.</div>
            </div>
          </div>
          <div className="billing-grid-4" style={S.planGrid}>
            {plans.map((item) => {
              const current = item.id === activePlanId;
              return (
                <div key={item.id} style={{ ...S.planCard, ...(current ? S.activePlanCard : {}) }}>
                  <div style={S.planTop}>
                    <div>
                      <div style={S.planName}>{item.name}</div>
                      <div style={S.price}>${formatNumber(item.price_monthly_usd || 0)}<span style={S.priceSuffix}>/mo</span></div>
                    </div>
                    {current && <span style={S.currentBadge}>Current</span>}
                  </div>
                  <div style={S.planMeta}>
                    <InfoRow label="Tokens" value={formatNumber(item.included_tokens || 0)} compact />
                    <InfoRow label="Agent runs" value={formatNumber(item.monthly_agent_runs || 0)} compact />
                    <InfoRow label="Documents" value={formatNumber(item.documents_limit || 0)} compact />
                    <InfoRow label="Members" value={formatNumber(item.team_members || 1)} compact />
                  </div>
                  <div style={S.planFeatures}>
                    {(item.features || []).slice(0, 5).map((feature) => (
                      <div key={feature} style={S.featureLine}>{feature}</div>
                    ))}
                  </div>
                  <div style={S.planActions}>
                    <button
                      type="button"
                      onClick={() => changePlan(item.id)}
                      disabled={loading || current}
                      style={{ ...S.smallButton, ...(current ? S.disabledButton : {}) }}
                    >
                      {current ? 'Active' : 'Switch Plan'}
                    </button>
                    {!current && (
                      <button type="button" onClick={() => prepareCheckout(item.id)} disabled={loading} style={S.linkButton}>
                        Checkout
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <div className="billing-grid-2" style={S.grid2}>
          <section style={S.panel}>
            <div style={S.sectionTitle}>Usage by Feature</div>
            <div style={{ overflowX: 'auto' }}>
              <table className="billing-table" style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Feature</th>
                    <th style={S.th}>Events</th>
                    <th style={S.th}>Quantity</th>
                    <th style={S.th}>Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {(usage.by_feature || []).length === 0 ? (
                    <tr><td colSpan={4} style={S.emptyCell}>No usage events yet.</td></tr>
                  ) : (usage.by_feature || []).map((row) => (
                    <tr key={row.feature}>
                      <td style={S.td}>{row.feature}</td>
                      <td style={S.td}>{formatNumber(row.events || 0)}</td>
                      <td style={S.td}>{formatNumber(row.quantity || 0)}</td>
                      <td style={S.td}>{formatNumber(row.tokens || 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={S.panel}>
            <div style={S.sectionTitle}>Invoices</div>
            <div style={{ overflowX: 'auto' }}>
              <table className="billing-table" style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Invoice</th>
                    <th style={S.th}>Amount</th>
                    <th style={S.th}>Status</th>
                    <th style={S.th}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.length === 0 ? (
                    <tr><td colSpan={4} style={S.emptyCell}>No invoices yet.</td></tr>
                  ) : invoices.map((invoice) => (
                    <tr key={invoice.id}>
                      <td style={S.td}>{invoice.invoice_number}</td>
                      <td style={S.td}>${formatNumber(invoice.amount_usd || 0)}</td>
                      <td style={S.td}><StatusPill status={invoice.status} /></td>
                      <td style={S.td}>{formatDate(invoice.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function emptyBilling() {
  return {
    subscription: {},
    plan: {},
    usage: { totals: {}, by_feature: [], recent: [] },
    entitlements: {},
  };
}

function Metric({ label, value, hint, color }) {
  return (
    <section style={{
      background: '#0f172a',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 16,
      boxShadow: '0 14px 34px rgba(0,0,0,.2)',
    }}>
      <div style={{ width: 30, height: 4, borderRadius: 999, background: color, marginBottom: 12 }} />
      <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 750 }}>{label}</div>
      <div style={{ color: '#f8fafc', fontSize: 24, fontWeight: 900, marginTop: 5 }}>{value}</div>
      {hint && <div style={{ color: '#64748b', fontSize: 11, marginTop: 5 }}>{hint}</div>}
    </section>
  );
}

function InfoRow({ label, value, compact = false }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      gap: 14,
      padding: compact ? '4px 0' : '8px 0',
      borderBottom: compact ? 'none' : '1px solid rgba(148,163,184,.12)',
    }}>
      <span style={{ color: '#94a3b8', fontSize: compact ? 11 : 12 }}>{label}</span>
      <span style={{ color: '#e5e7eb', fontSize: compact ? 11 : 12, fontWeight: 800, textAlign: 'right' }}>{value || '0'}</span>
    </div>
  );
}

function Entitlement({ label, value, S }) {
  return (
    <div style={S.entitlementCard}>
      <div style={S.entitlementValue}>{value}</div>
      <div style={S.muted}>{label}</div>
    </div>
  );
}

function Progress({ label, value, color }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', fontSize: 12, marginBottom: 8 }}>
        <span>{label}</span>
        <span>{value}%</span>
      </div>
      <div style={{ height: 10, borderRadius: 999, background: '#020617', border: '1px solid rgba(148,163,184,.16)', overflow: 'hidden' }}>
        <div style={{ width: `${value}%`, height: '100%', background: color, borderRadius: 999, transition: 'width .25s ease' }} />
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const color = status === 'paid' || status === 'active'
    ? '#34d399'
    : status === 'open'
      ? '#fbbf24'
      : '#94a3b8';
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      border: `1px solid ${color}55`,
      color,
      background: `${color}18`,
      borderRadius: 999,
      padding: '4px 9px',
      fontSize: 11,
      fontWeight: 800,
      textTransform: 'capitalize',
    }}>
      {status || 'draft'}
    </span>
  );
}

function formatNumber(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(number);
}

function formatDate(value) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function styles(loading) {
  return {
    page: {
      minHeight: 'calc(100vh - 52px)',
      background: '#09131c',
      color: '#e5e7eb',
      padding: 22,
      fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
    },
    shell: {
      maxWidth: 1280,
      margin: '0 auto',
      display: 'grid',
      gap: 16,
    },
    header: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 14,
      flexWrap: 'wrap',
    },
    title: {
      margin: 0,
      color: '#f8fafc',
      fontSize: 23,
      fontWeight: 850,
    },
    sub: {
      color: '#94a3b8',
      fontSize: 13,
      marginTop: 4,
    },
    primaryButton: {
      border: '1px solid rgba(56,189,248,.38)',
      borderRadius: 8,
      background: loading ? '#0f172a' : 'linear-gradient(135deg,#0f766e,#2563eb)',
      color: '#fff',
      padding: '10px 14px',
      cursor: loading ? 'not-allowed' : 'pointer',
      fontWeight: 850,
      fontSize: 12,
      opacity: loading ? 0.72 : 1,
    },
    grid4: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    grid2: {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
      gap: 16,
      alignItems: 'start',
    },
    panel: {
      background: '#0f172a',
      border: '1px solid rgba(148,163,184,.18)',
      borderRadius: 8,
      padding: 16,
      boxShadow: '0 16px 36px rgba(0,0,0,.24)',
    },
    sectionHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: 14,
      marginBottom: 14,
    },
    sectionTitle: {
      color: '#f8fafc',
      fontSize: 15,
      fontWeight: 900,
      marginBottom: 10,
    },
    muted: {
      color: '#94a3b8',
      fontSize: 12,
      lineHeight: 1.5,
    },
    strong: {
      color: '#f8fafc',
      fontSize: 13,
      fontWeight: 850,
    },
    infoGrid: {
      display: 'grid',
      gap: 2,
    },
    governanceBox: {
      display: 'grid',
      gridTemplateColumns: 'auto minmax(0, 1fr)',
      gap: 10,
      alignItems: 'flex-start',
      marginTop: 16,
      padding: 12,
      borderRadius: 8,
      background: '#020617',
      border: '1px solid rgba(148,163,184,.14)',
    },
    statusDot: {
      width: 9,
      height: 9,
      borderRadius: '50%',
      marginTop: 4,
    },
    entitlementList: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
      gap: 10,
      marginBottom: 14,
    },
    entitlementCard: {
      background: '#020617',
      border: '1px solid rgba(148,163,184,.14)',
      borderRadius: 8,
      padding: 12,
    },
    entitlementValue: {
      color: '#f8fafc',
      fontSize: 18,
      fontWeight: 900,
      marginBottom: 3,
    },
    featureList: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 8,
    },
    featurePill: {
      border: '1px solid rgba(56,189,248,.24)',
      borderRadius: 999,
      color: '#bae6fd',
      background: 'rgba(8,47,73,.34)',
      padding: '6px 9px',
      fontSize: 11,
      fontWeight: 750,
    },
    planGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 12,
    },
    planCard: {
      background: '#020617',
      border: '1px solid rgba(148,163,184,.16)',
      borderRadius: 8,
      padding: 14,
      display: 'flex',
      flexDirection: 'column',
      gap: 12,
      minHeight: 332,
    },
    activePlanCard: {
      borderColor: 'rgba(56,189,248,.62)',
      boxShadow: '0 0 0 1px rgba(56,189,248,.12)',
    },
    planTop: {
      display: 'flex',
      justifyContent: 'space-between',
      gap: 12,
      alignItems: 'flex-start',
    },
    planName: {
      color: '#f8fafc',
      fontSize: 16,
      fontWeight: 900,
    },
    price: {
      color: '#f8fafc',
      fontSize: 26,
      fontWeight: 950,
      marginTop: 6,
    },
    priceSuffix: {
      color: '#94a3b8',
      fontSize: 12,
      fontWeight: 750,
      marginLeft: 2,
    },
    currentBadge: {
      border: '1px solid rgba(52,211,153,.34)',
      borderRadius: 999,
      color: '#34d399',
      background: 'rgba(6,78,59,.28)',
      padding: '4px 8px',
      fontSize: 10,
      fontWeight: 900,
    },
    planMeta: {
      display: 'grid',
      gap: 1,
      padding: '8px 0',
      borderTop: '1px solid rgba(148,163,184,.12)',
      borderBottom: '1px solid rgba(148,163,184,.12)',
    },
    planFeatures: {
      display: 'grid',
      gap: 7,
      flex: 1,
    },
    featureLine: {
      color: '#cbd5e1',
      fontSize: 12,
      lineHeight: 1.35,
    },
    planActions: {
      display: 'flex',
      gap: 8,
      alignItems: 'center',
      marginTop: 'auto',
    },
    smallButton: {
      border: '1px solid rgba(56,189,248,.35)',
      borderRadius: 8,
      background: '#075985',
      color: '#fff',
      padding: '9px 11px',
      cursor: loading ? 'not-allowed' : 'pointer',
      fontWeight: 850,
      fontSize: 12,
    },
    disabledButton: {
      background: '#111827',
      color: '#64748b',
      borderColor: 'rgba(148,163,184,.16)',
      cursor: 'not-allowed',
    },
    linkButton: {
      border: '1px solid rgba(148,163,184,.2)',
      borderRadius: 8,
      background: '#111827',
      color: '#cbd5e1',
      padding: '9px 11px',
      cursor: loading ? 'not-allowed' : 'pointer',
      fontWeight: 800,
      fontSize: 12,
    },
    table: {
      width: '100%',
      borderCollapse: 'collapse',
      fontSize: 12,
    },
    th: {
      textAlign: 'left',
      color: '#94a3b8',
      fontWeight: 800,
      borderBottom: '1px solid rgba(148,163,184,.16)',
      padding: '10px 8px',
    },
    td: {
      color: '#e5e7eb',
      borderBottom: '1px solid rgba(148,163,184,.08)',
      padding: '10px 8px',
      verticalAlign: 'top',
    },
    emptyCell: {
      color: '#94a3b8',
      textAlign: 'center',
      padding: 22,
    },
    error: {
      border: '1px solid rgba(248,113,113,.32)',
      borderRadius: 8,
      background: 'rgba(127,29,29,.28)',
      color: '#fecaca',
      padding: 12,
      fontSize: 13,
    },
    notice: {
      border: '1px solid rgba(52,211,153,.28)',
      borderRadius: 8,
      background: 'rgba(6,78,59,.24)',
      color: '#bbf7d0',
      padding: 12,
      fontSize: 13,
    },
  };
}

