"""Jinja2 템플릿으로 리포트 HTML / 메일 본문을 만든다."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import SECTION_NAMES, Article

TEMPLATES = Path(__file__).parent / "templates"
FIRM_ORDER = ["삼일PwC", "삼정KPMG", "안진Deloitte", "한영EY"]
SHORT = {1: "금감원·금융위", 2: "한공회", 3: "4대 법인"}

_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))


def build_sections(arts: list[Article]) -> list[dict]:
    sections = []
    for no in (1, 2, 3):
        items = sorted([a for a in arts if a.section == no and not a.is_baseline],
                       key=lambda a: (a.dup_of is not None, -(a.importance * 2 + a.score)))
        sec = {"no": no, "name": SECTION_NAMES[no], "short": SHORT[no], "arts": items}
        if no == 3:
            groups = OrderedDict((f, []) for f in FIRM_ORDER)
            for a in items:
                groups.setdefault(a.org, []).append(a)
            sec["groups"] = list(groups.items())
        sections.append(sec)
    return sections


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)
