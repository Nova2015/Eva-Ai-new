import { Link, NavLink } from 'react-router-dom';
import './PublicSite.css';

export default function PublicNavbar() {
  return (
    <header className="eva-public-nav">
      <Link className="eva-public-brand" to="/">
        <span>E</span>
        EVA AI
      </Link>
      <nav aria-label="Public navigation">
        <NavLink to="/features">Features</NavLink>
        <NavLink to="/pricing">Pricing</NavLink>
        <NavLink to="/about">About</NavLink>
        <NavLink to="/contact">Contact</NavLink>
      </nav>
      <div className="eva-public-nav-actions">
        <Link to="/login">Login</Link>
        <Link className="eva-public-button" to="/signup">Signup</Link>
      </div>
    </header>
  );
}
