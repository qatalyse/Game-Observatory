// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import SteamDevCollection, { steamGames } from "./SteamDevCollection";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const collection = {
  status: "partial", request_count: 3, success_count: 1,
  completed_at_utc: "2026-11-18T00:00:00+00:00",
  results: [
    { app_id: "413150", title: "Stardew Valley", player_count: 0, status: "ok", http_status: 200, steam_result: 1, retrieved_at_utc: "2026-11-18T00:00:00+00:00", error: "", error_code: "" },
    { app_id: "2320980", title: "Loftia", player_count: null, status: "unavailable", http_status: 200, steam_result: 42, retrieved_at_utc: "2026-11-18T00:00:00+00:00", error: "Steam did not provide a player count", error_code: "steam_unavailable" },
    { app_id: "2456740", title: "inZOI", player_count: null, status: "error", http_status: null, steam_result: null, retrieved_at_utc: "2026-11-18T00:00:00+00:00", error: "Steam request timed out", error_code: "timeout" },
  ],
};

async function enterToken() {
  await userEvent.type(screen.getByLabelText("Dev collection token (configured in Vercel)"), "secret-token");
}

describe("Steam manual diagnostics", () => {
  it("appears under Steam and never fetches on navigation or selection", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<App />);
    expect(screen.queryByRole("region", { name: "Steam concurrent-player diagnostics" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Steam" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(11);
    expect(screen.getAllByRole<HTMLInputElement>("checkbox").every(input => input.checked)).toBe(true);
    expect((screen.getByRole("button", { name: "Check selected games" }) as HTMLButtonElement).disabled).toBe(true);
    await enterToken();
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect((screen.getByRole("button", { name: "Check selected games" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Select all games" }));
    expect((screen.getByRole("button", { name: "Check selected games" }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("includes both Sims games exactly once in the tracked roster", () => {
    expect(steamGames.filter(game => game.id === "1222670")).toEqual([{ id: "1222670", name: "The Sims 4" }]);
    expect(steamGames.filter(game => game.id === "47890")).toEqual([{ id: "47890", name: "The Sims 3" }]);
    expect(new Set(steamGames.map(game => game.id)).size).toBe(11);
  });

  it("submits only selected IDs with the token in a header and renders zero versus missing counts", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => collection });
    vi.stubGlobal("fetch", fetch);
    render(<SteamDevCollection />);
    await enterToken();
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    for (const title of ["Stardew Valley", "Loftia", "inZOI"]) {
      await userEvent.click(screen.getByRole("checkbox", { name: new RegExp(title) }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Check selected games" }));
    await screen.findByRole("table");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("/api/dev/steam-collect");
    expect(options.method).toBe("POST");
    expect(options.headers["X-Dev-Token"]).toBe("secret-token");
    expect(JSON.parse(options.body)).toEqual({ app_ids: ["413150", "2320980", "2456740"] });
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(rows[0]).getAllByRole("cell")[1].textContent).toBe("0");
    expect(within(rows[1]).getAllByRole("cell")[1].textContent).toBe("—");
    expect(within(rows[2]).getAllByRole("cell")[1].textContent).toBe("—");
    expect(screen.getByText("unavailable")).toBeTruthy();
    expect(screen.getByText(/timeout: Steam request timed out/)).toBeTruthy();
    expect(screen.getByText(/1 of 3 counts available/)).toBeTruthy();
  });

  it("prevents duplicate runs and disables selection until the request finishes", async () => {
    let resolve!: (value: unknown) => void;
    const fetch = vi.fn().mockReturnValue(new Promise(value => { resolve = value; }));
    vi.stubGlobal("fetch", fetch);
    render(<SteamDevCollection />); await enterToken();
    await userEvent.click(screen.getByRole("button", { name: "Check selected games" }));
    expect((screen.getByRole("button", { name: "Checking Steam…" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("group", { name: "Games to check" }) as HTMLFieldSetElement).disabled).toBe(true);
    expect(JSON.parse(fetch.mock.calls[0][1].body).app_ids).toEqual(steamGames.map(game => game.id));
    resolve({ ok: true, json: async () => collection });
    await screen.findByRole("table");
    expect((screen.getByRole("button", { name: "Check selected games" }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ ok: false, status: 401, json: async () => ({ error: "Invalid dev token" }) }, "Invalid dev token"],
    [{ ok: false, status: 502, json: async () => { throw new Error(); } }, "non-JSON response (HTTP 502)"],
    [{ ok: true, json: async () => ({}) }, "Invalid Steam diagnostic response"],
  ])("shows endpoint errors without keeping stale results", async (response, message) => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => collection }).mockResolvedValueOnce(response);
    vi.stubGlobal("fetch", fetch);
    render(<SteamDevCollection />); await enterToken();
    await userEvent.click(screen.getByRole("button", { name: "Check selected games" }));
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "Check selected games" }));
    expect((await screen.findByRole("alert")).textContent).toContain(message);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows a network failure and permits a manual retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network failed")));
    render(<SteamDevCollection />); await enterToken();
    await userEvent.click(screen.getByRole("button", { name: "Check selected games" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Network failed");
    await waitFor(() => expect((screen.getByRole("button", { name: "Check selected games" }) as HTMLButtonElement).disabled).toBe(false));
  });
});
