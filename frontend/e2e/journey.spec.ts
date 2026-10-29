// Against the real backend with SYNTHETIC development data: these tests prove the product works end to end,
// not that any price is real (the UI itself labels every number as mock data).
import { expect, test, type Page } from "@playwright/test";

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

async function answer(page: Page, group: string, option: string) {
  await page.getByRole("group", { name: group, exact: true }).getByRole("radio", { name: option, exact: true }).check();
}

test("customer journey: search, value, save, revisit, compare", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What is your phone really worth?");
  await expect(page.getByText(/no real market prices yet/i)).toBeVisible();
  await page.getByRole("main").getByRole("link", { name: "Value my phone" }).click();

  // Step 1: search by OEM code, keyboard selection
  const combo = page.getByRole("combobox", { name: /phone model/i });
  await combo.fill("SM-G991B");
  await expect(page.getByRole("option", { name: /Samsung Galaxy S21/ })).toBeVisible();
  await combo.press("Enter");
  await expect(combo).toHaveValue("Samsung Galaxy S21");
  await answer(page, "Storage", "128 GB");
  await answer(page, "Where will you sell it?", "India (INR)");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 2
  await answer(page, "Does the phone turn on?", "Yes");
  await answer(page, "Can it be unlocked and used normally?", "Yes");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 3 (conditional touch question)
  await answer(page, "Screen", "Cracked glass");
  await answer(page, "With the crack, do the display and touch still work everywhere?", "Yes, fully");
  await answer(page, "Back and frame", "Light wear");
  await answer(page, "Battery", "Drains fast");
  await answer(page, "Charging", "Charges normally");
  for (const g of ["Cameras", "Speakers and microphones", "Buttons", "Wi-Fi, mobile data and Bluetooth"]) {
    await answer(page, g, "Works");
  }
  await answer(page, "Has it been in water or other liquid?", "No");
  await page.getByLabel(/after a repair/).selectOption("battery_replacement");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 4 → 5
  await expect(page.getByRole("heading", { name: "Check your answers" })).toBeVisible();
  await page.getByRole("button", { name: "Get my valuation" }).click();
  await expect(page.getByRole("heading", { name: /Samsung Galaxy S21 · 128 GB/ })).toBeVisible();
  await expect(page.getByText("Mock data — not a real valuation")).toBeVisible();
  const asIs = page.getByRole("article", { name: /What your Galaxy S21 128 GB is worth/ });
  await expect(asIs.getByText(/^₹[\d,]+$/)).toBeVisible();
  await expect(asIs.getByText(/Based on 12 synthetic \(mock\) observations/)).toBeVisible();
  await expect(page.getByRole("article", { name: /After battery replacement/ })).toBeVisible();
  await expect(page.getByText(/Graded faulty because the battery drains fast/)).toBeVisible();
  const asIsValue = await asIs.getByText(/^₹[\d,]+$/).textContent();

  // Save, then revisit through the saved list
  await page.getByRole("button", { name: "Save this valuation" }).click();
  const link = page.getByRole("link", { name: /\/v\// });
  await expect(link).toBeVisible();
  await page.getByRole("link", { name: "Saved", exact: true }).click();
  await page.getByRole("link", { name: "Open" }).click();
  await expect(page.getByRole("heading", { name: "Saved valuation" })).toBeVisible();
  await expect(page.getByRole("article", { name: /What your Galaxy S21 128 GB is worth/ }).getByText(asIsValue!)).toBeVisible();

  // Compare repair vs sell from the saved valuation
  await page.getByRole("link", { name: "Compare repair or sell" }).click();
  await page.getByLabel(/^Repair cost/).fill("3000");
  await page.getByRole("button", { name: "Compare options" }).click();
  await expect(page.getByRole("row", { name: /Repair, then sell/ })).toBeVisible();
  await expect(page.getByText(/better off|worse off/)).toBeVisible();

  // Delete with confirmation
  await page.getByRole("link", { name: "Saved", exact: true }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Nothing saved yet")).toBeVisible();

  expect(errors).toEqual([]);
});

test("known model without evidence shows an honest unavailable state", async ({ page }) => {
  await page.goto("/value?model=apple-iphone-13");
  await expect(page.getByRole("combobox", { name: /phone model/i })).toHaveValue("Apple iPhone 13");
  await answer(page, "Storage", "256 GB");
  await answer(page, "Where will you sell it?", "United States (USD)");
  await page.getByRole("button", { name: "Continue" }).click();
  await answer(page, "Does the phone turn on?", "No");
  await page.getByRole("button", { name: "Continue" }).click();
  await answer(page, "Screen", "No marks");
  await answer(page, "Back and frame", "Like new");
  await answer(page, "Battery", "Don't know");
  await answer(page, "Charging", "Does not charge");
  await answer(page, "Has it been in water or other liquid?", "Not sure");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Get my valuation" }).click();
  await expect(page.getByRole("heading", { name: "Not enough evidence for an estimate" })).toBeVisible();
  await expect(page.getByText(/\$/)).toHaveCount(0);
});

test("device search, trends empty state and info pages", async ({ page }) => {
  await page.goto("/devices");
  await page.getByLabel(/Search by brand/).fill("pixel");
  await expect(page.getByRole("heading", { name: /Google Pixel/ })).toHaveCount(6);
  await page.getByLabel(/Search by brand/).fill("nokia 3310");
  await expect(page.getByText(/No catalogued phone matches/)).toBeVisible();

  await page.goto("/trends?model=samsung-galaxy-s21");
  await expect(page.getByText("Not enough price history yet")).toBeVisible();

  for (const [path, heading] of [["/methodology", "How valuations work"], ["/data-sources", "Data sources"],
    ["/privacy", "Privacy"], ["/terms", "Terms of use"], ["/no-such-page", "Page not found"]]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
  }
});

test("keyboard users can skip to content and complete step one", async ({ page }) => {
  await page.goto("/value");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  const combo = page.getByRole("combobox", { name: /phone model/i });
  await combo.focus();
  await page.keyboard.type("Pixel 6a");
  await expect(page.getByRole("option", { name: /Pixel 6a/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Catalogued with 128 GB only.")).toBeVisible();
});

test("operator console needs an admin key", async ({ page }) => {
  await page.goto("/admin");
  await page.getByLabel("Admin API key").fill("not-a-key");
  await page.getByRole("button", { name: "Open console" }).click();
  await expect(page.getByText("That key was not accepted.")).toBeVisible();
  await page.getByLabel("Admin API key").fill(process.env.E2E_ADMIN_KEY!);
  await page.getByRole("button", { name: "Open console" }).click();
  await expect(page.getByRole("cell", { name: /Synthetic development data/ })).toBeVisible();
});

test("price comparison shows fixture offers labelled and alternatives", async ({ page }) => {
  await page.goto("/prices?model=samsung-galaxy-s21&storage=128");
  await expect(page.getByText("Fixture offers — not real listings")).toBeVisible();
  const rows = page.getByRole("table", { name: /New offers/ }).getByRole("row");
  await expect(rows).toHaveCount(4); // header + 3 comparable new offers
  await expect(page.getByRole("heading", { name: "Similar, but not the same phone" })).toBeVisible();
  await expect(page.getByText(/Lowest seen/)).toBeVisible(); // fixture history spans several days
});

test("developer creates a key, uses it against the API, and revokes it", async ({ page, request }) => {
  await page.goto("/developers");
  await page.getByRole("button", { name: /Create an account/ }).click();
  await page.getByLabel("Email").fill(`e2e-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("a long enough password");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByLabel("Name").fill("e2e key");
  await page.getByRole("button", { name: "Create key" }).click();
  const shown = page.getByLabel("API key", { exact: true });
  await expect(shown).toBeVisible();
  const key = (await shown.textContent())!.trim();
  expect(key).toMatch(/^fv_/);
  await page.getByRole("button", { name: "I have stored it" }).click();
  await expect(page.getByText(key)).toHaveCount(0);

  const body = { device: { product_id: "samsung-galaxy-s21", storage_gb: 128 }, region: "IN", currency: "INR",
    condition: { grade: "good", faults: [] } };
  const ok = await request.post("/api/v1/valuations", { data: body, headers: { "X-API-Key": key } });
  expect(ok.status()).toBe(201);
  expect(ok.headers()["x-ratelimit-remaining"]).toBeDefined();

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText(/Revoked/)).toBeVisible();
  const denied = await request.post("/api/v1/valuations", { data: body, headers: { "X-API-Key": key } });
  expect(denied.status()).toBe(401);
});

test("security headers are sent with the website", async ({ request }) => {
  const res = await request.get("/");
  expect(res.headers()["content-security-policy"]).toContain("default-src 'self'");
  expect(res.headers()["x-frame-options"]).toBe("DENY");
  const api = await request.post("/v1/valuations", { data: {} });
  expect(api.status()).toBe(401);
});

test("@mobile layout has no horizontal scrolling and a menu", async ({ page }) => {
  for (const path of ["/", "/value", "/devices", "/compare", "/methodology", "/prices?model=samsung-galaxy-s21&storage=128", "/developers", "/watchlist"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
  await page.getByRole("button", { name: "Menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Compare prices" })).toBeVisible();
});
