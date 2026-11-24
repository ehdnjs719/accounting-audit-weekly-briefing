"""섹션 1: 금융감독원 / 금융위원회 보도자료.

두 사이트 모두 서버 렌더링 HTML 이라 requests + BeautifulSoup 으로 안정적으로 파싱된다.
- 최근 목록 1~N 페이지 + 키워드 검색 결과를 합쳐 후보를 만들고
- 제목에 키워드가 있으면 채택, 없으면 본문을 열어 키워드가 2개 이상일 때만 채택한다.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import get_text
from ..models import Article
from ..textutil import clean, extract_main_text, keyword_hits, parse_date

log = logging.getLogger(__name__)

FSS_LIST = "https://www.fss.or.kr/fss/bbs/B0000188/list.do"
FSC_LIST = "https://www.fsc.go.kr/no010101"
SEARCH_WORDS = ["회계", "감사", "감리", "외부감사", "내부회계"]


def _relevant(session, art: Article, keywords, exclude) -> bool:
    """본문을 채우고, 관련성이 있으면 True."""
    try:
        art.body = extract_main_text(get_text(session, art.url), 3000)
    except Exception as e:
        log.debug("본문 실패 %s: %s", art.url, e)
    if keyword_hits(art.title, keywords, exclude):
        return True
    return len(set(keyword_hits(art.body, keywords, exclude))) >= 2


def _finalize(session, cands: dict[str, Article], since: date, keywords, exclude) -> list[Article]:
    out = []
    for art in sorted(cands.values(), key=lambda a: a.published or date.min, reverse=True):
        if not art.published or art.published < since:
            continue
        if _relevant(session, art, keywords, exclude):
            out.append(art)
        time.sleep(0.3)
    return out


def collect_fss(session, since: date, keywords, exclude, pages: int = 3) -> list[Article]:
    queries = [{"menuNo": "200218", "pageIndex": p} for p in range(1, pages + 1)]
    queries += [{"menuNo": "200218", "searchCnd": "1", "searchWrd": w, "pageIndex": 1} for w in SEARCH_WORDS]
    cands: dict[str, Article] = {}
    for q in queries:
        soup = BeautifulSoup(get_text(session, FSS_LIST, params=q), "lxml")
        for tr in soup.select("table tbody tr"):
            a = tr.select_one("td.title a")
            if not a:
                continue
            m = re.search(r"nttId=(\d+)", a["href"])
            if not m:
                continue
            # 목록/검색 결과마다 붙는 pageIndex·searchWrd 파라미터를 제거해 같은 글을 하나로 합친다
            url = f"https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId={m.group(1)}&menuNo=200218"
            pub = next((d for td in tr.find_all("td") if (d := parse_date(td.get_text()))), None)
            cands.setdefault(url, Article(1, "금융감독원 보도자료", clean(a.get_text()), url, pub, org="금융감독원"))
        time.sleep(0.3)
    return _finalize(session, cands, since, keywords, exclude)


def collect_fsc(session, since: date, keywords, exclude, pages: int = 3) -> list[Article]:
    queries = [{"curPage": p} for p in range(1, pages + 1)]
    queries += [{"srchKey": "sj", "srchText": w} for w in SEARCH_WORDS]
    cands: dict[str, Article] = {}
    for q in queries:
        soup = BeautifulSoup(get_text(session, FSC_LIST, params=q), "lxml")
        for li in soup.select("div.board-list-wrap li"):
            a = li.select_one(".subject a")
            if not a:
                continue
            url = urljoin(FSC_LIST, a["href"].split("?")[0])
            title = clean(a.get("title") or a.get_text())
            day = li.select_one(".day")
            pub = parse_date(day.get_text() if day else li.get_text(" "))
            cands.setdefault(url, Article(1, "금융위원회 보도자료", title, url, pub, org="금융위원회"))
        time.sleep(0.3)
    return _finalize(session, cands, since, keywords, exclude)
