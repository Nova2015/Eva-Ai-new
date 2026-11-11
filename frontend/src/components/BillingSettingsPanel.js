import { useCallback, useEffect, useState } from 'react';
import { ButtonRow, Panel, SettingRow, TextInput, Toggle, settingsRequest } from './SettingsPanelPrimitives';
import './BillingSettingsPanel.css';

export default function BillingSettingsPanel({ API }) {
  const [plans, setPlans] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [usage, setUsage] = useState({});
  const [invoices, setInvoices] = useState([]);
  const [yearly, setYearly] = useState(false);
  const [billingEmail, setBillingEmail] = useState(localStorage.getItem('eva_billing_email') || '');
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    const [plansData, subData, usageData, invoiceData] = await Promise.all([
      settingsRequest(API, '/billing/plans'),
      settingsRequest(API, '/billing/subscription'),
      settingsRequest(API, '/billing/usage'),
      settingsRequest(API, '/billing/invoices'),
    ]);
    setPlans(plansData.plans || []);
    setSubscription(subData.subscription || null);
    setUsage(usageData.usage || {});
    setInvoices(invoiceData.invoices || []);
  }, [API]);

  useEffect(() => {
    load().catch((error) => setStatus(error.message));
  }, [load]);

  const subscribe = async (plan_id) => {
    await settingsRequest(API, '/billing/subscribe', { method: 'POST', body: JSON.stringify({ plan_id, interval: yearly ? 'yearly' : 'monthly' }) });
    setStatus(`Plan changed to ${plan_id}`);
    await load();
  };

  const cancel = async () => {
    if (!window.confirm('Cancel subscription at period end?')) return;
    await settingsRequest(API, '/billing/cancel', { method: 'POST', body: JSON.stringify({}) });
    setStatus('Cancellation scheduled');
    await load();
  };

  const saveContact = () => {
    localStorage.setItem('eva_billing_email', billingEmail);
    setStatus('Billing contact saved');
  };

  return (
    <>
      <Panel title="Current Plan" subtitle="Subscription and usage controls.">
        <div className="eva-dev-score-grid">
          <div className="eva-dev-score"><span>Plan</span><strong>{subscription?.plan_id || 'free'}</strong></div>
          <div className="eva-dev-score"><span>Status</span><strong>{subscription?.status || 'active'}</strong></div>
          <div className="eva-dev-score"><span>Tokens</span><strong>{usage?.totals?.tokens || 0}</strong></div>
          <div className="eva-dev-score"><span>Messages</span><strong>{usage?.totals?.events || 0}</strong></div>
        </div>
        <SettingRow title="Monthly/yearly billing" detail="Switch pricing display interval.">
          <Toggle checked={yearly} onChange={setYearly} />
        </SettingRow>
      </Panel>

      <Panel title="Plans">
        <div className="eva-billing-plans">
          {plans.map((plan) => (
            <div key={plan.id} className="eva-billing-plan">
              <h4>{plan.name}</h4>
              <strong>${yearly ? Math.round((plan.price_monthly_usd || 0) * 10) : plan.price_monthly_usd || 0}</strong>
              <span>{yearly ? 'per year' : 'per month'}</span>
              <button type="button" className="eva-settings-button primary" onClick={() => subscribe(plan.id)}>Upgrade</button>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Payment + Contact" subtitle="Payment method is a provider placeholder until Stripe is configured.">
        <SettingRow title="Payment method"><input className="eva-settings-input" value="Stripe placeholder" readOnly /></SettingRow>
        <SettingRow title="Billing contact email"><TextInput value={billingEmail} onChange={setBillingEmail} /></SettingRow>
        <ButtonRow status={status}>
          <button type="button" className="eva-settings-button danger" onClick={cancel}>Cancel subscription</button>
          <button type="button" className="eva-settings-button primary" onClick={saveContact}>Save billing</button>
        </ButtonRow>
      </Panel>

      <Panel title="Invoice History">
        <div className="eva-settings-table">
          {invoices.map((invoice) => (
            <div key={invoice.id} className="eva-settings-table-row">
              <span>{invoice.invoice_number}</span>
              <span>${invoice.amount_usd}</span>
              <span>{invoice.status}</span>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}
