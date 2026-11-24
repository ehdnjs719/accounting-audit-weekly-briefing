"""섹션 3: 4대 회계법인(삼일PwC, 삼정KPMG, 안진Deloitte, 한영EY) 인사이트·뉴스룸.

수집 전략 (사이트별로 다르게 실패하므로 3단 방어):
 1) Playwright 로 목록 페이지를 렌더링 → 법인별 '기사 URL 정규식'에 맞는 링크만 추출
    (내비게이션 메뉴 링크는 정규식으로 걸러짐. PwC 는 requests 가 403 이라 브라우저 필수)
 2) URL 에 날짜가 있으면(KPMG, EY 뉴스룸) 기사를 열기 전에 기간 밖 글을 거른다
    → 기사 페이지는 requests 우선, 막히면 브라우저로 열어 og:title / 게시일 / 본문 추출
 3) Google News RSS 로 법인명 + 회계·감사·AI 키워드 기사를 보강
    (목록이 JS API 뒤에 숨어 있는 Deloitte 등에서 결손을 메움)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from urllib.parse import urljoin, urldefrag

from bs4 import BeautifulSoup

from ..http import get_text
from ..models import Article
from ..textutil import (clean, description, extract_main_text, find_published, is_relevant,
                        keyword_hits, page_title, parse_date)
from .google_news import search_google_news

log = logging.getLogger(__name__)

FIRMS = [
    {
        "org": "삼일PwC",
        "pages": ["https://www.pwc.com/kr/ko/insights.html"],
        "pattern": r"^https://www\.pwc\.com/kr/ko/insights/[\w-]+/[\w.-]+\.html$",
        "news": '("삼일PwC" OR "삼일회계법인") (회계 OR 감사 OR AI OR 내부통제 OR 공시)',
    },
    {
        "org": "삼정KPMG",
        "pages": ["https://kpmg.com/kr/ko/insights.html", "https://kpmg.com/kr/ko/media/press-releases.html"],
        "pattern": r"^https://kpmg\.com/kr/ko/(insights|media/press-releases)/.*20\d\d/.+\.html$",
        "news": '"삼정KPMG" (회계 OR 감사 OR AI OR 내부통제 OR 공시)',
    },
    {
        "org": "안진Deloitte",
        "pages": ["https://www.deloitte.com/kr/ko/our-thinking.html",
                  "https://www.deloitte.com/kr/ko/about/press-room.html"],
        "pattern": r"^https://www\.deloitte\.com/kr/ko/(our-thinking|about/press-room|issues)/[\w/-]+/[\w-]+\.html$",
        "news": '("딜로이트 안진" OR "안진회계법인" OR "한국 딜로이트") (회계 OR 감사 OR AI OR 내부통제 OR 공시)',
    },
    {
        "org": "한영EY",
        "pages": ["https://www.ey.com/ko_kr/insights", "https://www.ey.com/ko_kr/newsroom"],
        "pattern": r"^https://www\.ey\.com/ko_kr/(insights/[\w-]+/[\w-]+|newsroom/20\d\d/\d\d/[\w-]+)$",
        "news": '("EY한영" OR "한영회계법인") (회계 OR 감사 OR AI OR 내부통제 OR 공시)',
    },
]
FIRM_NAMES = re.compile(r"(EY)?(삼일|삼정|안진|한영|딜로이트\s?안진)\s?(회계법인|PwC|KPMG)?|한영회계법인|딜로이트|EY한영|삼일PwC|삼정KPMG")
SKIP_URL = re.compile(r"/(contact|careers?|services|industries|about-us|alumni)(/|\.html|$)", re.I)


def date_from_url(url: str) -> date | None:
    """URL 에 숨은 날짜 복원: EY '...-2026-11-23', KPMG '/2026/11/press-release-17', '/2026/businessfocus-1123'."""
    if m := re.search(r"(20\d\d)-(\d\d)-(\d\d)", url):
        y, mo, d = map(int, m.groups())
    elif m := re.search(r"/(20\d\d)/(\d\d)/[a-z-]*?-(\d\d)\.html", url):
        y, mo, d = map(int, m.groups())
    elif m := re.search(r"/(20\d\d)/[a-z-]+-(\d\d)(\d\d)\.html", url):
        y, mo, d = map(int, m.groups())
    else:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _month_floor(url: str) -> date | None:
    """URL 에 연/월만 있는 경우(EY '/newsroom/2026/09/') 해당 월의 말일 근사치."""
    if m := re.search(r"/(20\d\d)/(\d\d)/", url):
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y + (mo == 12), mo % 12 + 1, 1)
    return None


def _list_links(firm, session, browser) -> list[str]:
    links: list[str] = []
    for page in firm["pages"]:
        html = browser.fetch(page) if browser else None
        if html is None:
            try:
                html = get_text(session, page)
            except Exception as e:
                log.warning("%s 목록 실패: %s", firm["org"], e)
                continue
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            url = urldefrag(urljoin(page, a["href"]))[0].split("?")[0]
            if re.match(firm["pattern"], url) and not SKIP_URL.search(url) and url not in links:
                links.append(url)
    return links


def _open_article(url, session, browser) -> str | None:
    try:
        return get_text(session, url)
    except Exception:
        return browser.fetch(url, wait_ms=2000, scroll=0) if browser else None


def collect_firm(firm, session, browser, since: date, core, ai, exclude, max_open: int = 14) -> list[Article]:
    out: list[Article] = []
    opened = 0
    for url in _list_links(firm, session, browser):
        d = date_from_url(url)
        if d and d < since:
            continue
        mf = _month_floor(url)
        if not d and mf and mf < since:
            continue
        if opened >= max_open:
            break
        html = _open_article(url, session, browser)
        opened += 1
        if not html:
            continue
        pub = d or find_published(html)
        if not pub or pub < since:
            continue
        title = page_title(html) or url.rsplit("/", 1)[-1]
        desc = description(html)
        if parse_date(desc) and len(desc) < 15:   # KPMG 는 description 에 날짜만 들어 있음
            desc = ""
        body = clean(desc + " " + extract_main_text(html, 2500))
        if not is_relevant(title, body, core, ai, exclude, min_body_hits=3):
            continue
        kind = "뉴스룸" if re.search(r"press|newsroom|media", url) else "인사이트"
        out.append(Article(3, f"{firm['org']} {kind}", title, url, pub, body=body[:2500],
                           org=firm["org"], via="browser" if browser else "site"))
        time.sleep(0.3)
    return out


def collect_big4(session, browser, since: date, days: int, core, ai, exclude,
                 news_limit: int = 3, statuses: list | None = None) -> list[Article]:
    from ..models import SourceStatus
    result: list[Article] = []
    for firm in FIRMS:
        site_items: list[Article] = []
        try:
            site_items = collect_firm(firm, session, browser, since, core, ai, exclude)
            if statuses is not None:
                statuses.append(SourceStatus(f"{firm['org']} 홈페이지", True, len(site_items)))
        except Exception as e:
            log.exception("%s 수집 실패", firm["org"])
            if statuses is not None:
                statuses.append(SourceStatus(f"{firm['org']} 홈페이지", False, 0, str(e)[:120]))
        # 법인명 속 '회계법인'이 키워드로 잡히지 않도록 이름을 지운 제목으로 관련성 판정
        def accept(title: str) -> bool:
            t = FIRM_NAMES.sub(" ", title)
            return bool(keyword_hits(t, core, exclude) or keyword_hits(t, ai, exclude))
        news = search_google_news(session, firm["news"], days, 3, f"{firm['org']} 언론보도",
                                  org=firm["org"], limit=news_limit, accept=accept)
        news = [n for n in news if not n.published or n.published >= since]
        if statuses is not None:
            statuses.append(SourceStatus(f"{firm['org']} Google News 보강", True, len(news)))
        result += site_items + news
    return result
