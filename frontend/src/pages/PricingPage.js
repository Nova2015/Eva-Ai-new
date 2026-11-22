import { Link } from 'react-router-dom';
import PublicFooter from '../components/PublicFooter';
import PublicNavbar from '../components/PublicNavbar';
import '../components/PublicSite.css';

const plans = [
  ['Free', '$0', 'Core chat, basic RAG, local workspace previews.'],
  ['Pro', '$19', 'More messages, files, model controls, and agent runs.'],
  ['Team', '$49', 'Team seats, admin controls, shared workflows, and monitoring.'],
  ['Enterprise', 'Custom', 'Advanced governance, usage controls, and deployment support.'],
];

export default function PricingPage() {
  return (
    <div className="eva-public-page">
      <PublicNavbar />
      <section className="eva-public-page-title">
        <h1>Pricing</h1>
        <p>Start small, then scale EVA across models, files, agents, and team workflows.</p>
      </section>
      <section className="eva-public-section alt">
        <div className="eva-public-grid">
          {plans.map(([name, price, body]) => (
            <article key={name} className="eva-public-price">
              <h3>{name}</h3>
              <strong>{price}</strong>
              <p>{body}</p>
              <Link className="eva-public-cta" to="/signup">Choose {name}</Link>
            </article>
          ))}
        </div>
      </section>
      <PublicFooter />
    </div>
  );
}
