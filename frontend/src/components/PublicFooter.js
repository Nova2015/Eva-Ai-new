import { Link } from 'react-router-dom';
import './PublicSite.css';

export default function PublicFooter() {
  return (
    <footer className="eva-public-footer">
      <div>
        <strong>EVA AI</strong>
        <p>AI workspace for chat, RAG, agents, tools, security, and team operations.</p>
      </div>
      <nav aria-label="Footer navigation">
        <Link to="/features">Features</Link>
        <Link to="/pricing">Pricing</Link>
        <Link to="/about">About</Link>
        <Link to="/contact">Contact</Link>
        <Link to="/app">Open app</Link>
      </nav>
    </footer>
  );
}
