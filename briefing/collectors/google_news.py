"""Google News RSS 검색 — 사이트 직접 수집이 막히거나 빈약할 때의 보조 수단."""
from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote

import feedparser

from ..models import Article
from ..textutil import clean, strip_html

log = logging.getLogger(__name__)


def search_google_news(session, query: str, days: int, section: int, source: str,
                       org: str = "", limit: int = 3, accept=None) -> list[Article]:
    """accept(title) -> bool 이 주어지면 통과한 기사만 limit 개까지 담는다."""
    url = ("https://news.google.com/rss/search?q=" + quote(f"{query} when:{days}d")
           + "&hl=ko&gl=KR&ceid=KR:ko")
    try:
        raw = session.get(url, timeout=20).content
    except Exception as e:
        log.warning("Google News 실패 (%s): %s", query, e)
        return []
    feed = feedparser.parse(raw)
    out: list[Article] = []
    for e in feed.entries[: limit * 6]:
        title = clean(e.get("title", ""))
        press = ""
        if " - " in title:
            title, press = title.rsplit(" - ", 1)
            if title.endswith(" - " + press):      # "제목 - 언론사 - 언론사" 형태 보정
                title = title[: -len(" - " + press)]
        if accept and not accept(title):
            continue
        pub = None
        if e.get("published_parsed"):
            pub = datetime(*e.published_parsed[:6]).date()
        out.append(Article(
            section=section, source=f"{source}" + (f" ({press})" if press else ""), title=title.strip(),
            url=e.get("link", ""), published=pub, body=strip_html(e.get("summary", ""))[:300],
            org=org, via="google_news"))
        if len(out) >= limit:
            break
    return out
