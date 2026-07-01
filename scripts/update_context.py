#!/usr/bin/env python3
"""Actualiza context.json con contexto público de internet.

Estrategia:
1. Hace una sola consulta a GDELT para reducir errores HTTP 429.
2. Si GDELT limita la consulta, intenta una fuente RSS pública.
3. No descarga ni copia artículos completos: guarda título, enlace y metadatos.
4. Si ninguna fuente responde, conserva context.json y termina sin error.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_PATH = Path("data.json")
CONTEXT_PATH = Path("context.json")

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_RSS_URL = "https://news.google.com/rss/search"

MAX_ARTICLES = 60
MAX_TEAMS_IN_QUERY = 12
REQUEST_TIMEOUT = 40

ALIASES: dict[str, list[str]] = {
    "usa": ["united states", "usmnt", "estados unidos"],
    "united states": ["usa", "usmnt", "estados unidos"],
    "south korea": ["korea republic", "corea del sur"],
    "korea republic": ["south korea", "corea del sur"],
    "dr congo": ["democratic republic of congo", "congo dr", "rd congo"],
    "ivory coast": ["cote d ivoire", "costa de marfil"],
    "cape verde": ["cabo verde"],
    "mexico": ["méxico"],
    "brazil": ["brasil"],
    "japan": ["japon", "japón"],
    "spain": ["espana", "españa"],
    "germany": ["alemania"],
    "england": ["inglaterra"],
    "switzerland": ["suiza"],
    "belgium": ["belgica", "bélgica"],
    "morocco": ["marruecos"],
    "algeria": ["argelia"],
    "egypt": ["egipto"],
    "canada": ["canadá"],
}

TAG_RULES: dict[str, tuple[str, ...]] = {
    "lesión o baja": (
        "injury", "injured", "lesion", "lesión", "lesionado",
        "baja", "hamstring", "ankle", "knee",
    ),
    "alineación": (
        "lineup", "line-up", "starting xi", "team news",
        "alineacion", "alineación", "titulares", "once inicial",
    ),
    "sanción": (
        "suspended", "suspension", "ban",
        "sancion", "sanción", "suspendido",
    ),
    "previa": (
        "preview", "prediction", "predictions",
        "previa", "pronostico", "pronóstico",
    ),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_iso(value: str | None) -> datetime:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)


def priority_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {"En vivo": 0, "Próximo": 1, "Final": 2}
    return sorted(
        matches,
        key=lambda match: (
            rank.get(str(match.get("status")), 3),
            parse_iso(str(match.get("kickoff") or "")),
        ),
    )


def selected_teams(matches: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    teams: list[str] = []

    for match in priority_matches(matches):
        for team in match.get("teams") or []:
            name = str(team).strip()
            key = normalize(name)
            if name and key not in seen:
                seen.add(key)
                teams.append(name)
                if len(teams) >= MAX_TEAMS_IN_QUERY:
                    return teams
    return teams


def team_aliases(team: str) -> list[str]:
    values = [team, *ALIASES.get(normalize(team), [])]
    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        key = normalize(value)
        if key and key not in seen:
            seen.add(key)
            output.append(value)

    return output


def build_query(teams: list[str]) -> str:
    team_terms = " OR ".join(
        f'"{team.replace(chr(34), "")}"'
        for team in teams
    )
    tournament_terms = (
        '"FIFA World Cup" OR "World Cup 2026" OR '
        '"Copa del Mundo 2026" OR "Mundial 2026"'
    )

    if team_terms:
        return f"({team_terms}) ({tournament_terms})"
    return f"({tournament_terms})"


def request(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/rss+xml, application/xml, text/xml",
            "User-Agent": "Mozilla/5.0 TokolContext/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def request_gdelt(query: str) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(MAX_ARTICLES),
        "timespan": "2d",
        "sort": "datedesc",
        "format": "json",
    }
    url = f"{GDELT_URL}?{urllib.parse.urlencode(params)}"

    for attempt in range(2):
        try:
            raw = request(url).decode("utf-8-sig", errors="replace")
            payload = json.loads(raw)
            rows = payload.get("articles") if isinstance(payload, dict) else []
            return rows if isinstance(rows, list) else []
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 1:
                raise
            retry_after = error.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 20
            print(f"GDELT limitó la consulta. Reintento en {wait_seconds} segundos.")
            time.sleep(wait_seconds)

    return []


def request_google_rss(query: str) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "hl": "es-419",
        "gl": "MX",
        "ceid": "MX:es-419",
    }
    url = f"{GOOGLE_RSS_URL}?{urllib.parse.urlencode(params)}"
    raw = request(url)
    root = ET.fromstring(raw)

    rows: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[:MAX_ARTICLES]:
        source = item.find("source")
        rows.append({
            "title": item.findtext("title") or "",
            "url": item.findtext("link") or "",
            "domain": (source.get("url") if source is not None else "") or "",
            "language": "Spanish",
            "sourcecountry": "",
            "seendate": item.findtext("pubDate") or "",
            "socialimage": "",
        })
    return rows


def article_tags(title: str) -> list[str]:
    text = normalize(title)
    tags: list[str] = []

    for tag, keywords in TAG_RULES.items():
        if any(normalize(keyword) in text for keyword in keywords):
            tags.append(tag)

    return tags


def clean_article(
    row: dict[str, Any],
    teams: list[str],
    source_name: str,
) -> dict[str, Any] | None:
    url = str(row.get("url") or "").strip()
    title = str(row.get("title") or "").strip()

    if not url.startswith(("http://", "https://")) or not title:
        return None

    title_norm = normalize(title)
    matched: list[str] = []

    for team in teams:
        if any(normalize(alias) in title_norm for alias in team_aliases(team)):
            matched.append(team)

    domain = str(row.get("domain") or "").strip()
    if domain.startswith(("http://", "https://")):
        domain = urllib.parse.urlparse(domain).netloc
    if not domain:
        domain = urllib.parse.urlparse(url).netloc

    return {
        "title": title[:300],
        "url": url,
        "domain": domain.lower(),
        "language": str(row.get("language") or ""),
        "sourceCountry": str(row.get("sourcecountry") or ""),
        "seenDate": str(row.get("seendate") or ""),
        "image": str(row.get("socialimage") or ""),
        "matchedTeams": matched,
        "tags": article_tags(title),
        "discoveredBy": source_name,
    }


def article_score(article: dict[str, Any], home: str, away: str) -> int:
    matched = {normalize(team) for team in article.get("matchedTeams") or []}
    home_match = normalize(home) in matched
    away_match = normalize(away) in matched

    score = 0
    if home_match and away_match:
        score += 12
    elif home_match or away_match:
        score += 6

    title = normalize(str(article.get("title") or ""))
    if any(term in title for term in (
        "world cup", "copa del mundo", "mundial", "fifa",
    )):
        score += 2
    if article.get("tags"):
        score += 1

    return score


def main() -> int:
    data = load_json(DATA_PATH, {"matches": []})
    matches = data.get("matches") or []

    if not matches:
        print("data.json no contiene partidos.", file=sys.stderr)
        return 2

    teams = selected_teams(matches)
    query = build_query(teams)

    raw_articles: list[dict[str, Any]] = []
    source_name = ""
    warnings: list[str] = []

    try:
        raw_articles = request_gdelt(query)
        source_name = "GDELT"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
        warnings.append(f"GDELT: {error}")

    if not raw_articles:
        try:
            raw_articles = request_google_rss(query)
            source_name = "Google News RSS"
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ET.ParseError,
        ) as error:
            warnings.append(f"Google News RSS: {error}")

    if not raw_articles:
        print(
            "Ninguna fuente respondió. Se conserva context.json sin cambios.",
            file=sys.stderr,
        )
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)
        return 0

    cleaned: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for row in raw_articles:
        article = clean_article(row, teams, source_name)
        if not article or article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        cleaned.append(article)

    cleaned.sort(
        key=lambda article: str(article.get("seenDate") or ""),
        reverse=True,
    )

    match_context: dict[str, list[dict[str, Any]]] = {}

    for match in matches:
        match_id = str(match.get("id") or "")
        pair = match.get("teams") or []

        if not match_id or len(pair) < 2:
            continue

        home, away = str(pair[0]), str(pair[1])
        scored = [
            (article_score(article, home, away), article)
            for article in cleaned
        ]
        selected = [article for score, article in scored if score > 0]
        selected.sort(
            key=lambda article: (
                article_score(article, home, away),
                str(article.get("seenDate") or ""),
            ),
            reverse=True,
        )
        match_context[match_id] = selected[:6]

    global_articles = [
        article for article in cleaned
        if article.get("matchedTeams")
    ][:20]

    if len(global_articles) < 8:
        global_articles = cleaned[:20]

    output = {
        "meta": {
            "updatedAt": now_iso(),
            "source": source_name,
            "articleCount": len(cleaned),
            "queryCount": 1,
            "warning": (
                "Las noticias son menciones públicas encontradas en internet. "
                "No confirman por sí solas rumores, lesiones o alineaciones."
            ),
        },
        "articles": global_articles,
        "matches": match_context,
    }

    save_json(CONTEXT_PATH, output)

    print(
        f"Contexto actualizado con {source_name}: "
        f"{len(cleaned)} artículos únicos; "
        f"{len(match_context)} partidos relacionados; "
        "consultas principales: 1."
    )

    for warning in warnings:
        print(f"Advertencia: {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
