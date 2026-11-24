"""점수화 · 섹션 간 중복 판정 · 발송 이력 관리."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from .models import Article
from .textutil import keyword_hits, normalize_title

VIA_PRIORITY = {"site": 0, "rss": 0, "browser": 0, "google_news": 1}


def assign_uids(arts: list[Article]) -> None:
    for a in arts:
        a.uid = hashlib.md5(a.url.encode()).hexdigest()[:8]


def score(art: Article, weights: dict[str, int], exclude: list[str], today: date) -> float:
    s = 0.0
    for k in keyword_hits(art.title, list(weights), exclude):
        s += weights[k] * 2
    for k in keyword_hits(art.body[:1500], list(weights), exclude):
        s += weights[k] * 0.5
    if art.section == 1:
        s += 3            # 감독당국 자료는 감사 실무 영향이 직접적
    if art.via == "google_news":
        s -= 1.5          # 2차 보도는 원문보다 낮게
    if art.published:
        s += max(0, 7 - (today - art.published).days) * 0.2
    return round(s, 2)


def _bigrams(t: str) -> set[str]:
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similar(a: Article, b: Article, max_gap_days: int = 3) -> bool:
    if a.url == b.url:
        return True
    # '사업보고서 등에 대한 조사·감리결과 조치'처럼 매 회의마다 같은 제목으로 나오는 정례 보도자료는
    # 날짜가 다르면 다른 사건이므로 중복으로 보지 않는다.
    if a.published and b.published and abs((a.published - b.published).days) > max_gap_days:
        return False
    na, nb = normalize_title(a.title), normalize_title(b.title)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return min(len(na), len(nb)) >= 12
    ga, gb = _bigrams(na), _bigrams(nb)
    jac = len(ga & gb) / max(1, len(ga | gb))
    return jac >= 0.45 or SequenceMatcher(None, na, nb).ratio() >= 0.62


def mark_duplicates(arts: list[Article]) -> int:
    """같은 이슈를 다룬 글을 찾아 '원본'(섹션 번호가 낮고 1차 출처인 글)에 연결한다.
    중복 글은 삭제하지 않고 남겨서 리포트에 '어느 섹션의 어느 글과 중복인지' 표시한다."""
    ordered = sorted(arts, key=lambda a: (a.section, VIA_PRIORITY.get(a.via, 0), -(a.score)))
    primaries: list[Article] = []
    n = 0
    for a in ordered:
        hit = next((p for p in primaries if similar(a, p)), None)
        if hit:
            a.dup_of = hit
            hit.dup_refs.append(a)
            n += 1
        else:
            primaries.append(a)
    return n


def dedupe_same_url(arts: list[Article]) -> list[Article]:
    seen, out = set(), []
    for a in arts:
        if a.url in seen:
            continue
        seen.add(a.url)
        out.append(a)
    return out


class SeenStore:
    """이미 발송한 URL 을 기록해 다음 주에 같은 글이 반복되지 않게 한다."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    @property
    def first_run(self) -> bool:
        return not self.data

    def is_new(self, url: str) -> bool:
        return url not in self.data

    def add(self, arts: list[Article], when: date) -> None:
        for a in arts:
            self.data.setdefault(a.url, when.isoformat())
        # 1년 지난 기록은 정리
        cutoff = date.fromordinal(when.toordinal() - 365).isoformat()
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
