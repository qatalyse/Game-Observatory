// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function collection(count = 100, feed = "topgrossingapplications") {
  const discovery = feed === "newapplications";
  return {
    feed_type: feed, genre: "simulation", country: "SG", request_count: 1,
    requested_depth: discovery ? 20 : 100,
    rankings: Array.from({ length: count }, (_, i) => ({
      position: i + 1, position_semantics: discovery ? "feed_order_not_verified_as_rank" : "grossing_chart_rank",
      app_id: String(880000 + i), title: `Simulation Game ${i + 1}`, developer: "Fixture Studio",
      release_date: "", store_url: "", artwork_url: "", price_amount: "", price_currency: "",
      category_id: "7015", category_label: "Simulation",
    })),
    statuses: [{
      feed_type: feed, genre: "simulation", status: discovery || count === 100 ? "ok" : count ? "partial" : "empty",
      returned_count: count, source_count: count, requested_depth: discovery ? 20 : 100,
      category_filter_id: "", http_status: 200, error: "",
      feed_fields: "entry,updated", entry_fields: "id,im:name", source_url: "https://itunes.apple.com/sg/rss/fixture",
    }],
  };
}

async function openApple() {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Apple Markets" }));
  return within(screen.getByRole("region", { name: "Developer Apple RSS diagnostics" }));
}

function mockResponse(data: ReturnType<typeof collection>) {
  const fetch = vi.fn().mockResolvedValue({
    ok: true, status: 200, text: async () => JSON.stringify(data),
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("Apple full Top 100 diagnostics", () => {
  it("has no targeted-ID controls and never fetches on category or market selection", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const panel = await openApple();
    expect(panel.queryAllByRole("checkbox")).toHaveLength(0);
    expect(panel.queryByRole("group", { name: /tracked games/i })).toBeNull();
    expect(panel.queryByPlaceholderText("Numeric App Store ID")).toBeNull();
    expect(panel.getByRole("option", { name: "Action" })).toBeTruthy();
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Category" }), "simulation");
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Market" }), "VN");
    expect(fetch).not.toHaveBeenCalled();
    expect((panel.getByRole("button", { name: "Run Selected Feed Test" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("posts only scope selectors and displays every returned Top 100 row", async () => {
    const fetch = mockResponse(collection());
    const panel = await openApple();
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Category" }), "simulation");
    await userEvent.type(panel.getByLabelText("Dev collection token (configured in Vercel)"), "test-token");
    await userEvent.click(panel.getByRole("button", { name: "Run Selected Feed Test" }));
    const table = await panel.findByRole("table");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("/api/dev/apple-collect");
    expect(options.headers["X-Dev-Token"]).toBe("test-token");
    expect(JSON.parse(options.body)).toEqual({ feed_type: "top-grossing", genre: "simulation", market: "SG" });
    expect(within(table).getAllByRole("row")).toHaveLength(101);
    expect(within(table).getByText("Simulation Game 100")).toBeTruthy();
    expect(panel.getByText("100/100 fetched")).toBeTruthy();
    expect((panel.getByRole("button", { name: "Download CSV" }) as HTMLButtonElement).disabled).toBe(false);
    expect(panel.queryByText(/snapshot retained|fallback|lowest-ranked/i)).toBeNull();
  });

  it("shows partial coverage and keeps result metadata tied to the returned market", async () => {
    const fetch = mockResponse(collection(23));
    const panel = await openApple();
    await userEvent.type(panel.getByLabelText("Dev collection token (configured in Vercel)"), "test-token");
    await userEvent.click(panel.getByRole("button", { name: "Run Selected Feed Test" }));
    const table = await panel.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(24);
    expect(panel.getByText("PARTIAL")).toBeTruthy();
    expect(panel.getByText("23/100 fetched")).toBeTruthy();
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Market" }), "VN");
    expect(panel.getByText("SG APP STORE")).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(panel.queryByText(/fallback/i)).toBeNull();
  });

  it("keeps New Applications at 20 requested while showing all 104 returned entries", async () => {
    mockResponse(collection(104, "newapplications"));
    const panel = await openApple();
    await userEvent.selectOptions(panel.getByRole("combobox", { name: "Feed type" }), "new-applications");
    await userEvent.type(panel.getByLabelText("Dev collection token (configured in Vercel)"), "test-token");
    await userEvent.click(panel.getByRole("button", { name: "Run Selected Feed Test" }));
    const table = await panel.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(105);
    expect(within(table).getByRole("columnheader", { name: "Feed order" })).toBeTruthy();
    expect(panel.getByText(/20 requested; feed may return more/)).toBeTruthy();
    expect(panel.queryByText("104/100 fetched")).toBeNull();
  });
});
