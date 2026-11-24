"""요약 · 감사인 관점 시사점 · Top 3 브리핑 생성.

- ANTHROPIC_API_KEY 가 있으면 Claude API 로 3~4줄 요약과 시사점, 중요도(1~10)를 만든다.
- 키가 없거나 호출이 실패하면 규칙 기반(본문 앞 문장 + 키워드별 시사점 템플릿)으로 대체해
  파이프라인이 절대 멈추지 않도록 한다.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .models import Article, SECTION_NAMES

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 한국 회계법인 감사본부의 시니어 매니저이자 리서치 담당자입니다.
매주 금융감독원·금융위원회·한국공인회계사회·4대 회계법인 자료를 읽고, 동료 감사인들이
출근길 5분 안에 읽을 수 있는 브리핑을 씁니다.

작성 원칙:
- 한국어, 간결한 개조식 문장(~함/~임 체 또는 명사형 종결).
- 'summary' 는 3~4개 항목. 앞 2~3개는 사실(무엇이, 언제, 누구에게, 수치), 마지막은 의미.
- 'implication' 은 감사인 관점 시사점 1~2문장: 감사계획·위험평가·내부회계 검토·
  감사위원회 커뮤니케이션·품질관리·감사 절차에 어떤 영향을 주는지 구체적으로.
- 제공된 본문에 없는 사실·수치를 지어내지 마세요. 정보가 부족하면 제목에서 확인되는 범위로만 쓰세요.
- 'importance' 는 외부감사인 실무 영향도 기준 1~10 정수.
- 반드시 JSON 만 출력하세요 (코드블록·설명 금지)."""

IMPLICATION_RULES = [
    (r"감리|지적사례|조치", "감리 지적 유형을 당기 감사계획의 유의적 위험 식별과 핵심감사사항(KAM) 검토에 반영할 필요가 있음."),
    (r"내부회계|내부통제", "내부회계관리제도 설계·운영 평가 범위와 통제 테스트 절차가 바뀌는지 확인하고 감사위원회와 사전 공유 필요."),
    (r"회계기준|IFRS|K-IFRS|기준서", "신규·개정 기준의 적용 시점과 피감사회사의 전환 준비 상태를 점검하고 관련 주석 공시 검토 절차를 보완해야 함."),
    (r"품질관리|감사인|회계법인", "감사인 품질관리 체계(ISQM) 및 독립성 점검 항목을 업데이트하고 내부 교육에 반영 권장."),
    (r"AI|인공지능|생성형|디지털", "감사 업무에 AI·데이터 분석 활용 시 결과 검증, 데이터 무결성, 문서화 기준을 함께 마련해야 함."),
    (r"공시|지속가능|ESG", "비재무 공시·인증 수요 확대에 대비해 공시 통제와 데이터 원천에 대한 이해를 감사 절차에 포함할 필요."),
    (r"회계부정|분식|신고", "부정위험 평가 시 신고 제도·제보 채널 정보를 반영하고 경영진 무력화 위험 절차를 강화할 필요."),
]


def rule_based(art: Article) -> None:
    text = art.body or art.title
    sents = [s.strip() for s in re.split(r"(?<=[.다요])\s+|\s*[□○◦▶■•ㅇㅁ①②③④⑤-]\s+", text)
             if len(s.strip()) > 15 and not s.strip().startswith("※")]
    art.summary = [s if len(s) <= 140 else s[:138].rstrip() + "…" for s in sents[:3]] or [art.title]
    default = "피감사회사 업종·거래와의 관련성을 검토하고 필요 시 감사계획 회의에서 공유 권장."
    # 제목 매칭을 우선하고, 제목에서 못 찾을 때만 본문 앞부분으로 판단
    art.implication = (next((msg for pat, msg in IMPLICATION_RULES if re.search(pat, art.title)), None)
                       or next((msg for pat, msg in IMPLICATION_RULES if re.search(pat, art.body[:500])), default))


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception as e:
        log.warning("anthropic SDK 초기화 실패: %s", e)
        return None


def _ask(client, model: str, effort: str, user: str) -> str:
    """Claude 호출. 안전 분류기 거절 시 서버측 fallback 모델로 자동 재시도하도록 설정."""
    with client.beta.messages.stream(
        model=model,
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        output_config={"effort": effort},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude 가 요청을 거절했습니다")
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("JSON 없음")
    return json.loads(m.group(0))


def summarize(arts: list[Article], model: str, effort: str, chunk_size: int = 18) -> str:
    """각 글의 summary / implication / importance 를 채운다. 사용한 엔진 이름을 반환."""
    targets = [a for a in arts if a.dup_of is None]
    client = _client()
    if client is None:
        for a in targets:
            rule_based(a)
        return "rule-based"
    engine = f"Claude ({model})"
    for i in range(0, len(targets), chunk_size):
        chunk = targets[i:i + chunk_size]
        payload = [{"id": a.uid, "section": SECTION_NAMES[a.section], "source": a.source,
                    "title": a.title, "date": str(a.published or ""), "body": a.body[:1400]} for a in chunk]
        prompt = ("다음 자료 각각에 대해 summary(3~4개 문자열 배열), implication(문자열), importance(정수)를 작성하세요.\n"
                  '출력 형식: {"items": {"<id>": {"summary": [...], "implication": "...", "importance": 7}}}\n\n'
                  + json.dumps(payload, ensure_ascii=False))
        try:
            data = _parse_json(_ask(client, model, effort, prompt)).get("items", {})
        except Exception as e:
            log.warning("Claude 요약 실패 → 규칙 기반 대체: %s", e)
            data, engine = {}, f"Claude ({model}) + rule-based"
        for a in chunk:
            d = data.get(a.uid)
            if d and d.get("summary"):
                a.summary = [str(s) for s in d["summary"]][:4]
                a.implication = str(d.get("implication", ""))
                a.importance = int(d.get("importance") or 0)
            else:
                rule_based(a)
    return engine


def build_top3(arts: list[Article], model: str, effort: str) -> list[dict]:
    primaries = [a for a in arts if a.dup_of is None and not a.is_baseline]
    ranked = sorted(primaries, key=lambda a: (a.importance * 2 + a.score + 1.5 * len(a.dup_refs)), reverse=True)
    picks = ranked[:3]
    client = _client()
    if client and picks:
        payload = [{"id": a.uid, "title": a.title, "source": a.source, "summary": a.summary,
                    "implication": a.implication, "related": [r.location for r in a.dup_refs]} for a in picks]
        prompt = ("이번 주 감사인이 가장 주목해야 할 이슈 3개입니다. 각각에 대해 headline(25자 이내 핵심 문구)과 "
                  "brief(2~3문장: 무엇이 바뀌었고 감사인은 무엇을 해야 하는지)를 작성하세요.\n"
                  '출력 형식: {"top3": [{"id": "...", "headline": "...", "brief": "..."}]}\n\n'
                  + json.dumps(payload, ensure_ascii=False))
        try:
            got = {t["id"]: t for t in _parse_json(_ask(client, model, effort, prompt)).get("top3", [])}
            return [{"art": a, "headline": got.get(a.uid, {}).get("headline") or a.title,
                     "brief": got.get(a.uid, {}).get("brief") or a.implication} for a in picks]
        except Exception as e:
            log.warning("Top3 생성 실패 → 규칙 기반: %s", e)
    return [{"art": a, "headline": a.title,
             "brief": " ".join(a.summary[:1]) + " → " + a.implication} for a in picks]
