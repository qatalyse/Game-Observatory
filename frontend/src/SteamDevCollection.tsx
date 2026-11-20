import { useState } from "react";

export const steamGames = [
  { id: "1671200", name: "Honkai Impact 3rd" },
  { id: "4162040", name: "Zenless Zone Zero" },
  { id: "3513350", name: "Wuthering Waves" },
  { id: "4125930", name: "Punishing Gray Raven" },
  { id: "2064650", name: "Tower of Fantasy" },
  { id: "4508340", name: "Neverness to Everness" },
  { id: "2456740", name: "inZOI" },
  { id: "2320980", name: "Loftia" },
  { id: "413150", name: "Stardew Valley" },
  { id: "1222670", name: "The Sims 4" },
  { id: "47890", name: "The Sims 3" },
  { id: "4025700", name: "Heartopia" },
  { id: "4732690", name: "Arknights: Endfield" },
  { id: "3061570", name: "Persona5: The Phantom X" },
  { id: "3564740", name: "Where Winds Meet" },
  { id: "3092660", name: "Reverse: 1999" },
  { id: "4195600", name: "AFK Journey" },
  { id: "4019220", name: "Dressmaker" },
  { id: "1401590", name: "Disney Dreamlight Valley" },
];

type PlayerResult = {
  app_id: string; title: string; player_count: number | null;
  status: "ok" | "unavailable" | "error"; error_code: string; error: string;
  http_status: number | null; steam_result: number | null; retrieved_at_utc: string;
};
type Collection = {
  status: string; request_count: number; success_count: number;
  completed_at_utc: string; results: PlayerResult[];
};

export default function SteamDevCollection() {
  const [token, setToken] = useState("");
  const [selected, setSelected] = useState(steamGames.map(game => game.id));
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Collection | null>(null);
  const [error, setError] = useState("");

  async function run() {
    setLoading(true); setResult(null); setError("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 55_000);
    try {
      const response = await fetch("/api/dev/steam-collect", {
        method: "POST",
        headers: { "X-Dev-Token": token, "Content-Type": "application/json" },
        body: JSON.stringify({ app_ids: selected }),
        signal: controller.signal,
      });
      let body;
      try { body = await response.json(); }
      catch { throw new Error(`Steam diagnostic returned a non-JSON response (HTTP ${response.status})`); }
      if (!response.ok) throw new Error(body?.error || `Steam diagnostic failed (HTTP ${response.status})`);
      if (!body || !Array.isArray(body.results)) throw new Error("Invalid Steam diagnostic response");
      setResult(body as Collection);
    } catch (err) {
      setError(err instanceof Error && err.name === "AbortError"
        ? "Steam diagnostic timed out. Run it again when ready."
        : err instanceof Error ? err.message : "Steam diagnostic failed");
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  }

  return (
    <section className="panel dev-panel" aria-label="Steam concurrent-player diagnostics">
      <div className="panel-heading">
        <div><h2>Steam · Current players</h2><p>Manual diagnostics for {steamGames.length} selected Steam titles</p></div>
        <span className="panel-status">On demand</span>
      </div>
      <div className="dev-body">
        <p className="dev-note">Current players connected to Steam only. These counts exclude other launchers, platforms and offline players; they are not total game audiences or daily active users.</p>
        <label htmlFor="steam-dev-token">Dev collection token (configured in Vercel)</label>
        <input id="steam-dev-token" type="password" autoComplete="off" value={token}
          disabled={loading} placeholder="Enter token" onChange={event => setToken(event.target.value)} />
        <fieldset className="tracked-games-control steam-games-control" disabled={loading}>
          <legend>Games to check</legend>
          <div className="dev-actions">
            <button type="button" onClick={() => setSelected(steamGames.map(game => game.id))}>Select all games</button>
            <button type="button" onClick={() => setSelected([])}>Clear selection</button>
          </div>
          {steamGames.map(game => <label key={game.id} className="tracked-game-option">
            <input type="checkbox" checked={selected.includes(game.id)}
              onChange={event => setSelected(current => event.target.checked
                ? [...current, game.id] : current.filter(id => id !== game.id))} />
            <span>{game.name} <small>ID {game.id}</small></span>
          </label>)}
          <p className="dev-note">{selected.length} selected · one Steam request per selected game · no automatic refresh</p>
        </fieldset>
        <button className="dev-run" type="button" disabled={!token || !selected.length || loading} onClick={run}>
          {loading ? "Checking Steam…" : "Check selected games"}
        </button>
        <div role="status" aria-live="polite">
          {loading && <p className="dev-note">Requesting current player counts…</p>}
          {result && <p className="dev-note">{result.success_count} of {result.request_count} counts available · {result.status} · completed {result.completed_at_utc} (UTC)</p>}
        </div>
        {error && <p className="dev-error" role="alert">{error}</p>}
        {result && <div className="dev-results">
          <p className="dev-note">Unavailable or failed requests have no count. A reported zero is a successful Steam observation. Results remain a retrieval-time sample until you run another check.</p>
          <div className="dev-table-wrap">
            <table className="dev-table steam-table">
              <caption>Steam concurrent-player diagnostic results</caption>
              <thead><tr><th>Game / Steam App ID</th><th>Current players</th><th>Status / details</th><th>Retrieved at (UTC)</th></tr></thead>
              <tbody>{result.results.map(row => <tr key={row.app_id}>
                <td><a className="apple-store-link" href={`https://store.steampowered.com/app/${row.app_id}/`} target="_blank" rel="noreferrer">{row.title}</a><br /><small>{row.app_id}</small></td>
                <td className="steam-player-count">{row.status === "ok" && row.player_count !== null ? row.player_count.toLocaleString() : "—"}</td>
                <td><strong>{row.status}</strong><br /><small>HTTP {row.http_status ?? "—"} · Steam result {row.steam_result ?? "—"}</small>
                  {row.error && <p className="dev-error">{row.error_code}: {row.error}</p>}</td>
                <td><time dateTime={row.retrieved_at_utc}>{row.retrieved_at_utc}</time></td>
              </tr>)}</tbody>
            </table>
          </div>
          <p className="dev-note">Source: <a className="apple-store-link" href="https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers" target="_blank" rel="noreferrer">Steam Web API · GetNumberOfCurrentPlayers</a>. Unavailable data does not establish a game's release state.</p>
        </div>}
      </div>
    </section>
  );
}
