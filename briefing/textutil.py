"""HTML 본문 추출, 날짜 추출, 키워드 매칭 유틸리티."""
from __future__ import annotations

import html as htmllib
import re
from datetime import date

from bs4 import BeautifulSoup

DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
EN_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    m = DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # 영문: "20 November 2026" / "November 20, 2026"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", text) or None
    if m and m.group(2).lower() in EN_MONTHS:
        try:
            return date(int(m.group(3)), EN_MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})", text)
    if m and m.group(1).lower() in EN_MONTHS:
        try:
            return date(int(m.group(3)), EN_MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            pass
    return None


def clean(text: str) -> str:
    text = htmllib.unescape(text or "")
    text = text.replace("﻿", "").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def strip_html(fragment: str) -> str:
    return clean(BeautifulSoup(fragment or "", "lxml").get_text(" "))


def meta_content(soup: BeautifulSoup, *names: str) -> str:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return clean(tag["content"])
    return ""


def find_published(html: str) -> date | None:
    """메타태그 → JSON-LD → 본문 상단 텍스트 순으로 게시일을 찾는다."""
    soup = BeautifulSoup(html, "lxml")
    d = parse_date(meta_content(
        soup, "article:published_time", "og:article:published_time", "publishDate",
        "publish-date", "pubdate", "date", "DC.date.issued", "dcterms.created",
        "PublicationDate", "publication-date", "pwcReleaseDate"))
    if d:
        return d
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        if re.search(r"publish|releasedate|created", key) and (d := parse_date(m.get("content"))):
            return d
    # JSON-LD / 내장 데이터: "datePublished":"2026-11-09" 또는 \"datePublished\": \"2026년 11월 9일\"
    for m in re.finditer(r'datePublished\W{1,8}([^"\'\\<]{6,40})', html):
        if d := parse_date(m.group(1)):
            return d
    for t in soup.find_all("time"):
        if d := parse_date(t.get("datetime") or t.get_text(" ")):
            return d
    return parse_date(extract_main_text(html)[:600])


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    t = meta_content(soup, "og:title", "twitter:title")
    if not t and soup.title:
        t = clean(soup.title.get_text())
    # "제목 | EY - Korea" 같은 꼬리 제거
    return re.split(r"\s+[|ㅣ]\s+", t)[0].strip()


# 사이트별 본문 컨테이너 (앞에 있을수록 우선). 공유 버튼·메뉴 텍스트가 섞이지 않게 한다.
BODY_SELECTORS = [
    ".krds-bd-view .n-dbdata",          # 금융감독원 보도자료
    ".board-view-wrap .body",           # 금융위원회 보도자료
    "#article-view-content-div",        # CPA뉴스
    ".cmp-text",                        # 삼정KPMG / Deloitte (AEM)
    ".text-component",                  # 삼일PwC
    ".article-body, .rich-text, .cmp-text-v2",
]


def extract_main_text(html: str, max_chars: int = 4000) -> str:
    """사이트별 본문 셀렉터 → 가장 긴 article/main 블록 → <p> 모음 순으로 본문을 찾는다."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "aside", "iframe"]):
        tag.decompose()
    for sel in BODY_SELECTORS:
        parts, seen = [], set()
        for el in soup.select(sel):
            t = clean(el.get_text(" "))
            if t and t not in seen:
                seen.add(t)
                parts.append(t)
        joined = " ".join(parts)
        if len(joined) >= 150:
            return joined[:max_chars]
    candidates = soup.select("article, main, .bd-view, .board-view, .view-cont, .cont-wrap")
    best, best_len = None, 0
    for c in candidates or [soup.body or soup]:
        txt = clean(c.get_text(" "))
        if len(txt) > best_len:
            best, best_len = txt, len(txt)
    if best_len < 200:  # 후보가 빈약하면 <p> 모음 사용
        ps = " ".join(clean(p.get_text(" ")) for p in soup.find_all("p"))
        if len(ps) > best_len:
            best = ps
    return (best or "")[:max_chars]


def description(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return meta_content(soup, "og:description", "description", "twitter:description")


def keyword_hits(text: str, keywords: list[str], exclude: list[str] | None = None) -> list[str]:
    t = text or ""
    for ex in exclude or []:
        t = t.replace(ex, " ")
    return [k for k in keywords if k.lower() in t.lower()]


def is_relevant(title: str, body: str, core: list[str], ai: list[str], exclude: list[str],
                min_body_hits: int = 2) -> bool:
    """회계·감사 관련성 판정.
    - 제목에 핵심 키워드가 있으면 채택
    - 제목에 AI 키워드 + 본문에 핵심 키워드가 있으면 채택 (AI 감사/내부통제 트렌드)
    - 본문에 서로 다른 핵심 키워드가 min_body_hits 개 이상이면 채택"""
    if keyword_hits(title, core, exclude):
        return True
    body_hits = set(keyword_hits(body, core, exclude))
    if keyword_hits(title, ai, exclude) and body_hits:
        return True
    return len(body_hits) >= min_body_hits


def normalize_title(title: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", title or "")
    t = re.sub(r"[^\w가-힣]", "", t)
    return t.lower()
