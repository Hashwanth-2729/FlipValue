import { Link } from "react-router-dom";

import { api } from "../api";
import { EvidenceBadge, Loading } from "../components/ui";
import { useAsync, usePageTitle } from "../hooks";
import { useMeta } from "../meta";

export function HomePage() {
  const titleRef = usePageTitle("What is your phone really worth?");
  const { data: meta } = useMeta();
  const catalogue = useAsync(() => api.catalogue(), []);
  const brands = [...new Set((catalogue.data ?? []).map((m) => m.manufacturer))];

  return (
    <div className="container">
      <section className="hero">
        <p className="eyebrow">Independent phone resale values · India and US</p>
        <h1 ref={titleRef} tabIndex={-1}>What is your phone really worth?</h1>
        <p className="lead">
          FlipValue estimates a used phone's resale value from recent prices of the same model, storage and condition —
          and tells you plainly when there isn't enough evidence to say.
        </p>
        {meta?.data_status === "mock_only" && (
          <p className="notice mock" style={{ maxWidth: "60ch" }}>
            <strong>Preview with mock data.</strong> Real market prices are not connected yet, so every estimate you see
            here is labelled as synthetic.
          </p>
        )}
        <div className="row">
          <Link to="/value" className="btn primary">Value my phone</Link>
          <Link to="/methodology" className="btn">How valuations work</Link>
        </div>
      </section>

      <section aria-labelledby="how">
        <h2 id="how">How it works</h2>
        <ol className="steps-preview">
          <li><strong>Pick your phone.</strong><br />Search by name or model code. We only value catalogued models.</li>
          <li><strong>Describe its condition.</strong><br />A few plain questions; extra ones only when they matter.</li>
          <li><strong>See the evidence.</strong><br />A middle price, a range, how many prices it rests on, and how recent.</li>
          <li><strong>Decide.</strong><br />Compare selling as-is with repairing first, using your own repair quote.</li>
        </ol>
      </section>

      <section aria-labelledby="features">
        <h2 id="features">What you get</h2>
        <div className="grid">
          <div className="card"><h3>As-is and after-repair values</h3><p className="muted">Separate estimates, each from its own comparable prices. A repair is never assumed to add its cost to the value.</p></div>
          <div className="card"><h3>Ranges, not false precision</h3><p className="muted">Every estimate shows its range, the number of prices behind it and how fresh they are.</p></div>
          <div className="card"><h3>Repair-or-sell calculator</h3><p className="muted">Net proceeds after fees and repair costs, with every assumption on screen.</p></div>
          <div className="card"><h3>No account needed</h3><p className="muted">Value a phone as a guest. Save a private link if you want to come back to it.</p></div>
        </div>
      </section>

      <section aria-labelledby="coverage">
        <h2 id="coverage">Phones we know</h2>
        {catalogue.loading && <Loading label="Loading catalogue" lines={2} />}
        {catalogue.data && (
          <>
            <p className="muted">
              {catalogue.data.length} models from {brands.join(", ")}. Knowing a model is not the same as having price
              evidence for it — each shows its evidence status:
            </p>
            <div className="grid">
              {catalogue.data.map((m) => (
                <Link key={m.id} to={`/value?model=${m.id}`} className="card" style={{ textDecoration: "none", color: "inherit" }}>
                  <strong>{m.manufacturer} {m.name}</strong>
                  <div className="row small" style={{ marginTop: 8, gap: 6 }}>
                    <EvidenceBadge status={m.evidence.IN} region="IN" />
                    <EvidenceBadge status={m.evidence.US} region="US" />
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="trust" className="grid">
        <div>
          <h2 id="trust">Evidence and uncertainty</h2>
          <p>
            An estimate is the median of comparable prices; the range covers the middle of them. Completed sales are
            preferred. Asking prices are used only when sales are scarce, and are labelled. Different kinds of price are
            never averaged together. Fewer than three recent comparable prices means no estimate.
          </p>
          <Link to="/methodology">Read the methodology</Link>
        </div>
        <div>
          <h2>Privacy and security</h2>
          <p>
            No account, name, email, IMEI or serial number is needed. Valuations you save hold only the phone details
            you entered, and can be deleted from this browser. <Link to="/privacy">Privacy notice</Link>
          </p>
        </div>
        <div>
          <h2>Limitations</h2>
          <p>
            Estimates rely on your description; a buyer will inspect the phone. Faults and age don't adjust prices yet
            because there is no evidence for how much they should. FlipValue does not buy phones or estimate repair
            costs. <Link to="/data-sources">Where the data comes from</Link>
          </p>
        </div>
      </section>
    </div>
  );
}
