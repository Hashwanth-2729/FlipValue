import { Link } from "react-router-dom";

import { API_BASE } from "../api";
import { ErrorState, Loading, Notice } from "../components/ui";
import { day } from "../format";
import { usePageTitle } from "../hooks";
import { useMeta } from "../meta";

function Page({ title, children }: { title: string; children: React.ReactNode }) {
  const ref = usePageTitle(title);
  return (
    <div className="container narrow">
      <h1 ref={ref} tabIndex={-1}>{title}</h1>
      {children}
    </div>
  );
}

export function MethodologyPage() {
  const { data: meta } = useMeta();
  return (
    <Page title="How valuations work">
      <p className="lead">The method is versioned ({meta?.method_version ?? "comparables-v1"}) and the same for the website and partner API.</p>
      <h2>1. Exact comparables only</h2>
      <p>
        An estimate uses prices of the <strong>same model, storage size, market and condition grade</strong>, observed
        within the last {meta?.freshness_days ?? 180} days. Different storage sizes, markets or currencies are never
        mixed, and an unknown model is never mapped to a similar one.
      </p>
      <h2>2. One kind of price at a time</h2>
      <p>
        Completed sales are used first. If there are fewer than three, asking prices from listings are used instead and
        labelled, because sellers often accept less. Trade-in offers are shown separately. Different kinds of price are
        never averaged together.
      </p>
      <h2>3. Median and range</h2>
      <p>
        The estimate is the median (middle) price. With 10 or more prices, the range is the 10th to 90th percentile —
        the middle 80%. With 3–9 prices it is simply the lowest to the highest. With fewer than 3, there is no estimate.
      </p>
      <h2>4. Evidence quality</h2>
      <ul>
        <li><strong>Evidence-backed:</strong> 10 or more completed sales, the newest within 90 days.</li>
        <li><strong>Limited:</strong> fewer prices, older prices, or asking prices only.</li>
      </ul>
      <p>These labels describe the evidence, not a statistical confidence score. FlipValue does not claim an accuracy figure it has not measured.</p>
      <h2>5. Condition</h2>
      <p>
        Your answers map to five grades: Excellent (like new), Good (light wear), Fair (visible scratches or dents), Poor
        (heavy wear or cracked glass, still working) and Faulty (at least one function doesn't work). Any reported
        functional problem makes the phone Faulty; otherwise the worse of screen and body decides.
      </p>
      <h2>6. What is not adjusted, and why</h2>
      <p>
        Specific faults, age and previous repairs do not change the estimate. There is not yet evidence for how much
        each moves prices, and a made-up discount would look precise while being a guess. The grade carries the
        condition. This is disclosed on every result.
      </p>
      <h2>7. After a repair</h2>
      <p>
        The after-repair value uses comparables in the grade the phone should reach: a Faulty phone is assumed to become
        Good; any other grade keeps its grade, because a repair restores function, not cosmetics. It assumes the repair
        is done well and does not include its cost.
      </p>
      <h2>8. Gross prices</h2>
      <p>Values are expected sale prices before selling fees. The <Link to="/compare">repair-or-sell calculator</Link> subtracts fees and costs you enter.</p>
    </Page>
  );
}

const INVESTIGATED = [
  ["eBay Marketplace Insights API (US)", "Completed sales", "Limited-release API; access needs approval from eBay. Not available to this project yet."],
  ["Swappa (US)", "Listings / sales", "No official public API found. Scraping not used."],
  ["Cashify (India)", "Dealer offers", "Terms prohibit systematic retrieval of data. Not used."],
  ["Back Market (US)", "Refurbished retail / buyback", "API is for its sellers only. Not available to this project."],
];

export function DataSourcesPage() {
  const meta = useMeta();
  return (
    <Page title="Data sources">
      <p className="lead">Where FlipValue's prices come from, what kind of price each is, and what is missing.</p>
      {meta.loading && <Loading />}
      {meta.error && <ErrorState error={meta.error} onRetry={meta.reload} what="the source list" />}
      {meta.data && (
        <>
          {meta.data.data_status !== "real" && (
            <Notice tone="mock" title="No real market data is connected yet">
              <p>
                {meta.data.data_status === "mock_only"
                  ? `This deployment uses ${meta.data.mock_observations} synthetic observations for development. They are generated, not collected, and every estimate based on them is labelled “Mock data”. They are refused in production.`
                  : "Valuations show as unavailable until real data is imported."}
              </p>
            </Notice>
          )}
          <h2>Sources in use</h2>
          {meta.data.sources.length === 0 ? <p>None.</p> : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th scope="col">Source</th><th scope="col">Kind of price</th><th scope="col">Markets</th>
                    <th scope="col" className="num">Observations</th><th scope="col">Newest</th></tr>
                </thead>
                <tbody>
                  {meta.data.sources.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name}{s.is_mock && <> <span className="badge mock">Mock</span></>}
                        <div className="small muted">{s.collection_method}</div></td>
                      <td>{s.source_type.replace("_", " ")}{s.verified ? " (verified)" : ""}</td>
                      <td>{s.markets}</td>
                      <td className="num">{s.observation_count}</td>
                      <td>{day(s.newest_observation)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <h2>Sources investigated (October 2026)</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Source</th><th scope="col">Kind of price</th><th scope="col">Status</th></tr></thead>
          <tbody>{INVESTIGATED.map(([a, b, c]) => <tr key={a}><td>{a}</td><td>{b}</td><td>{c}</td></tr>)}</tbody>
        </table>
      </div>
      <h2>Kinds of price</h2>
      <p>
        Completed sales, asking prices, dealer offers, trade-in offers and refurbished retail prices measure different
        things and are stored and used separately. FlipValue only collects data through permitted access — APIs,
        authorised feeds or manual imports of legitimately obtained data — and never bypasses logins, CAPTCHAs or site
        rules. Every observation keeps its source, date and import job.
      </p>
    </Page>
  );
}

export function PrivacyPage() {
  return (
    <Page title="Privacy">
      <Notice tone="warn" title="Draft">
        <p>This notice describes how the software works. It has not been reviewed by a lawyer.</p>
      </Notice>
      <h2>What we collect</h2>
      <ul>
        <li><strong>Valuation answers</strong> (phone model, storage, market, condition answers). No name, email, phone number, IMEI or serial number is asked for.</li>
        <li><strong>Saved valuations:</strong> only if you choose Save — the answers and result, under a random link. Kept up to 365 days unless deleted.</li>
        <li><strong>Request log:</strong> time, path, status and response time, kept 90 days. No IP address, body or identifier.</li>
        <li><strong>Rate limiting:</strong> a salted hash of your IP address, held for about an hour to limit abuse.</li>
      </ul>
      <h2>In your browser</h2>
      <p>The list of your saved valuations and their delete keys is stored in this browser's local storage only. Clearing site data removes it.</p>
      <h2>Deleting</h2>
      <p>Open <Link to="/saved">Saved</Link> and choose Delete. The link stops working for everyone. There are no accounts to delete.</p>
      <h2>No tracking</h2>
      <p>No analytics, advertising cookies or third-party scripts are loaded.</p>
    </Page>
  );
}

export function TermsPage() {
  return (
    <Page title="Terms of use">
      <Notice tone="warn" title="Draft">
        <p>Placeholder terms describing the service honestly. Not legal advice; to be reviewed before public launch.</p>
      </Notice>
      <ul>
        <li>FlipValue estimates are informational. They are not offers to buy, quotes or guarantees of any sale price.</li>
        <li>Estimates depend on your description and on the available price evidence, which may be incomplete.</li>
        <li>Results labelled “Mock data” are synthetic and must not be used for real decisions.</li>
        <li>Automated or abusive use of the website is not permitted; partner access uses the documented API with a key.</li>
      </ul>
    </Page>
  );
}

export function AboutPage() {
  return (
    <Page title="About FlipValue">
      <p className="lead">An independent phone resale intelligence service.</p>
      <p>
        FlipValue answers a simple question honestly: what is this phone realistically worth today, what could it be
        worth after a repair, and does repairing make financial sense? It works on its own, and it also provides
        resale values to partner services such as FixMyTech, a phone diagnosis and repair-estimate app, through a
        documented API.
      </p>
      <p>FlipValue does not buy or sell phones, run a marketplace, or estimate repair costs.</p>
    </Page>
  );
}

export function ApiDocsPage() {
  return (
    <Page title="API documentation">
      <p>
        Partners call <code>POST /v1/valuations</code> with an <code>X-API-Key</code> header. Keys are issued privately by
        the FlipValue operator. The full interactive reference is generated from the code:
      </p>
      <p>
        <a className="btn" href={`${API_BASE}/openapi.json`}>Download openapi.json</a>{" "}
        {API_BASE && <a className="btn" href={`${API_BASE}/docs`}>Open the interactive reference</a>}
      </p>
      {!API_BASE && (
        <p className="small muted">The interactive reference is served at <code>/docs</code> on the API's own address.</p>
      )}
      <h2>Errors</h2>
      <p>All errors use <code>{'{"error": {"code", "message", "request_id"}}'}</code>. Codes include
        <code>unauthorized</code>, <code>unsupported_model</code>, <code>no_data_for_condition</code>,
        <code>validation_error</code>, <code>unsupported_region</code>, <code>unsupported_currency</code>,
        <code>idempotency_key_reused</code>, <code>rate_limited</code> and <code>service_timeout</code>.</p>
      <p>The website itself uses the public <code>/api</code> endpoints, which need no key and are rate-limited per network.</p>
    </Page>
  );
}

export function ContactPage() {
  return (
    <Page title="Contact">
      <p>
        No public contact address has been configured for this deployment yet. The maintainer should publish one here
        before launch. For partner access, ask the FlipValue maintainer directly.
      </p>
    </Page>
  );
}

export function NotFoundPage() {
  return (
    <Page title="Page not found">
      <p>That page does not exist. <Link to="/">Go to the home page</Link>.</p>
    </Page>
  );
}
