from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

SECTION_NAMES = {
    1: "금융감독원 & 금융위원회 보도자료",
    2: "한국공인회계사회(KICPA)",
    3: "4대 회계법인 인사이트",
}


@dataclass
class Article:
    section: int                 # 1, 2, 3
    source: str                  # 예: "금융감독원 보도자료", "CPA뉴스", "삼정KPMG 인사이트"
    title: str
    url: str
    published: date | None = None
    body: str = ""               # 요약에 쓰는 본문(일부)
    org: str = ""                # 기관/법인명 (섹션 3 그룹핑용)
    via: str = "site"            # site | rss | browser | google_news
    # 가공 결과
    summary: list[str] = field(default_factory=list)
    implication: str = ""
    score: float = 0.0
    importance: int = 0          # LLM 이 매긴 1~10 중요도
    is_baseline: bool = False    # 최초 실행 시 '기준 게시물'
    dup_of: "Article | None" = None
    dup_refs: list["Article"] = field(default_factory=list)
    uid: str = ""

    @property
    def location(self) -> str:
        """중복 안내 문구에 쓰는 '섹션 N · 출처' 표기."""
        return f"섹션 {self.section} · {self.source}"


@dataclass
class SourceStatus:
    name: str
    ok: bool
    count: int = 0
    note: str = ""
