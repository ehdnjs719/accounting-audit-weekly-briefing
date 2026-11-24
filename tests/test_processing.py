from datetime import date

from briefing.collectors.big4 import date_from_url
from briefing.collectors.kicpa import bltn_date
from briefing.models import Article
from briefing.processing import mark_duplicates, similar
from briefing.summarizer import rule_based
from briefing.textutil import is_relevant, parse_date

CORE = ["회계", "감사", "감리", "내부통제", "IFRS"]
AI = ["AI", "인공지능"]


def art(section, title, d, source="src", via="site", url=None):
    return Article(section, source, title, url or f"https://x/{section}/{title}/{d}", d, via=via)


def test_parse_date_variants():
    assert parse_date("2026-11-23") == date(2026, 11, 23)
    assert parse_date("2026.11.17.") == date(2026, 11, 17)
    assert parse_date("2026년 3월 5일") == date(2026, 3, 5)
    assert parse_date("2026-11-04T17:07:00.000+09:00") == date(2026, 11, 4)
    assert parse_date("20 November 2026") == date(2026, 11, 20)
    assert parse_date("no date") is None


def test_date_from_url():
    assert date_from_url("https://www.ey.com/ko_kr/newsroom/2026/11/ey-korea-news-release-2026-11-23") == date(2026, 11, 23)
    assert date_from_url("https://kpmg.com/kr/ko/media/press-releases/2026/11/press-release-17.html") == date(2026, 11, 17)
    assert date_from_url("https://kpmg.com/kr/ko/insights/eri/2026/businessfocus-1123.html") == date(2026, 11, 23)
    assert date_from_url("https://www.pwc.com/kr/ko/insights/issue-brief/genai.html") is None


def test_month_only_urls_and_embedded_dates():
    from briefing.collectors.big4 import _month_floor
    from briefing.textutil import find_published
    assert _month_floor("https://kpmg.com/kr/ko/insights/aci/aci-monthly-newsletter-202611.html") == date(2026, 12, 1)
    assert _month_floor("https://x/perspectives/ccg-newsletter-2026-10.html") == date(2026, 11, 1)
    assert _month_floor("https://www.ey.com/ko_kr/newsroom/2026/12/x") == date(2027, 1, 1)
    html = '<script>{\\"datePublished\\": \\"2026년 11월 9일\\"}</script>'
    assert find_published(html) == date(2026, 11, 9)


def test_kicpa_bulletin_number_is_timestamp():
    assert bltn_date("11755058839387") == date(2025, 8, 13)
    assert bltn_date("garbage") is None


def test_same_issue_across_regulators_is_duplicate():
    fsc = art(1, "사업보고서 등에 대한 조사·감리결과 조치", date(2026, 11, 23), "금융위원회 보도자료")
    fss = art(1, "사업보고서 등에 대한 조사,감리결과 조치 - 제20차 금융위원회('26.11.23.) 조치 의결 -",
              date(2026, 11, 23), "금융감독원 보도자료")
    assert similar(fsc, fss)


def test_recurring_title_on_different_dates_is_not_duplicate():
    a = art(1, "사업보고서 등에 대한 조사·감리결과 조치", date(2026, 11, 23))
    b = art(1, "사업보고서 등에 대한 조사·감리결과 조치", date(2026, 10, 28))
    assert not similar(a, b)


def test_mark_duplicates_points_to_higher_priority_section():
    primary = art(2, "신설 감사인 대상 감사인 감리 설명회 개최", date(2026, 11, 19), "CPA뉴스")
    press = art(3, "신설 감사인 대상 감사인 감리 설명회 개최…품질관리 당부", date(2026, 11, 19),
                "삼일PwC 언론보도", via="google_news")
    other = art(3, "보험산업의 AI 전환", date(2026, 11, 19))
    assert mark_duplicates([press, primary, other]) == 1
    assert press.dup_of is primary and primary.dup_refs == [press]
    assert other.dup_of is None
    assert "섹션 2" in press.dup_of.location


def test_relevance_filter():
    assert is_relevant("K-IFRS 개정 안내", "", CORE, AI, [])
    assert is_relevant("AI 에이전트 도입 전략", "내부통제와 감사 절차", CORE, AI, [])
    assert not is_relevant("G-STAR 게임 산업 전망", "게임 신작", CORE, AI, [])
    assert not is_relevant("감사합니다 이벤트", "", CORE, AI, ["감사합니다"])


def test_firm_name_does_not_count_as_accounting_keyword():
    from briefing.collectors.big4 import FIRM_NAMES
    from briefing.textutil import keyword_hits
    noise = FIRM_NAMES.sub(" ", "하나증권, 이지스운용·딜로이트 안진회계법인과 '맞손'")
    signal = FIRM_NAMES.sub(" ", "삼일회계법인, 내부회계관리제도 세미나 개최")
    assert not keyword_hits(noise, CORE)
    assert keyword_hits(signal, CORE)


def test_rule_based_summary_has_implication():
    a = art(1, "외부감사 및 회계 등에 관한 규정 개정", date(2026, 11, 20))
    a.body = "금융위원회는 감리 제도를 개선한다. 개정안은 내년부터 시행된다. 감사인 지정 기준도 바뀐다."
    rule_based(a)
    assert 1 <= len(a.summary) <= 4 and a.implication
