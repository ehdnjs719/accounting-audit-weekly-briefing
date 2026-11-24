"""섹션 2: 한국공인회계사회(KICPA).

- CPA뉴스: 공식 RSS (news.kicpa.or.kr/rss/allArticle.xml) — 가장 안정적
- 공지사항(알림마당): 포털 메인 페이지의 공지 목록을 파싱.
  게시글 번호(bltnNo)가 '1' + 밀리초 타임스탬프 형태라 게시일을 번호에서 복원한다.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from ..http import get_text
from ..models import Article
from ..textutil import clean, is_relevant, parse_date, strip_html

log = logging.getLogger(__name__)

KICPA_MAIN = "https://www.kicpa.or.kr/portal/default/kicpa/main/kr_pc_guest.page"
CPA_NEWS_RSS = "https://news.kicpa.or.kr/rss/allArticle.xml"
KST = timezone(timedelta(hours=9))
NOISE = re.compile(r"입찰|모집|채용|선발|제휴|후보자|위원.*등록|건강검진")


def bltn_date(bltn_no: str) -> date | None:
    try:
        ms = int(bltn_no[1:14])
        d = datetime.fromtimestamp(ms / 1000, tz=KST).date()
        return d if date(2015, 1, 1) <= d <= date.today() + timedelta(days=1) else None
    except (ValueError, OSError):
        return None


def collect_kicpa_notices(session, since: date, exclude) -> list[Article]:
    """공지 상세 페이지는 포털 프레임(JS)이라 본문 추출이 불안정 → 메인의 '제목+미리보기'를 본문으로 사용."""
    soup = BeautifulSoup(get_text(session, KICPA_MAIN), "lxml")
    found: dict[str, Article] = {}
    for a in soup.find_all("a", href=re.compile(r"boardId=noti.*bltnNo=")):
        m = re.search(r"bltnNo=(\d+)", a["href"])
        if not m:
            continue
        no = m.group(1)
        text = clean(a.get_text(" "))
        url = urljoin(KICPA_MAIN, a["href"]).replace("/kr_mobile/", "/kr_pc/")
        art = found.get(no)
        if art is None:
            art = Article(2, "KICPA 공지사항", text, url, bltn_date(no), org="한국공인회계사회")
            found[no] = art
        # 같은 글이 '제목'만 있는 링크와 '제목+본문 미리보기' 링크로 두 번 나온다
        if len(text) > len(art.title) + 10:
            art.body = text
        elif len(text) < len(art.title):
            art.title = text
    out = []
    for art in found.values():
        if not art.published or art.published < since:
            continue
        if art.body.startswith(art.title):
            art.body = art.body[len(art.title):].strip()
        if NOISE.search(art.title):   # 외부기관 입찰·모집·제휴 안내는 감사 이슈가 아님
            continue
        out.append(art)
    return out


def collect_cpa_news(session, since: date, core, ai, exclude) -> list[Article]:
    feed = feedparser.parse(session.get(CPA_NEWS_RSS, timeout=20).content)
    out = []
    for e in feed.entries:
        pub = parse_date(e.get("published", "")) or (
            datetime(*e.published_parsed[:6]).date() if e.get("published_parsed") else None)
        if not pub or pub < since:
            continue
        title, body = clean(e.get("title", "")), strip_html(e.get("summary", ""))[:2500]
        if not is_relevant(title, body, core, ai, exclude):
            continue
        out.append(Article(2, "CPA뉴스", title, e.get("link", ""), pub,
                           body=body, org="한국공인회계사회", via="rss"))
    return out
