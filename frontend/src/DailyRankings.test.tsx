// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("Daily Rankings navigation", () => {
  it("appears between Overview and Steam and opens a dedicated chart placeholder without fetching", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<App />);
    const nav = within(screen.getByRole("navigation", { name: "Dashboard sections" }));
    expect(nav.getAllByRole("button").map(button => button.textContent)).toEqual([
      "Overview", "Daily Rankings", "Steam", "Apple Markets",
    ]);
    await userEvent.click(nav.getByRole("button", { name: "Daily Rankings" }));
    expect(screen.getByRole("heading", { level: 1, name: "Daily Rankings" })).toBeTruthy();
    expect(nav.getByRole("button", { name: "Daily Rankings" }).getAttribute("aria-current")).toBe("page");
    const panel = within(screen.getByRole("region", { name: "Daily rankings dashboard" }));
    expect(panel.getByText("A Tableau chart of daily ranking history will appear here.")).toBeTruthy();
    expect(screen.queryByTitle("Game Observatory - Apple Top Grossing Adventure Rankings")).toBeNull();
    expect(screen.queryByRole("region", { name: "Steam concurrent-player diagnostics" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Developer Apple RSS diagnostics" })).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    await userEvent.click(nav.getByRole("button", { name: "Overview" }));
    expect(screen.getByRole("region", { name: "Tableau Public dashboard" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Daily rankings dashboard" })).toBeNull();
  });

  it("remains available in the existing embed mode", async () => {
    window.history.replaceState({}, "", "/?embed=true");
    render(<App />);
    expect(screen.queryByRole("banner")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Daily Rankings" }));
    expect(screen.getByRole("region", { name: "Daily rankings dashboard" })).toBeTruthy();
  });
});
