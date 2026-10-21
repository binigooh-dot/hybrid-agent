"""[TOOLS / knowledge] Free public knowledge sources - none need an API key.

Tools: wikipedia_search, wikipedia_summary, arxiv_search, weather, define_word, read_feed

Services used (all free, keyless, rate-limited for fair use):
  Wikipedia REST + Action API   https://en.wikipedia.org
  arXiv export API              https://export.arxiv.org/api/query
  Open-Meteo forecast+geocoding https://open-meteo.com
  Free Dictionary API           https://dictionaryapi.dev
"""
from __future__ import annotations

import re
import urllib.parse

from ...security.xmlsafe import safe_xml_fromstring
from ..registry import S, ToolContext, ToolError, ToolRegistry
from .web import RateLimited, html_to_text, http_get_json, http_get_text, search_marginalia, search_wikipedia

CATEGORY = "knowledge"
ATOM = "{http://www.w3.org/2005/Atom}"

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "heavy showers", 82: "violent showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
}


def parse_feed(xml_text: str, limit: int = 15) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, link, date, summary}]."""
    try:
        root = safe_xml_fromstring(xml_text)
    except ToolError as e:
        raise ToolError(f"Not a valid RSS/Atom feed: {e}") from None
    items = []
    for it in root.iter("item"):  # RSS
        items.append({"title": it.findtext("title", ""), "link": it.findtext("link", ""),
                      "date": it.findtext("pubDate", ""),
                      "summary": html_to_text(it.findtext("description", ""))[:300]})
    for it in root.iter(f"{ATOM}entry"):  # Atom
        link = it.find(f"{ATOM}link")
        items.append({"title": (it.findtext(f"{ATOM}title") or "").strip(),
                      "link": link.get("href", "") if link is not None else "",
                      "date": it.findtext(f"{ATOM}updated") or it.findtext(f"{ATOM}published") or "",
                      "summary": html_to_text(it.findtext(f"{ATOM}summary") or "")[:300]})
    return items[:limit]


def register(reg: ToolRegistry) -> None:
    t = reg.group(CATEGORY, risk="network")

    @t("wikipedia_search", "Search Wikipedia article titles. Then use wikipedia_summary or fetch_url.",
       S(query="string", lang="string?|Language code, default 'en'", limit="integer?|Default 8"))
    def wikipedia_search(ctx: ToolContext, query: str, lang: str = "en", limit: int = 8):
        try:
            rows = search_wikipedia(query, limit, lang)
        except RateLimited:           # Wikipedia's API is busy: find articles via a public search engine instead
            rows = [r for r in search_marginalia(f"{query} site:{lang}.wikipedia.org", limit * 2)
                    if f"{lang}.wikipedia.org/wiki/" in r[1]][:limit]
        return "\n".join(f"- {t}: {s}  ({u})" for t, u, s in rows) or "No results."

    @t("wikipedia_summary", "Get the introduction of a Wikipedia article by exact title.",
       S(title="string", lang="string?|Language code, default 'en'"))
    def wikipedia_summary(ctx: ToolContext, title: str, lang: str = "en"):
        page = urllib.parse.quote(title.replace(" ", "_"))
        try:
            d = http_get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{page}")
        except RateLimited:           # API busy: read the article page itself (an ordinary page view)
            _, body = http_get_text(f"https://{lang}.wikipedia.org/wiki/{page}")
            paras = [html_to_text(p) for p in re.findall(r"<p>(.*?)</p>", body, re.DOTALL)]
            intro = "\n\n".join(p for p in paras if len(p) > 80)[:2500]
            return f"{title}\n\n{intro}\n\nhttps://{lang}.wikipedia.org/wiki/{page}"
        return f"{d.get('title')}\n{d.get('description', '')}\n\n{d.get('extract', '')}\n\n" \
               f"{d.get('content_urls', {}).get('desktop', {}).get('page', '')}"

    @t("arxiv_search", "Search arXiv for scientific papers (title, authors, date, abstract, link).",
       S(query="string", max_results="integer?|Default 5"))
    def arxiv_search(ctx: ToolContext, query: str, max_results: int = 5):
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": f"all:{query}", "max_results": max_results, "sortBy": "relevance"})
        _, body = http_get_text(url)
        root = safe_xml_fromstring(body)
        out = []
        for e in root.iter(f"{ATOM}entry"):
            authors = ", ".join(a.findtext(f"{ATOM}name", "") for a in e.findall(f"{ATOM}author"))
            out.append(f"* {' '.join((e.findtext(f'{ATOM}title') or '').split())}\n"
                       f"  {authors[:150]} | {(e.findtext(f'{ATOM}published') or '')[:10]}\n"
                       f"  {e.findtext(f'{ATOM}id')}\n"
                       f"  {' '.join((e.findtext(f'{ATOM}summary') or '').split())[:500]}")
        return "\n\n".join(out) or "No papers found."

    @t("weather", "Current weather and a short daily forecast for a place name (via Open-Meteo).",
       S(place="string|City or place name", days="integer?|Forecast days 1-7, default 3"))
    def weather(ctx: ToolContext, place: str, days: int = 3):
        geo = http_get_json("https://geocoding-api.open-meteo.com/v1/search?"
                            + urllib.parse.urlencode({"name": place, "count": 1}))
        if not geo.get("results"):
            raise ToolError(f"Place not found: {place}")
        g = geo["results"][0]
        q = {"latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto",
             "forecast_days": max(1, min(days, 7)),
             "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
             "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
        d = http_get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q))
        c = d.get("current", {})
        lines = [f"{g['name']}, {g.get('admin1', '')} {g.get('country', '')}".strip(),
                 f"Now: {c.get('temperature_2m')}°C (feels {c.get('apparent_temperature')}°C), "
                 f"{WEATHER_CODES.get(c.get('weather_code'), '?')}, humidity {c.get('relative_humidity_2m')}%, "
                 f"wind {c.get('wind_speed_10m')} km/h"]
        dd = d.get("daily", {})
        for i, day in enumerate(dd.get("time", [])):
            lines.append(f"{day}: {dd['temperature_2m_min'][i]}–{dd['temperature_2m_max'][i]}°C, "
                         f"{WEATHER_CODES.get(dd['weather_code'][i], '?')}, "
                         f"rain chance {dd['precipitation_probability_max'][i]}%")
        return "\n".join(lines)

    @t("define_word", "Dictionary definitions, part of speech and examples for an English word.",
       S(word="string"))
    def define_word(ctx: ToolContext, word: str):
        data = http_get_json("https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word))
        if not isinstance(data, list):
            raise ToolError(f"No definition found for '{word}'.")
        out = []
        for entry in data[:2]:
            for m in entry.get("meanings", [])[:4]:
                for d in m.get("definitions", [])[:2]:
                    ex = f'  e.g. "{d["example"]}"' if d.get("example") else ""
                    out.append(f"({m.get('partOfSpeech')}) {d.get('definition')}{ex}")
        return f"{word}:\n" + "\n".join(out)

    @t("read_feed", "Read an RSS or Atom news feed: latest titles, links, dates and summaries.",
       S(url="string", limit="integer?|Default 15"))
    def read_feed(ctx: ToolContext, url: str, limit: int = 15):
        _, body = http_get_text(url)
        items = parse_feed(body, limit)
        return "\n\n".join(f"* {i['title']}\n  {i['date']}\n  {i['link']}\n  {i['summary']}"
                           for i in items) or "Feed has no items."
