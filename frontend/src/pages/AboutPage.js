import PublicFooter from '../components/PublicFooter';
import PublicNavbar from '../components/PublicNavbar';
import '../components/PublicSite.css';

export default function AboutPage() {
  return (
    <div className="eva-public-page">
      <PublicNavbar />
      <section className="eva-public-page-title">
        <h1>About EVA AI</h1>
        <p>EVA AI is a practical workspace for teams that want their AI work to be useful, inspectable, and governed.</p>
      </section>
      <section className="eva-public-section alt">
        <div className="eva-public-grid">
          <article className="eva-public-card"><h3>Built for real workflows</h3><p>Chat, files, tools, history, runs, security, agents, and settings stay organized.</p></article>
          <article className="eva-public-card"><h3>Model-flexible</h3><p>Provider settings support OpenAI, Gemini, Claude, Groq, and local models.</p></article>
          <article className="eva-public-card"><h3>Production-minded</h3><p>Monitoring, usage, cost, and deployment scaffolding are part of the workspace.</p></article>
        </div>
      </section>
      <PublicFooter />
    </div>
  );
}
