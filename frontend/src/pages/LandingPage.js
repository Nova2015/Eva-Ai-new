import { Link } from 'react-router-dom';
import { useEffect } from 'react';
import PublicFooter from '../components/PublicFooter';
import PublicNavbar from '../components/PublicNavbar';
import '../components/PublicSite.css';

const features = [
  ['Multi-model AI', 'Route EVA across OpenAI, Gemini, Claude, Groq, and local models from one settings surface.'],
  ['Knowledge base', 'Upload files, tune retrieval, rebuild indexes, and train domain datasets for RAG.'],
  ['Agent Studio', 'Create governed agents with tools, workflows, approvals, run history, and JSON exports.'],
  ['Security center', 'Use masked secrets, session controls, activity logs, and security export workflows.'],
  ['Run monitoring', 'Track health, usage, cost, latency, logs, and production readiness from developer settings.'],
  ['Team workspace', 'Invite members, assign roles, manage limits, and prepare billing governance.'],
];

export default function LandingPage({ focus }) {
  useEffect(() => {
    if (focus === 'features') {
      window.requestAnimationFrame(() => document.getElementById('features')?.scrollIntoView({ block: 'start' }));
    }
  }, [focus]);

  return (
    <div className="eva-public-page">
      <PublicNavbar />
      <section className="eva-public-hero">
        <div className="eva-public-hero-content">
          <p className="eva-public-kicker">AI workspace for builders</p>
          <h1>EVA AI</h1>
          <p>Chat, RAG, agents, model settings, security, monitoring, billing, and team workflows in one clean workspace.</p>
          <div className="eva-public-actions">
            <Link className="eva-public-cta" to="/app">Open EVA</Link>
            <Link className="eva-public-ghost" to="/pricing">View pricing</Link>
          </div>
        </div>
      </section>

      <section id="features" className="eva-public-section alt">
        <h2>Features</h2>
        <div className="eva-public-grid">
          {features.map(([title, body]) => (
            <article key={title} className="eva-public-card">
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="eva-public-section">
        <h2>Product Screenshot</h2>
        <div className="eva-public-shot" role="img" aria-label="EVA AI product workspace preview" />
      </section>

      <section className="eva-public-section alt">
        <h2>Teams use EVA for</h2>
        <div className="eva-public-grid">
          {['Answering from documents', 'Building governed agents', 'Monitoring AI cost'].map((item) => (
            <article key={item} className="eva-public-card">
              <h3>{item}</h3>
              <p>Placeholder testimonial: EVA keeps the workflow focused, inspectable, and ready for production use.</p>
            </article>
          ))}
        </div>
      </section>

      <section className="eva-public-section">
        <h2>FAQ</h2>
        <div className="eva-public-grid">
          <article className="eva-public-faq"><h3>Can I use my own model keys?</h3><p>Yes. Keys are saved through settings and returned masked.</p></article>
          <article className="eva-public-faq"><h3>Does EVA support RAG?</h3><p>Yes. Knowledge base and domain training controls are included.</p></article>
          <article className="eva-public-faq"><h3>Can teams collaborate?</h3><p>Yes. Team roles, invites, limits, and billing placeholders are ready.</p></article>
        </div>
      </section>
      <PublicFooter />
    </div>
  );
}
