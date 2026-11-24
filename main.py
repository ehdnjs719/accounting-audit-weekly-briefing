"""주간 회계·감사 인사이트 파이프라인 진입점.

사용 예)
  python main.py                      # 수집 → 요약 → PDF 저장 → 메일 발송
  python main.py --no-email           # 메일 없이 PDF 만
  python main.py --no-llm --no-state  # 빠른 테스트 (규칙 기반 요약, 발송 이력 미기록)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from briefing.browser import Browser
from briefing.collectors import (collect_big4, collect_cpa_news, collect_fsc, collect_fss,
                                 collect_kicpa_notices, search_google_news)
from briefing.http import make_session
from briefing.mailer import send_report
from briefing.models import SourceStatus
from briefing.processing import SeenStore, assign_uids, dedupe_same_url, mark_duplicates, score
from briefing.report import build_sections, render
from briefing.summarizer import build_top3, summarize

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
log = logging.getLogger("briefing")


def parse_args():
    p = argparse.ArgumentParser(description="주간 회계·감사 인사이트 브리핑 생성기")
    p.add_argument("--days", type=int, help="수집 기간(일). 기본: config.yaml lookback_days")
    p.add_argument("--output-dir", help="PDF 저장 폴더 (기본: OUTPUT_DIR 환경변수 → config.yaml)")
    p.add_argument("--no-email", action="store_true", help="메일 발송 생략")
    p.add_argument("--no-llm", action="store_true", help="Claude API 를 쓰지 않고 규칙 기반 요약")
    p.add_argument("--no-browser", action="store_true", help="Playwright 렌더링 없이 수집 (PDF 는 필요)")
    p.add_argument("--no-state", action="store_true", help="발송 이력(state/seen.json)을 읽거나 쓰지 않음")
    p.add_argument("--baseline", choices=["auto", "on", "off"], default="auto",
                   help="초기 기준 게시물 섹션 포함 여부 (auto: 최초 실행일 때만)")
    p.add_argument("--html-out", help="렌더링한 HTML 도 저장할 경로 (예: docs/latest.html)")
    return p.parse_args()


def run_source(name, fn, statuses, fallback=None):
    try:
        items = fn()
        statuses.append(SourceStatus(name, True, len(items)))
        return items
    except Exception as e:
        log.exception("%s 수집 실패", name)
        statuses.append(SourceStatus(name, False, 0, f"{type(e).__name__}: {str(e)[:90]}"))
        if fallback:
            items = fallback()
            statuses.append(SourceStatus(f"{name} → Google News 대체", True, len(items)))
            return items
        return []


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    now = datetime.now(KST)
    today = now.date()
    days = args.days or cfg["lookback_days"]
    since = today - timedelta(days=days)
    until = today

    seen = SeenStore(ROOT / "state" / "seen.json")
    baseline_on = args.baseline == "on" or (args.baseline == "auto" and not args.no_state and seen.first_run)
    collect_since = today - timedelta(days=cfg["baseline_days"]) if baseline_on else since
    collect_days = (today - collect_since).days
    kw, ex = cfg["keywords"]["regulator"], cfg["keywords"]["exclude"]
    core, ai = cfg["keywords"]["core"], cfg["keywords"]["ai"]
    lim = cfg["limits"]
    log.info("수집 기간 %s ~ %s (기준 게시물 %s)", since, until, "포함" if baseline_on else "미포함")

    session = make_session()
    statuses: list[SourceStatus] = []
    with Browser() as browser:
        if args.no_browser:
            browser.available = False
        b = browser if browser.available else None

        gq = lambda q, src, org: lambda: search_google_news(session, q, collect_days, 1, src, org, lim["google_news_per_query"])
        arts = []
        arts += run_source("금융감독원 보도자료", lambda: collect_fss(session, collect_since, kw, ex), statuses,
                           gq("금융감독원 (회계 OR 감리 OR 외부감사 OR 내부회계)", "금융감독원 관련 보도", "금융감독원"))
        arts += run_source("금융위원회 보도자료", lambda: collect_fsc(session, collect_since, kw, ex), statuses,
                           gq("금융위원회 (회계 OR 감리 OR 외부감사 OR 회계기준)", "금융위원회 관련 보도", "금융위원회"))
        arts += run_source("KICPA 공지사항", lambda: collect_kicpa_notices(session, collect_since, ex), statuses)
        arts += run_source("KICPA CPA뉴스(RSS)", lambda: collect_cpa_news(session, collect_since, core, ai, ex), statuses)
        try:
            # 언론 보강 검색은 '이번 주' 범위로만 (기준 게시물은 홈페이지 원문으로 충분)
            arts += collect_big4(session, b, collect_since, days, core, ai, ex,
                                 lim["google_news_per_query"], statuses)
        except Exception as e:
            log.exception("4대 법인 수집 실패")
            statuses.append(SourceStatus("4대 회계법인", False, 0, str(e)[:100]))

        arts = dedupe_same_url(arts)
        if not args.no_state and not seen.first_run:
            before = len(arts)
            arts = [a for a in arts if seen.is_new(a.url)]
            log.info("지난주까지 발송된 글 %d건 제외", before - len(arts))
        weights = cfg["weights"]
        for a in arts:
            a.score = score(a, weights, ex, today)
            a.is_baseline = bool(a.published and a.published < since)

        # 섹션별 상한 적용 (점수순)
        def cap(items, n):
            return sorted(items, key=lambda a: a.score, reverse=True)[:n]
        weekly = [a for a in arts if not a.is_baseline]
        s3 = []
        for org in {a.org for a in weekly if a.section == 3}:
            s3 += cap([a for a in weekly if a.section == 3 and a.org == org], lim["section3_per_firm"] + 2)
        # 섹션 2: 협회 공지(주요 활동)는 기사와 점수 경쟁에서 밀리지 않도록 별도 자리 확보
        notices = cap([a for a in weekly if a.section == 2 and a.source == "KICPA 공지사항"], 4)
        news2 = cap([a for a in weekly if a.section == 2 and a.source != "KICPA 공지사항"],
                    lim["section2"] - len(notices))
        weekly = cap([a for a in weekly if a.section == 1], lim["section1"]) + notices + news2 + s3
        baseline = cap([a for a in arts if a.is_baseline], 10) if baseline_on else []
        final = weekly + baseline
        assign_uids(final)
        dup_count = mark_duplicates(final)
        log.info("최종 %d건 (기준 게시물 %d건, 중복 %d건)", len(final), len(baseline), dup_count)

        model, effort = cfg["llm"]["model"], cfg["llm"]["effort"]
        if args.no_llm:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        engine = summarize(final, model, effort, cfg["llm"]["chunk_size"])
        top3 = build_top3(final, model, effort)

        sections = build_sections(final)
        # 섹션 3 은 요약 후 중요도 기준으로 법인당 상한 재적용
        for s in sections:
            if s["no"] == 3:
                s["groups"] = [(org, items[:lim["section3_per_firm"]]) for org, items in s["groups"]]
                s["arts"] = [a for _, items in s["groups"] for a in items]
        ctx = dict(title=f"{today} 주간 회계·감사 브리핑", report_date=today, since=since, until=until,
                   sections=sections, top3=top3, dup_count=dup_count,
                   baseline=[a for a in baseline], baseline_days=cfg["baseline_days"],
                   statuses=statuses, engine=engine, generated_at=now.strftime("%Y-%m-%d %H:%M"))
        html = render("report.html.j2", **ctx)
        if args.html_out:
            Path(args.html_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.html_out).write_text(html, encoding="utf-8")

        out_dir = Path(os.path.expanduser(args.output_dir or os.getenv("OUTPUT_DIR") or cfg["output_dir"]))
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = out_dir / cfg["filename_pattern"].format(date=today.isoformat())
        browser.available = True  # PDF 는 항상 Chromium 사용
        browser.html_to_pdf(html, str(pdf_path), footer_label=f"주간 회계·감사 브리핑 · {today}")
        log.info("PDF 저장: %s", pdf_path)

    if not args.no_email:
        mail_html = render("email.html.j2", filename=pdf_path.name, **ctx)
        text = "\n".join([f"[주간 회계·감사 브리핑] {today}", ""] +
                         [f"{i}. {t['headline']}\n   {t['art'].url}" for i, t in enumerate(top3, 1)] +
                         ["", "상세 내용은 첨부 PDF를 확인하세요."])
        top_head = top3[0]["headline"] if top3 else "이번 주 동향"
        try:
            send_report(f"[주간 회계·감사 브리핑] {today} | {top_head}", mail_html, text, pdf_path)
        except Exception:
            log.exception("메일 발송 실패")
            return 2
    if not args.no_state:
        seen.add(final, today)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
