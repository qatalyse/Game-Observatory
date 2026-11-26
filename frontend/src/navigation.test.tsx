// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("dashboard navigation feature flags", () => {
  it("hides secondary tabs by default while retaining direct URL access", () => {
    vi.stubEnv("VITE_SHOW_STEAM_TAB", "");
    vi.stubEnv("VITE_SHOW_APPLE_MARKETS_TAB", "");
    window.history.replaceState({}, "", "/?section=steam");
    render(<App />);
    expect(screen.getByRole("button", { name: "Overview" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Steam" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Apple Markets" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Steam" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Steam concurrent-player diagnostics" })).toBeTruthy();
  });

  it("shows each secondary tab only when its own flag is enabled", () => {
    vi.stubEnv("VITE_SHOW_STEAM_TAB", "true");
    vi.stubEnv("VITE_SHOW_APPLE_MARKETS_TAB", "");
    window.history.replaceState({}, "", "/");
    const { unmount } = render(<App />);
    expect(screen.getByRole("button", { name: "Steam" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Apple Markets" })).toBeNull();
    unmount();

    vi.stubEnv("VITE_SHOW_STEAM_TAB", "");
    vi.stubEnv("VITE_SHOW_APPLE_MARKETS_TAB", "true");
    render(<App />);
    expect(screen.queryByRole("button", { name: "Steam" })).toBeNull();
    expect(screen.getByRole("button", { name: "Apple Markets" })).toBeTruthy();
  });
});
