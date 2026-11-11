import PublicFooter from '../components/PublicFooter';
import PublicNavbar from '../components/PublicNavbar';
import '../components/PublicSite.css';

export default function ContactPage() {
  return (
    <div className="eva-public-page">
      <PublicNavbar />
      <section className="eva-public-page-title">
        <h1>Contact</h1>
        <p>Talk to the EVA team about rollout, integrations, training data, or production deployment.</p>
      </section>
      <section className="eva-public-section alt">
        <div className="eva-public-grid">
          <article className="eva-public-card"><h3>Email</h3><p>support@eva.ai</p></article>
          <article className="eva-public-card"><h3>Sales</h3><p>sales@eva.ai</p></article>
          <article className="eva-public-card"><h3>Office</h3><p>Remote-first workspace support.</p></article>
        </div>
      </section>
      <PublicFooter />
    </div>
  );
}
