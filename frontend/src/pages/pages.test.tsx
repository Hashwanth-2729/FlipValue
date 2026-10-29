import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ValuationResult } from "../components/ValuationResult";
import { META, mockFetch, PIXEL6A, renderAt, S21, VALUATION } from "../test/utils";
import { ComparePage } from "./ComparePage";
import { DevicesPage } from "./DevicesPage";
import { HomePage } from "./HomePage";
import { TrendsPage } from "./TrendsPage";
import { buildRequest, missingFor, ValuePage } from "./ValuePage";

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const base = { "/api/meta": { body: META }, "/api/catalogue": { body: [S21, PIXEL6A] } };

describe("landing page", () => {
  it("explains the product, shows the mock-data banner and real catalogue coverage", async () => {
    mockFetch(base);
    renderAt("/", <HomePage />);

    expect(screen.getByRole("heading", { level: 1, name: /really worth/i })).toBeInTheDocument();
    const cta = screen.getAllByRole("link", { name: "Value my phone" });
    expect(cta.length).toBe(2); // navigation + main call to action
    expect(cta.every((a) => a.getAttribute("href") === "/value")).toBe(true);
    expect(await screen.findByText(/no real market prices yet/i)).toBeInTheDocument();
    expect(await screen.findByText("Samsung Galaxy S21")).toBeInTheDocument();
    expect(screen.getAllByText(/Mock data only/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Methodology" })).toHaveAttribute("href", "/methodology");
  });
});

describe("device search", () => {
  it("shows an honest empty state when nothing matches", async () => {
    mockFetch({ ...base, "/api/catalogue?q=nokia": { body: [] }, "/api/catalogue": { body: [S21] } });
    renderAt("/devices?q=nokia", <DevicesPage />);

    expect(await screen.findByText(/No catalogued phone matches/)).toBeInTheDocument();
    expect(screen.getByText(/never substitutes a similar model/)).toBeInTheDocument();
  });

  it("lists models with storage, codes and evidence per market", async () => {
    mockFetch(base);
    renderAt("/devices", <DevicesPage />);

    const card = (await screen.findByRole("heading", { name: "Samsung Galaxy S21" })).closest("article")!;
    expect(within(card).getByText(/128 GB · 256 GB/)).toBeInTheDocument();
    expect(within(card).getByText(/SM-G991B/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Value this phone" })).toHaveAttribute("href", "/value?model=samsung-galaxy-s21");
  });
});

async function completeWizard(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("combobox", { name: /phone model/i }), "S21");
  await user.click(await screen.findByRole("option", { name: /Samsung Galaxy S21/ }));
  await user.click(screen.getByRole("radio", { name: "128 GB" }));
  await user.click(screen.getByRole("radio", { name: "India (INR)" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(within(screen.getByRole("group", { name: "Does the phone turn on?" })).getByRole("radio", { name: "Yes" }));
  await user.click(within(screen.getByRole("group", { name: /unlocked and used normally/ })).getByRole("radio", { name: "Yes" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("valuation wizard", () => {
  it("requires answers before moving on", async () => {
    mockFetch(base);
    const user = userEvent.setup();
    renderAt("/value", <ValuePage />);

    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText("Choose a phone from the list.")).toBeInTheDocument();
    expect(screen.getByText("Choose where you are selling.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Which phone?" })).toBeInTheDocument();
  });

  it("asks the touch question only for a cracked screen, and skips feature checks if the phone is dead", async () => {
    mockFetch(base);
    const user = userEvent.setup();
    renderAt("/value", <ValuePage />);
    await completeWizard(user);

    const screenGroup = screen.getByRole("group", { name: "Screen" });
    expect(screen.queryByRole("group", { name: /display and touch still work/ })).not.toBeInTheDocument();
    await user.click(within(screenGroup).getByRole("radio", { name: "Cracked glass" }));
    expect(screen.getByRole("group", { name: /display and touch still work/ })).toBeInTheDocument();
    await user.click(within(screenGroup).getByRole("radio", { name: "No marks" }));
    expect(screen.queryByRole("group", { name: /display and touch still work/ })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Cameras" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(within(screen.getByRole("group", { name: "Does the phone turn on?" })).getByRole("radio", { name: "No" }));
    expect(screen.queryByRole("group", { name: /unlocked/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByRole("group", { name: "Cameras" })).not.toBeInTheDocument();
    expect(screen.getByText(/will be valued as faulty/)).toBeInTheDocument();
  });

  it("submits the answers to the backend and renders the result", async () => {
    const calls = mockFetch({ ...base, "POST /api/valuations": { body: VALUATION } });
    const user = userEvent.setup();
    renderAt("/value", <ValuePage />);
    await completeWizard(user);
    for (const [group, answer] of [["Screen", "No marks"], ["Back and frame", "Light wear"], ["Battery", "Drains fast"],
      ["Charging", "Charges normally"], ["Cameras", "Works"], ["Speakers and microphones", "Works"], ["Buttons", "Works"],
      ["Wi-Fi, mobile data and Bluetooth", "Not tested"], ["Has it been in water or other liquid?", "No"]] as const) {
      await user.click(within(screen.getByRole("group", { name: group })).getByRole("radio", { name: answer }));
    }
    await user.selectOptions(screen.getByLabelText(/after a repair/), "battery_replacement");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByRole("heading", { name: "Check your answers" })).toBeInTheDocument();
    expect(screen.getByText("Samsung Galaxy S21")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Get my valuation" }));

    expect(await screen.findByText("₹8,000")).toBeInTheDocument();
    expect(screen.getByText("₹22,000")).toBeInTheDocument();
    expect(screen.getByText("High ₹9,500.50")).toBeInTheDocument();
    expect(screen.getByText(/Mock data — not a real valuation/)).toBeInTheDocument();
    const sent = JSON.parse(String(calls.find((c) => c.url === "/api/valuations")!.init!.body));
    expect(sent).toMatchObject({ device: { model_id: S21.id, storage_gb: 128 }, region: "IN", currency: "INR",
      repair_type: "battery_replacement", assessment: { battery: "drains_fast", connectivity: "not_tested" } });
  });

  it("shows a retry control when the backend is temporarily unavailable", async () => {
    let attempts = 0;
    mockFetch({ ...base, "POST /api/valuations": () => (++attempts === 1
      ? { status: 503, body: { error: { code: "service_timeout", message: "The request took too long.", request_id: "r1" } }, headers: { "Retry-After": "1" } }
      : { body: VALUATION }) });
    const user = userEvent.setup();
    renderAt("/value", <ValuePage />);
    await completeWizard(user);
    for (const [group, answer] of [["Screen", "No marks"], ["Back and frame", "Like new"], ["Battery", "Lasts as expected"],
      ["Charging", "Charges normally"], ["Cameras", "Works"], ["Speakers and microphones", "Works"], ["Buttons", "Works"],
      ["Wi-Fi, mobile data and Bluetooth", "Works"], ["Has it been in water or other liquid?", "No"]] as const) {
      await user.click(within(screen.getByRole("group", { name: group })).getByRole("radio", { name: answer }));
    }
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Get my valuation" }));

    expect(await screen.findByText(/took too long/)).toBeInTheDocument();
    expect(screen.getByText(/Reference: r1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("₹8,000")).toBeInTheDocument();
  });

  it("validation and request building are pure functions", () => {
    const draft = { model: PIXEL6A, storage: 128, region: "US" as const, repair: "" as const,
      a: { powers_on: "no" as const, screen: "perfect" as const, body: "like_new" as const, battery: "unknown" as const,
           charging: "not_charging" as const, liquid_damage: "no" as const } };
    expect(missingFor(1, draft)).toEqual({});
    expect(missingFor(2, draft)).toEqual({});
    const req = buildRequest(draft);
    expect(req.currency).toBe("USD");
    expect(req.assessment).toMatchObject({ usable_normally: "no", cameras: "not_tested", buttons: "not_tested" });
    expect(req).not.toHaveProperty("repair_type");
    expect(missingFor(2, { ...draft, a: { ...draft.a, powers_on: "yes", screen: "cracked" } })).toHaveProperty("screen_touch_works");
  });
});

describe("result view", () => {
  it("shows an unavailable state instead of a number when evidence is missing", () => {
    mockFetch(base);
    renderAt("/", <ValuationResult v={{ ...VALUATION, mock: false, status: "unavailable", as_is: null, after_repair: null,
      repair_type: null, as_is_unavailable_reason: "Not enough recent price evidence for Galaxy S21 128 GB." }} />);

    expect(screen.getByRole("heading", { name: "Not enough evidence for an estimate" })).toBeInTheDocument();
    expect(screen.getByText(/Not enough recent price evidence/)).toBeInTheDocument();
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument();
  });

  it("labels a modelled estimate clearly and leaves out the observation count", () => {
    mockFetch(base);
    const modelled = { value: 39000, low: 36660, high: 41340, range_method: "min_max" as const, basis: "estimate",
      basis_label: "FlipValue modelled estimates", quality: "modelled" as const, observation_count: 3,
      oldest_observation: "2026-10-01", newest_observation: "2026-10-01",
      sources: [{ id: "flipvalue-estimates", name: "FlipValue estimates (modelled)", source_type: "estimate", verified: false, is_mock: false }] };
    renderAt("/", <ValuationResult v={{ ...VALUATION, mock: false, status: "partial", as_is: modelled, repair_type: null,
      after_repair: null, condition: { ...VALUATION.condition, grade: "good", faults: [] } }} />);

    expect(screen.getByText("This is a FlipValue estimate")).toBeInTheDocument();
    expect(screen.getByText("₹39,000")).toBeInTheDocument();
    expect(screen.getByText(/Modelled for Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText("Not based on observed sales of this phone")).toBeInTheDocument();
    expect(screen.queryByText(/Based on 3/)).not.toBeInTheDocument();
  });

  it("marks condition as customer-reported", () => {
    mockFetch(base);
    renderAt("/", <ValuationResult v={VALUATION} />);
    expect(screen.getByText(/has not inspected or tested the phone/)).toBeInTheDocument();
    expect(screen.getByText(/Battery wear/)).toBeInTheDocument();
  });
});

describe("repair or sell", () => {
  it("prefills from a valuation, sends the inputs and shows every scenario with assumptions", async () => {
    const calls = mockFetch({ ...base, "POST /api/decision": { body: {
      currency: "INR", repair_first_advantage: 7600,
      scenarios: [
        { key: "sell_as_is", title: "Sell as-is", available: true, missing: [], gross: 8000, selling_fees: 800, other_costs: 0, net: 7200, explanation: "x" },
        { key: "repair_then_sell", title: "Repair, then sell", available: true, missing: [], gross: 22000, selling_fees: 2200, other_costs: 5000, net: 14800, explanation: "y" },
      ],
      assumptions: ["Repair cost is a verified quote."] } } });
    const user = userEvent.setup();
    renderAt("/compare?currency=INR&as_is=8000&after_repair=22000&repair=battery_replacement", <ComparePage />);

    expect(screen.getByLabelText(/Resale value as it is/)).toHaveValue(8000);
    await user.type(screen.getByLabelText(/^Repair cost/), "5000");
    await user.selectOptions(screen.getByLabelText(/Where does the repair cost/), "verified_quote");
    await user.clear(screen.getByLabelText(/Selling fees/));
    await user.type(screen.getByLabelText(/Selling fees/), "10");
    await user.click(screen.getByRole("button", { name: "Compare options" }));

    expect(await screen.findByText("₹14,800")).toBeInTheDocument();
    expect(screen.getByText(/better off/)).toBeInTheDocument();
    expect(screen.getByText("Repair cost is a verified quote.")).toBeInTheDocument();
    const sent = JSON.parse(String(calls.find((c) => c.url === "/api/decision")!.init!.body));
    expect(sent).toMatchObject({ as_is_value: 8000, after_repair_value: 22000, repair_cost: 5000, selling_fee_pct: 10,
      repair_cost_basis: "verified_quote" });
  });

  it("rejects negative numbers before calling the server", async () => {
    const calls = mockFetch(base);
    const user = userEvent.setup();
    renderAt("/compare", <ComparePage />);
    await user.type(screen.getByLabelText(/^Repair cost/), "-5");
    await user.click(screen.getByRole("button", { name: "Compare options" }));
    expect(screen.getByText("Enter a number of 0 or more.")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/decision")).toBe(false);
  });
});

describe("trends", () => {
  it("explains missing history instead of drawing a chart", async () => {
    mockFetch({ ...base, "/api/trends": { body: { model_id: S21.id, storage_gb: 128, region: "IN", currency: "INR",
      grade: "good", available: false, reason: "Not enough genuine price history.", series: {},
      min_observations_per_month: 3, mock_data_excluded: true } } });
    renderAt(`/trends?model=${S21.id}`, <TrendsPage />);

    expect(await screen.findByText("Not enough price history yet")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Monthly median/ })).not.toBeInTheDocument();
  });

  it("draws the modelled estimate over the years with the overall change", async () => {
    mockFetch({ ...base, "/api/trends": { body: { model_id: S21.id, storage_gb: 128, region: "IN", currency: "INR",
      grade: "good", available: true, reason: null, min_observations_per_month: 3, mock_data_excluded: true,
      series: { estimate: [{ month: "2021-02", median: 56000, count: 3 }, { month: "2023-10", median: 28000, count: 3 },
        { month: "2026-10", median: 15000, count: 3 }] } } } });
    renderAt(`/trends?model=${S21.id}`, <TrendsPage />);

    expect((await screen.findAllByText("FlipValue estimate (modelled, dashed)")).length).toBeGreaterThan(0);
    expect(screen.getByText("-73%")).toBeInTheDocument();
    expect(screen.getByText("5.7 years")).toBeInTheDocument();
  });

  it("draws genuine history with an accessible data table", async () => {
    mockFetch({ ...base, "/api/trends": { body: { model_id: S21.id, storage_gb: 128, region: "IN", currency: "INR",
      grade: "good", available: true, reason: null, min_observations_per_month: 3, mock_data_excluded: true,
      series: { completed_sale: [{ month: "2026-08", median: 21000, count: 4 }, { month: "2026-09", median: 20500, count: 5 },
        { month: "2026-10", median: 20000, count: 3 }] } } } });
    renderAt(`/trends?model=${S21.id}`, <TrendsPage />);

    expect(await screen.findByRole("img", { name: /Monthly median/ })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByText("Show the data"));
    // en-GB abbreviates September as "Sept" in current ICU data, "Sep" in older.
    await waitFor(() => expect(screen.getByRole("cell", { name: /^Sept? 2026$/ })).toBeInTheDocument());
    expect(screen.getByRole("cell", { name: "₹20,500" })).toBeInTheDocument();
  });
});
