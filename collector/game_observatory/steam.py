"""Manual, storage-independent Steam concurrent-player diagnostics (stdlib only)."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

GAMES = {
    "1671200": "Honkai Impact 3rd",
    "4162040": "Zenless Zone Zero",
    "3513350": "Wuthering Waves",
    "4125930": "Punishing Gray Raven",
    "2064650": "Tower of Fantasy",
    "4508340": "Neverness to Everness",
    "2456740": "inZOI",
    "2320980": "Loftia",
    "413150": "Stardew Valley",
    "1222670": "The Sims 4",
    "47890": "The Sims 3",
    "4025700": "Heartopia",
    "4732690": "Arknights: Endfield",
    "3061570": "Persona5: The Phantom X",
    "3564740": "Where Winds Meet",
    "3092660": "Reverse: 1999",
    "4195600": "AFK Journey",
}
SOURCE = "steam_web_api_get_number_of_current_players"
ENDPOINT = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 65_536


class InvalidResponse(ValueError):
    def __init__(self, message: str, http_status: int):
        super().__init__(message)
        self.http_status = http_status


def validate_app_ids(app_ids: object) -> tuple[str, ...]:
    """Reject invalid/duplicate IDs before making any upstream requests."""
    if not isinstance(app_ids, (list, tuple)) or not 1 <= len(app_ids) <= len(GAMES):
        raise ValueError(f"app_ids must be a non-empty list of at most {len(GAMES)} configured Steam App IDs")
    if any(not isinstance(value, str) or value not in GAMES for value in app_ids):
        raise ValueError("Each app_id must be a configured Steam App ID string")
    if len(set(app_ids)) != len(app_ids):
        raise ValueError("Steam App IDs must be unique")
    return tuple(app_ids)


def player_url(app_id: str) -> str:
    validate_app_ids([app_id])
    return f"{ENDPOINT}?appid={app_id}"


def fetch_json(url: str) -> tuple[object, int]:
    request = Request(url, headers={"User-Agent": "GameObservatory/0.2", "Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise InvalidResponse("Steam response exceeded the 64 KiB diagnostic limit", response.status)
        try:
            return json.loads(raw.decode("utf-8")), response.status
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidResponse("Steam returned invalid JSON or UTF-8", response.status) from exc


def parse_response(payload: object) -> tuple[int | None, int]:
    """Only a successful result with a nonnegative integer count is an observation."""
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise ValueError("Missing Steam response object")
    response = payload["response"]
    result = response.get("result")
    if type(result) is not int:
        raise ValueError("Missing or invalid Steam result code")
    if result != 1:
        return None, result
    count = response.get("player_count")
    if type(count) is not int or count < 0:
        raise ValueError("Missing or invalid Steam player_count")
    return count, result


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def collect(
    app_ids: list[str] | tuple[str, ...] | None = None,
    *,
    fetch: Callable[[str], tuple[object, int]] = fetch_json,
    clock: Callable[[], datetime] = utc_now,
) -> dict:
    """Make one request per selected app, with three workers and no retries/writes.

    Times describe local retrieval, since this API supplies no measurement timestamp.
    An unavailable result does not establish release state or imply zero players.
    """
    selected = validate_app_ids(tuple(GAMES) if app_ids is None else app_ids)
    run_id = uuid4().hex
    stamp = lambda: clock().astimezone(timezone.utc).isoformat()
    started = stamp()

    def collect_one(app_id: str) -> dict:
        row = {
            "snapshot_id": uuid4().hex, "run_id": run_id,
            "app_id": app_id, "title": GAMES[app_id],
            "source": SOURCE, "source_url": player_url(app_id),
            "started_at_utc": stamp(), "retrieved_at_utc": None,
            "player_count": None, "steam_result": None, "http_status": None,
            "status": "error", "error_code": "", "error": "",
        }
        try:
            payload, http_status = fetch(row["source_url"])
            row["http_status"] = http_status
            if http_status != 200:
                row.update(error_code="http_error", error=f"Steam returned HTTP {http_status}")
            else:
                count, result = parse_response(payload)
                row.update(player_count=count, steam_result=result)
                if result == 1:
                    row["status"] = "ok"
                else:
                    row.update(status="unavailable", error_code="steam_unavailable",
                               error=f"Steam did not provide a player count (result {result})")
        except HTTPError as exc:
            row.update(http_status=exc.code, error_code="http_error", error=f"Steam returned HTTP {exc.code}")
        except TimeoutError:
            row.update(error_code="timeout", error="Steam request timed out")
        except URLError as exc:
            timeout = isinstance(exc.reason, TimeoutError)
            row.update(error_code="timeout" if timeout else "network_error",
                       error="Steam request timed out" if timeout else "Could not reach Steam")
        except (ValueError, UnicodeDecodeError) as exc:
            if isinstance(exc, InvalidResponse):
                row["http_status"] = exc.http_status
            row.update(error_code="invalid_response", error=str(exc))
        except OSError:
            row.update(error_code="network_error", error="Could not read the Steam response")
        except Exception:
            # Preserve other games' outcomes and avoid exposing internal exception details.
            row.update(error_code="unexpected_error", error="Unexpected Steam collection failure")
        row["retrieved_at_utc"] = stamp()
        return row

    with ThreadPoolExecutor(max_workers=min(3, len(selected))) as executor:
        results = list(executor.map(collect_one, selected))
    successes = sum(row["status"] == "ok" for row in results)
    return {
        "run_id": run_id, "source": SOURCE,
        "started_at_utc": started, "completed_at_utc": stamp(),
        "status": "ok" if successes == len(results) else "partial" if successes else "no_data",
        "app_ids_selected": list(selected), "request_count": len(selected),
        "success_count": successes, "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-ids", help="Comma-separated configured Steam App IDs; defaults to all configured games")
    args = parser.parse_args(argv)
    try:
        selected = validate_app_ids(args.app_ids.split(",")) if args.app_ids is not None else None
    except ValueError as exc:
        parser.error(str(exc))
    result = collect(selected)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
