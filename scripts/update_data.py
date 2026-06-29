#!/usr/bin/env python3
"""
Actualiza data.json con calendario, estado y marcador de API-Football v3.

La versión económica realiza una sola solicitud por ejecución.
No inventa cuotas, probabilidades, lesiones ni alineaciones.
Los análisis manuales existentes se conservan cuando el partido coincide.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

API_URL = "https://v3.football.api-sports.io/fixtures"
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
TIMEZONE = "America/Mexico_City"

TEAM_TRANSLATIONS = {
    "Brazil": "Brasil",
    "Japan": "Japón",
    "Germany": "Alemania",
    "Paraguay": "Paraguay",
    "Netherlands": "Países Bajos",
    "Morocco": "Marruecos",
    "Ivory Coast": "Costa de Marfil",
    "Norway": "Noruega",
    "France": "Francia",
    "Sweden": "Suecia",
    "Mexico": "México",
    "Ecuador": "Ecuador",
    "England": "Inglaterra",
    "DR Congo": "RD del Congo",
    "Belgium": "Bélgica",
    "Senegal": "Senegal",
    "United States": "Estados Unidos",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Spain": "España",
    "Austria": "Austria",
    "Portugal": "Portugal",
    "Croatia": "Croacia",
    "Switzerland": "Suiza",
    "Algeria": "Argelia",
    "Australia": "Australia",
    "Egypt": "Egipto",
    "Argentina": "Argentina",
    "Cape Verde": "Cabo Verde",
    "Colombia": "Colombia",
    "Ghana": "Ghana",
    "Canada": "Canadá",
    "South Africa": "Sudáfrica",
}

LIVE_CODES = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}
FINAL_CODES = {"FT", "AET", "PEN"}
UPCOMING_CODES = {"TBD", "NS"}
DELAYED_CODES = {"PST": "Pospuesto", "CANC": "Cancelado", "ABD": "Suspendido",
                 "INT": "Interrumpido", "SUSP": "Suspendido"}


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn").lower().strip()


def translated_team(name: str) -> str:
    return TEAM_TRANSLATIONS.get(name, name)


def status_label(code: str, long_name: str | None = None) -> str:
    if code in LIVE_CODES:
        return "En vivo"
    if code in FINAL_CODES:
        return "Final"
    if code in UPCOMING_CODES:
        return "Próximo"
    if code in DELAYED_CODES:
        return DELAYED_CODES[code]
    return long_name or code or "Sin estado"


def match_key(home: str, away: str) -> tuple[str, str]:
    return normalize(home), normalize(away)


def load_existing() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {
            "meta": {
                "title": "Radar de partidos — Mundial 2026",
                "timezone": TIMEZONE,
                "refreshSeconds": 60,
            },
            "matches": [],
        }
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def default_match(fixture_id: int, home: str, away: str, kickoff: str,
                  status: str, score: str | None) -> dict[str, Any]:
    classification = "evitar" if status in {"En vivo", "Final", "Cancelado", "Suspendido"} else "esperar"
    return {
        "id": f"api-{fixture_id}",
        "apiFixtureId": fixture_id,
        "source": "API-Football",
        "teams": [home, away],
        "kickoff": kickoff,
        "status": status,
        "score": score,
        "classification": classification,
        "market": "Análisis pendiente",
        "odds": [],
        "probability": {"home": None, "away": None},
        "reasonsFor": [
            "Partido agregado automáticamente desde API-Football."
        ],
        "reasonsAgainst": [
            "Todavía no existen cuotas ni un análisis estadístico verificado para este partido."
        ],
        "injuries": [
            "La opción económica no consulta lesiones automáticamente."
        ],
        "lineups": "La opción económica no consulta alineaciones automáticamente.",
        "form": "Pendiente de análisis.",
        "marketChange": "Sin comparación de cuotas en esta versión."
    }


def main() -> int:
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        print("Falta el secreto API_FOOTBALL_KEY.", file=sys.stderr)
        return 2

    league_id = os.environ.get("API_FOOTBALL_LEAGUE_ID", "1").strip() or "1"
    season = os.environ.get("API_FOOTBALL_SEASON", "2026").strip() or "2026"
    days_ahead = int(os.environ.get("API_FOOTBALL_DAYS_AHEAD", "14"))

    now = datetime.now(ZoneInfo(TIMEZONE))
    params = {
        "league": league_id,
        "season": season,
        "from": (now.date() - timedelta(days=1)).isoformat(),
        "to": (now.date() + timedelta(days=days_ahead)).isoformat(),
        "timezone": TIMEZONE,
    }

    response = requests.get(
        API_URL,
        headers={"x-apisports-key": api_key},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("errors"):
        print(f"API-Football devolvió errores: {payload['errors']}", file=sys.stderr)
        return 3

    fixtures = payload.get("response") or []
    if not fixtures:
        print(
            "La API no devolvió partidos. No se modificó data.json. "
            "Verifica API_FOOTBALL_LEAGUE_ID y API_FOOTBALL_SEASON."
        )
        return 0

    data = load_existing()
    existing_matches = data.get("matches", [])
    existing_by_api = {
        str(m.get("apiFixtureId")): m for m in existing_matches if m.get("apiFixtureId") is not None
    }
    existing_by_teams = {
        match_key(m["teams"][0], m["teams"][1]): m
        for m in existing_matches
        if isinstance(m.get("teams"), list) and len(m["teams"]) == 2
    }

    merged: list[dict[str, Any]] = []

    for item in fixtures:
        fixture = item.get("fixture") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        fixture_id = int(fixture["id"])
        home = translated_team((teams.get("home") or {}).get("name", "Local"))
        away = translated_team((teams.get("away") or {}).get("name", "Visitante"))
        kickoff = fixture.get("date")
        status_info = fixture.get("status") or {}
        status = status_label(status_info.get("short", ""), status_info.get("long"))

        home_goals = goals.get("home")
        away_goals = goals.get("away")
        score = None
        if home_goals is not None and away_goals is not None:
            score = f"{home_goals}–{away_goals}"

        current = (
            existing_by_api.get(str(fixture_id))
            or existing_by_teams.get(match_key(home, away))
            or default_match(fixture_id, home, away, kickoff, status, score)
        )

        current["apiFixtureId"] = fixture_id
        current["source"] = "API-Football"
        current["teams"] = [home, away]
        current["kickoff"] = kickoff
        current["status"] = status
        current["score"] = score

        if status in {"En vivo", "Final", "Cancelado", "Suspendido", "Interrumpido"}:
            current["classification"] = "evitar"
        elif current.get("classification") not in {"considerar", "esperar", "evitar"}:
            current["classification"] = "esperar"

        merged.append(current)

    merged.sort(key=lambda m: m.get("kickoff") or "")
    data["matches"] = merged
    data.setdefault("meta", {})
    data["meta"].update({
        "title": data["meta"].get("title", "Radar de partidos — Mundial 2026"),
        "timezone": TIMEZONE,
        "lastUpdated": now.isoformat(),
        "refreshSeconds": 60,
        "sourceNote": (
            "Calendario, estado y marcador actualizados mediante API-Football. "
            + (
                "Cuotas 1X2 y probabilidades sin margen disponibles mediante The Odds API. "
                if data.get("meta", {}).get("theOddsApi", {}).get("enabled")
                else "Cuotas y probabilidades pendientes de The Odds API. "
            )
            + "Lesiones y alineaciones todavía requieren otra fuente o revisión manual."
        ),
        "apiFootball": {
            "enabled": True,
            "leagueId": league_id,
            "season": season,
            "requestCountThisRun": 1,
        },
    })

    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Actualizados {len(merged)} partidos en {DATA_PATH.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
