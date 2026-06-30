 #!/usr/bin/env python3
"""
Actualiza data.json con marcadores reales usando The Odds API Scores.

No usa API-Football.
No inventa cuotas, lesiones ni alineaciones.
Conserva análisis/cuotas existentes cuando el partido coincide.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_PATH = Path("data.json")
API_HOST = "https://api.the-odds-api.com"
TIMEZONE = "America/Mexico_City"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(value: str | None) -> str:
    text = value or ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def load_data() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {
            "meta": {
                "title": "Radar de partidos — Mundial 2026",
                "timezone": TIMEZONE,
                "lastUpdated": now_iso(),
                "refreshSeconds": 60,
                "sourceNote": "Datos creados con The Odds API Scores.",
            },
            "matches": [],
        }

    with DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    data.setdefault("meta", {})
    data.setdefault("matches", [])
    return data


def save_data(data: dict[str, Any]) -> None:
    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def request_json(url: str, timeout: int = 30) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "tokol-github-actions/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return json.loads(body), headers
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"The Odds API devolvió HTTP {error.code}: {body}") from error


def score_map(event: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in event.get("scores") or []:
        name = normalize(row.get("name"))
        score = row.get("score")
        if name and score is not None:
            result[name] = str(score)
    return result


def score_for_team(scores: dict[str, str], team: str) -> str | None:
    normalized = normalize(team)
    if normalized in scores:
        return scores[normalized]

    # Tolerancia básica por nombres abreviados.
    for key, value in scores.items():
        if normalized in key or key in normalized:
            return value

    return None


def event_score(event: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    scores = score_map(event)
    home = event.get("home_team") or ""
    away = event.get("away_team") or ""

    home_score = score_for_team(scores, home)
    away_score = score_for_team(scores, away)

    if home_score is None or away_score is None:
        return None, home_score, away_score

    return f"{home_score}–{away_score}", home_score, away_score


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def event_status(event: dict[str, Any], score: str | None) -> str:
    if event.get("completed") is True:
        return "Final"

    kickoff = parse_time(event.get("commence_time"))
    if score and kickoff and kickoff <= datetime.now(timezone.utc):
        return "En vivo"

    if kickoff and kickoff <= datetime.now(timezone.utc) and not event.get("completed"):
        return "En vivo"

    return "Próximo"


def team_key(home: str, away: str) -> str:
    return f"{normalize(home)}::{normalize(away)}"


def reverse_team_key(home: str, away: str) -> str:
    return f"{normalize(away)}::{normalize(home)}"


def index_existing(matches: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_teams: dict[str, dict[str, Any]] = {}

    for match in matches:
        if match.get("id"):
            by_id[str(match["id"])] = match

        teams = match.get("teams") or []
        if len(teams) >= 2:
            by_teams[team_key(str(teams[0]), str(teams[1]))] = match
            by_teams[reverse_team_key(str(teams[0]), str(teams[1]))] = match

    return by_id, by_teams


def default_probability(score: str | None) -> dict[str, float | None]:
    return {"home": None, "draw": None, "away": None}


def final_info(event: dict[str, Any], score: str | None) -> dict[str, Any] | None:
    if event.get("completed") is not True:
        return None

    home = event.get("home_team") or "Local"
    away = event.get("away_team") or "Visitante"

    return {
        "summary": f"{home} {score or 'resultado no disponible'} {away}",
        "method": "Final",
        "source": "The Odds API Scores",
    }


def merge_event(existing: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    home = event.get("home_team") or "Local"
    away = event.get("away_team") or "Visitante"
    score, home_score, away_score = event_score(event)
    status = event_status(event, score)
    event_id = str(event.get("id") or team_key(home, away))

    base = dict(existing or {})

    base["id"] = event_id
    base["teams"] = [home, away]
    base["kickoff"] = event.get("commence_time") or base.get("kickoff") or now_iso()
    base["status"] = status
    base["statusCode"] = "FT" if status == "Final" else ("LIVE" if status == "En vivo" else "NS")
    base["statusLong"] = "Final" if status == "Final" else ("En curso" if status == "En vivo" else "Programado")
    base["elapsed"] = None
    base["score"] = score
    base["homeScore"] = home_score
    base["awayScore"] = away_score
    base["completed"] = bool(event.get("completed"))
    base["finalInfo"] = final_info(event, score)
    base["isFinal"] = status == "Final"
    base["updatedAt"] = event.get("last_update") or now_iso()
    base["fixtureSource"] = "The Odds API Scores"
    base["analysisSource"] = "Tokol"

    # Conserva datos ya enriquecidos por otros procesos.
    base.setdefault("classification", "esperar")
    base.setdefault("market", "Resultado / marcador")
    base.setdefault("odds", [])
    base.setdefault("probability", default_probability(score))
    base.setdefault("reasonsFor", [])
    base.setdefault("reasonsAgainst", [])
    base.setdefault("injuries", ["The Odds API Scores no entrega bajas ni lesiones."])
    base.setdefault("lineups", "The Odds API Scores no entrega alineaciones.")
    base.setdefault("form", "Dato no disponible en The Odds API Scores.")
    base.setdefault("marketChange", "Sin movimiento registrado en este actualizador.")

    if not base["reasonsFor"]:
        base["reasonsFor"] = ["Partido actualizado desde The Odds API Scores."]
    if not base["reasonsAgainst"]:
        base["reasonsAgainst"] = ["Verifica cuotas y contexto antes de tomar decisiones."]

    if status == "En vivo":
        base["classification"] = "esperar"
        base["marketChange"] = "Partido en vivo; revisar marcador antes de decidir."
    elif status == "Final":
        base["classification"] = "evitar"
        base["marketChange"] = "Partido finalizado."

    return base


def main() -> int:
    api_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    sport_key = os.environ.get("THE_ODDS_SPORT_KEY", "soccer_fifa_world_cup").strip()

    if not api_key:
        print("Falta THE_ODDS_API_KEY en Actions secrets.", file=sys.stderr)
        return 2

    params = {
        "apiKey": api_key,
        "daysFrom": "3",
        "dateFormat": "iso",
    }

    url = (
        f"{API_HOST}/v4/sports/{urllib.parse.quote(sport_key)}/scores/"
        f"?{urllib.parse.urlencode(params)}"
    )

    events, headers = request_json(url)

    if not isinstance(events, list):
        print(f"Respuesta inesperada de The Odds API: {events}", file=sys.stderr)
        return 3

    data = load_data()
    old_matches: list[dict[str, Any]] = data.get("matches") or []
    by_id, by_teams = index_existing(old_matches)

    updated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for event in events:
        if not isinstance(event, dict):
            continue

        home = event.get("home_team") or ""
        away = event.get("away_team") or ""
        event_id = str(event.get("id") or "")
        existing = by_id.get(event_id) or by_teams.get(team_key(home, away))
        merged = merge_event(existing, event)
        updated.append(merged)
        seen_ids.add(merged["id"])

    # Conserva únicamente partidos anteriores que ya provengan de una fuente real.
    # Esto elimina los partidos de demostración incluidos en la primera versión.
    trusted_sources = {"the odds api scores", "api football"}

    for match in old_matches:
        if str(match.get("id")) in seen_ids:
            continue

        source_name = normalize(str(match.get("fixtureSource") or ""))
        if source_name in trusted_sources:
            updated.append(match)

    def sort_key(match: dict[str, Any]) -> tuple[int, str]:
        rank = {"En vivo": 0, "Próximo": 1, "Final": 2}.get(match.get("status"), 3)
        return rank, str(match.get("kickoff") or "")

    updated.sort(key=sort_key)

    data["matches"] = updated
    data["meta"].update({
        "title": data.get("meta", {}).get("title") or "Radar de partidos — Mundial 2026",
        "timezone": data.get("meta", {}).get("timezone") or TIMEZONE,
        "lastUpdated": now_iso(),
        "refreshSeconds": 60,
        "sourceNote": (
            "Marcadores actualizados con The Odds API Scores. "
            "Cuotas actualizadas con The Odds API Odds. "
            "The Odds API Scores no entrega minuto exacto para todos los deportes."
        ),
    })

    save_data(data)

    remaining = headers.get("x-requests-remaining", "desconocido")
    cost = headers.get("x-requests-last", "desconocido")

    live_count = sum(1 for match in updated if match.get("status") == "En vivo")
    final_count = sum(1 for match in updated if match.get("status") == "Final")

    print(
        f"Marcadores recibidos: {len(events)}; "
        f"partidos guardados: {len(updated)}; "
        f"en vivo: {live_count}; finalizados: {final_count}."
    )
    print(f"Créditos restantes: {remaining} | costo: {cost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
