import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useMeta } from "../meta";

const NAV = [
  { to: "/value", label: "Value my phone" },
  { to: "/prices", label: "Compare prices" },
  { to: "/compare", label: "Repair or sell" },
  { to: "/trends", label: "Trends" },
  { to: "/watchlist", label: "Watchlist" },
  { to: "/saved", label: "Saved" },
  { to: "/developers", label: "Developers" },
];

function DataBanner() {
  const { data: meta } = useMeta();
  if (!meta || meta.data_status === "real") return null;
  return (
    <div className="mock-banner" role="note">
      <div className="container">
        {meta.data_status === "estimated" ? (
          <>
            <strong>Estimated prices:</strong> FlipValue doesn't have enough real sales yet, so values and store prices
            are rough estimates, labelled “Estimate” wherever they appear. <Link to="/data-sources">How they're made</Link>
          </>
        ) : meta.data_status === "mock_only" ? (
          <>
            <strong>Development preview:</strong> FlipValue has no real market prices yet. Every number on this site
            comes from synthetic (mock) data and is labelled as such. <Link to="/data-sources">Why?</Link>
          </>
        ) : (
          <>
            <strong>No price data yet.</strong> Valuations will show as unavailable until real market data is
            imported. <Link to="/data-sources">Learn more</Link>
          </>
        )}
      </div>
    </div>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="container">
          <Link to="/" className="brand">
            <img src="/favicon.svg" alt="" />
            FlipValue
          </Link>
          <button
            type="button"
            className="btn nav-toggle"
            aria-expanded={open}
            aria-controls="site-nav"
            onClick={() => setOpen((o) => !o)}
          >
            Menu
          </button>
          <nav id="site-nav" aria-label="Main" className={`site-nav${open ? " open" : ""}`}>
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <DataBanner />
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container">
          <ul className="footer-links">
            <li><Link to="/about">About</Link></li>
            <li><Link to="/devices">Devices</Link></li>
            <li><Link to="/methodology">Methodology</Link></li>
            <li><Link to="/data-sources">Data sources</Link></li>
            <li><Link to="/privacy">Privacy</Link></li>
            <li><Link to="/terms">Terms</Link></li>
            <li><Link to="/api">API documentation</Link></li>
            <li><Link to="/contact">Contact</Link></li>
          </ul>
          <p>
            FlipValue estimates are not offers to buy and not guarantees. They show what comparable phones sold or
            were listed for, with the evidence behind them.
          </p>
        </div>
      </footer>
    </>
  );
}
