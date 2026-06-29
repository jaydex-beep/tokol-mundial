#!/usr/bin/env python3
"""
Actualiza cuotas 1X2 del Mundial en data.json usando The Odds API v4.

Diseño económico:
- 1 región (por defecto eu)
- 1 mercado (h2h)
- 1 crédito por ejecución

La clave se recibe exclusivamente por variable de entorno THE_ODDS_API_KEY.
"""

from __future__ import annotations

import json
import math
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
API_BASE = "https://api.the-odds-api.com/v4"
TIMEZONE = "America/Mexico_City"

# Alias bilingües para empatar The Odds API con los nombres mostrados en la web.
TEAM_ALIASES = {
    "argentina": "argentina",
    "australia": "australia",
    "austria": "austria",
    "belgium": "belgium", "belgica": "belgium",
    "bosnia and herzegovina": "bosnia", "bosnia y herzegovina": "bosnia",
    "brazil": "brazil", "brasil": "brazil",
    "canada": "canada",
    "cape verde": "cape_verde", "cabo verde": "cape_verde",
    "colombia": "colombia",
    "croatia": "croatia", "croacia": "croatia",
    "czechia": "czechia", "czech republic": "czechia", "republica checa": "czechia",
    "curacao": "curacao",
    "haiti": "haiti",
    "iran": "iran",
    "iraq": "iraq", "irak": "iraq",
    "jordan": "jordan", "jordania": "jordan",
    "new zealand": "new_zealand", "nueva zelanda": "new_zealand",
    "panama": "panama",
    "qatar": "qatar", "catar": "qatar",
    "saudi arabia": "saudi_arabia", "arabia saudita": "saudi_arabia",
    "scotland": "scotland", "escocia": "scotland",
    "south korea": "south_korea", "korea republic": "south_korea", "corea del sur": "south_korea",
    "tunisia": "tunisia", "tunez": "tunisia",
    "turkey": "turkey", "turkiye": "turkey", "turquia": "turkey",
    "uruguay": "uruguay",
    "uzbekistan": "uzbekistan", "uzbekistan": "uzbekistan",
    "dr congo": "dr_congo", "democratic republic of the congo": "dr_congo", "rd del congo": "dr_congo",
    "ecuador": "ecuador",
    "egypt": "egypt", "egipto": "egypt",
    "england": "england", "inglaterra": "england",
    "france": "france", "francia": "france",
    "germany": "germany", "alemania": "germany",
    "ghana": "ghana",
    "ivory coast": "ivory_coast", "cote d'ivoire": "ivory_coast", "costa de marfil": "ivory_coast",
    "japan": "japan", "japon": "japan",
    "mexico": "mexico",
    "morocco": "morocco", "marruecos": "morocco",
    "netherlands": "netherlands", "paises bajos": "netherlands", "holland": "netherlands",
    "norway": "norway", "noruega": "norway",
    "paraguay": "paraguay",
    "portugal": "portugal",
    "senegal": "senegal",
    "south africa": "south_africa", "sudafrica": "south_africa",
    "spain": "spain", "espana": "spain",
    "sweden": "sweden", "suecia": "sweden",
    "switzerland": "switzerland", "suiza": "switzerland",
    "united states": "united_states", "usa": "united_states", "estados unidos": "united_states",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join(value.lower().replace("-", " ").split())


def canonical_team(value: str) -> str:
    clean = normalize(value)
    return TEAM_ALIASES.get(clean, clean)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def decimal_to_american(price: float) -> str:
    if price <= 1:
        return "—"
    if price >= 2:
        return f"+{round((price - 1) * 100)}"
    return str(round(-100 / (price - 1)))


def find_h2h_market(bookmaker: dict[str, Any]) -> dict[str, Any] | None:
    for market in bookmaker.get("markets") or []:
        if market.get("key") == "h2h":
            return market
    return None


def outcomes_for_event(event: dict[str, Any], market: dict[str, Any]) -> dict[str, float] | None:
    home_key = canonical_team(event.get("home_team", ""))
    away_key = canonical_team(event.get("away_team", ""))
    result: dict[str, float] = {}

    for outcome in market.get("outcomes") or []:
        name = normalize(outcome.get("name", ""))
        team_key = canonical_team(outcome.get("name", ""))
        try:
            price = float(outcome.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 1:
            continue
        if team_key == home_key:
            result["home"] = price
        elif team_key == away_key:
            result["away"] = price
        elif name in {"draw", "empate", "tie"}:
            result["draw"] = price

    if {"home", "draw", "away"}.issubset(result):
        return result
    return None


def devig(prices: dict[str, float]) -> dict[str, float]:
    raw = {key: 1.0 / price for key, price in prices.items()}
    total = sum(raw.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Cuotas inválidas para retirar margen")
    return {key: value / total for key, value in raw.items()}


def match_event(matches: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any] | None:
    event_home = canonical_team(event.get("home_team", ""))
    event_away = canonical_team(event.get("away_team", ""))
    event_time = parse_iso(event.get("commence_time"))
    candidates: list[tuple[float, dict[str, Any]]] = []

    for match in matches:
        teams = match.get("teams") or []
        if len(teams) != 2:
            continue
        match_home = canonical_team(str(teams[0]))
        match_away = canonical_team(str(teams[1]))
        same_pair = (match_home, match_away) == (event_home, event_away)
        reversed_pair = (match_home, match_away) == (event_away, event_home)
        if not (same_pair or reversed_pair):
            continue

        match_time = parse_iso(match.get("kickoff"))
        if event_time and match_time:
            delta = abs((event_time - match_time).total_seconds())
            if delta > 8 * 3600:
                continue
        else:
            delta = 0
        candidates.append((delta, match))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def summarize_event(event: dict[str, Any]) -> dict[str, Any] | None:
    books: list[dict[str, Any]] = []
    normalized_probabilities: list[dict[str, float]] = []

    for bookmaker in event.get("bookmakers") or []:
        market = find_h2h_market(bookmaker)
        if not market:
            continue
        prices = outcomes_for_event(event, market)
        if not prices:
            continue
        normalized_probabilities.append(devig(prices))
        books.append({
            "book": bookmaker.get("title") or bookmaker.get("key") or "Casa",
            "bookKey": bookmaker.get("key"),
            "home": decimal_to_american(prices["home"]),
            "draw": decimal_to_american(prices["draw"]),
            "away": decimal_to_american(prices["away"]),
            "homeDecimal": round(prices["home"], 3),
            "drawDecimal": round(prices["draw"], 3),
            "awayDecimal": round(prices["away"], 3),
            "lastUpdate": bookmaker.get("last_update"),
        })

    if not normalized_probabilities:
        return None

    consensus = {
        key: round(mean(p[key] for p in normalized_probabilities) * 100, 1)
        for key in ("home", "draw", "away")
    }
    best_decimal = {
        "home": max(book["homeDecimal"] for book in books),
        "draw": max(book["drawDecimal"] for book in books),
        "away": max(book["awayDecimal"] for book in books),
    }

    return {
        "odds": books,
        "probability": consensus,
        "bookmakerCount": len(books),
        "bestOdds": {
            key: {
                "decimal": round(value, 3),
                "american": decimal_to_american(value),
            }
            for key, value in best_decimal.items()
        },
    }


def movement_text(previous: dict[str, Any] | None, current: dict[str, float]) -> str:
    if not previous or not all(isinstance(previous.get(k), (int, float)) for k in ("home", "draw", "away")):
        return "Primera lectura automática del mercado 1X2."

    labels = {"home": "local", "draw": "empate", "away": "visitante"}
    changes = {key: round(current[key] - float(previous[key]), 1) for key in labels}
    key = max(changes, key=lambda k: abs(changes[k]))
    change = changes[key]
    if abs(change) < 2:
        return "Sin movimiento significativo del consenso desde la actualización anterior."
    direction = "subió" if change > 0 else "bajó"
    return f"La probabilidad sin margen del {labels[key]} {direction} {abs(change):.1f} puntos porcentuales."


def main() -> int:
    api_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if not api_key:
        print("Falta el secreto THE_ODDS_API_KEY.", file=sys.stderr)
        return 2

    sport_key = os.environ.get("THE_ODDS_SPORT_KEY", "soccer_fifa_world_cup").strip() or "soccer_fifa_world_cup"
    regions = os.environ.get("THE_ODDS_REGIONS", "eu").strip() or "eu"
    markets = os.environ.get("THE_ODDS_MARKETS", "h2h").strip() or "h2h"

    response = requests.get(
        f"{API_BASE}/sports/{sport_key}/odds/",
        params={
            "apiKey": api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        },
        timeout=30,
    )
    response.raise_for_status()
    events = response.json()
    if not isinstance(events, list):
        print("Respuesta inesperada de The Odds API.", file=sys.stderr)
        return 3

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    matches = data.get("matches") or []
    updated = 0
    unmatched: list[str] = []

    for event in events:
        match = match_event(matches, event)
        if not match:
            unmatched.append(f"{event.get('home_team')} vs {event.get('away_team')}")
            continue
        summary = summarize_event(event)
        if not summary:
            continue

        previous = match.get("probability") if match.get("oddsSource") == "The Odds API" else None
        match["market"] = "1X2 (90 minutos)"
        match["odds"] = summary["odds"]
        match["probability"] = summary["probability"]
        match["bestOdds"] = summary["bestOdds"]
        match["bookmakerCount"] = summary["bookmakerCount"]
        match["oddsSource"] = "The Odds API"
        match["oddsEventId"] = event.get("id")
        match["oddsUpdatedAt"] = max(
            (book.get("lastUpdate") for book in summary["odds"] if book.get("lastUpdate")),
            default=None,
        )
        match["marketChange"] = movement_text(previous, summary["probability"])

        status = normalize(match.get("status", ""))
        if status in {"en vivo", "final", "cancelado", "suspendido", "interrumpido"}:
            match["classification"] = "evitar"
        elif match.get("classification") not in {"considerar", "esperar", "evitar"}:
            match["classification"] = "esperar"

        updated += 1

    now = datetime.now(ZoneInfo(TIMEZONE))
    data.setdefault("meta", {})
    data["meta"].update({
        "lastUpdated": now.isoformat(),
        "sourceNote": (
            "Calendario y marcadores: API-Football. Cuotas 1X2 y probabilidades sin margen: "
            "The Odds API. Las probabilidades reflejan el consenso del mercado, no una garantía ni un modelo propio."
        ),
        "theOddsApi": {
            "enabled": True,
            "sportKey": sport_key,
            "regions": regions.split(","),
            "markets": markets.split(","),
            "eventsReceived": len(events),
            "matchesUpdated": updated,
            "requestsRemaining": response.headers.get("x-requests-remaining"),
            "requestsUsed": response.headers.get("x-requests-used"),
            "lastRequestCost": response.headers.get("x-requests-last"),
            "unmatchedEvents": unmatched[:20],
        },
    })

    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Cuotas actualizadas para {updated} partidos; eventos recibidos: {len(events)}.")
    if unmatched:
        print("Eventos sin coincidencia: " + "; ".join(unmatched))
    print(
        "Créditos restantes:", response.headers.get("x-requests-remaining", "desconocido"),
        "| costo:", response.headers.get("x-requests-last", "desconocido"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
