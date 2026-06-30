#!/usr/bin/env python3
"""Genera context.json con noticias públicas relacionadas con los partidos de data.json.

Fuente de descubrimiento: GDELT DOC 2.0.
No descarga ni copia el cuerpo completo de los artículos. Solo conserva metadatos,
títulos y enlaces para que el usuario abra la fuente original.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_PATH = Path("data.json")
CONTEXT_PATH = Path("context.json")
API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_ARTICLES = 80
BATCH_SIZE = 8

ALIASES: dict[str, list[str]] = {
    "usa": ["united states", "usmnt", "estados unidos"],
    "united states": ["usa", "usmnt", "estados unidos"],
    "south korea": ["korea republic", "corea del sur"],
    "korea republic": ["south korea", "corea del sur"],
    "dr congo": ["democratic republic of congo", "congo dr", "rd congo"],
    "ivory coast": ["cote d ivoire", "costa de marfil"],
    "cape verde": ["cabo verde"],
    "mexico": ["mexico", "méxico"],
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
    "australia": ["australia"],
    "canada": ["canadá"],
    "portugal": ["portugal"],
    "colombia": ["colombia"],
    "argentina": ["argentina"],
    "austria": ["austria"],
    "senegal": ["senegal"],
    "ghana": ["ghana"],
}

TAG_RULES: dict[str, tuple[str, ...]] = {
    "lesión o baja": ("injury", "injured", "lesion", "lesión", "lesionado", "baja", "hamstring", "ankle", "knee"),
    "alineación": ("lineup", "line-up", "starting xi", "team news", "alineacion", "alineación", "titulares", "once inicial"),
    "sanción": ("suspended", "suspension", "ban", "sancion", "sanción", "suspendido"),
    "previa": ("preview", "prediction", "predictions", "previa", "pronostico", "pronóstico"),
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique_teams(matches: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    teams: list[str] = []
    for match in matches:
        for team in match.get("teams") or []:
            name = str(team).strip()
            key = normalize(name)
            if name and key not in seen:
                seen.add(key)
                teams.append(name)
    return teams


def team_aliases(team: str) -> list[str]:
    key = normalize(team)
    values = [team]
    values.extend(ALIASES.get(key, []))
    dedup: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            dedup.append(value)
    return dedup


def build_query(teams: list[str]) -> str:
    phrases: list[str] = []
    for team in teams:
        phrases.append(f'"{team.replace(chr(34), "")}"')
    team_block = " OR ".join(phrases)
    return f"({team_block}) (football OR soccer OR futbol OR FIFA OR mundial)"


def request_articles(query: str) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(MAX_ARTICLES),
        "timespan": "2d",
        "sort": "datedesc",
        "format": "json",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "tokol-context-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8-sig", errors="replace")
    payload = json.loads(raw)
    rows = payload.get("articles") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def article_tags(title: str) -> list[str]:
    text = normalize(title)
    tags: list[str] = []
    for tag, keywords in TAG_RULES.items():
        if any(normalize(keyword) in text for keyword in keywords):
            tags.append(tag)
    return tags


def clean_article(row: dict[str, Any], teams: list[str]) -> dict[str, Any] | None:
    url = str(row.get("url") or "").strip()
    title = str(row.get("title") or "").strip()
    if not url.startswith(("http://", "https://")) or not title:
        return None

    title_norm = normalize(title)
    matched: list[str] = []
    for team in teams:
        aliases = team_aliases(team)
        if any(normalize(alias) in title_norm for alias in aliases):
            matched.append(team)

    return {
        "title": title[:300],
        "url": url,
        "domain": str(row.get("domain") or urllib.parse.urlparse(url).netloc).lower(),
        "language": str(row.get("language") or ""),
        "sourceCountry": str(row.get("sourcecountry") or ""),
        "seenDate": str(row.get("seendate") or ""),
        "image": str(row.get("socialimage") or ""),
        "matchedTeams": matched,
        "tags": article_tags(title),
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
    if any(term in title for term in ("world cup", "copa del mundo", "mundial", "fifa")):
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

    teams = unique_teams(matches)
    queries: list[str] = [
        '("FIFA World Cup" OR "World Cup 2026" OR "Copa del Mundo 2026" OR "Mundial 2026")'
    ]
    for index in range(0, len(teams), BATCH_SIZE):
        queries.append(build_query(teams[index:index + BATCH_SIZE]))

    raw_articles: list[dict[str, Any]] = []
    failures: list[str] = []
    for query in queries:
        try:
            raw_articles.extend(request_articles(query))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
            failures.append(str(error))
        time.sleep(1.2)

    if not raw_articles:
        print("No se pudo obtener contexto web; context.json no se modificó.", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 3

    cleaned: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in raw_articles:
        article = clean_article(row, teams)
        if not article or article["url"] in seen_urls:
            continue
        seen_urls.add(article["url"])
        cleaned.append(article)

    cleaned.sort(key=lambda article: str(article.get("seenDate") or ""), reverse=True)

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

    global_articles = [article for article in cleaned if article.get("matchedTeams")][:20]
    if len(global_articles) < 8:
        global_articles = cleaned[:20]

    output = {
        "meta": {
            "updatedAt": now_iso(),
            "source": "GDELT DOC 2.0",
            "articleCount": len(cleaned),
            "queryCount": len(queries),
            "warning": "Las noticias son menciones públicas localizadas en internet. No confirman por sí solas rumores, lesiones o alineaciones.",
        },
        "articles": global_articles,
        "matches": match_context,
    }
    save_json(CONTEXT_PATH, output)
    print(
        f"Contexto web actualizado: {len(cleaned)} artículos únicos; "
        f"{len(match_context)} partidos relacionados; consultas: {len(queries)}."
    )
    if failures:
        print(f"Consultas con advertencia: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
