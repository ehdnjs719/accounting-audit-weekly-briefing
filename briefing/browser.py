"""Playwright(Chromium) 헤드리스 브라우저 래퍼.

- JS 로 목록을 그리는 사이트(4대 법인, KICPA 포털) 렌더링
- Akamai 등 봇 차단으로 requests 가 403 을 받는 사이트(예: PwC) 우회
- HTML → PDF 출력
브라우저는 처음 필요할 때 한 번만 띄우고 재사용한다.
"""
from __future__ import annotations

import logging

from .http import USER_AGENT

log = logging.getLogger(__name__)


class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self.available = True

    def _ensure(self) -> bool:
        if self._ctx is not None:
            return True
        if not self.available:
            return False
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            self._ctx = self._browser.new_context(
                locale="ko-KR", user_agent=USER_AGENT, viewport={"width": 1366, "height": 900},
                extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"})
            return True
        except Exception as e:  # Playwright 미설치 등
            log.warning("Playwright 를 사용할 수 없습니다: %s", e)
            self.available = False
            return False

    def fetch(self, url: str, wait_ms: int = 3500, scroll: int = 2, timeout_ms: int = 45000) -> str | None:
        if not self._ensure():
            return None
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(wait_ms)
            for _ in range(scroll):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(800)
            return page.content()
        except Exception as e:
            log.warning("브라우저 로딩 실패 %s: %s", url, str(e)[:150])
            return None
        finally:
            page.close()

    def html_to_pdf(self, html: str, pdf_path: str, footer_label: str = "") -> None:
        if not self._ensure():
            raise RuntimeError("PDF 생성에는 Playwright(Chromium)가 필요합니다: python -m playwright install chromium")
        page = self._ctx.new_page()
        try:
            page.set_content(html, wait_until="networkidle", timeout=60000)
            page.emulate_media(media="print")
            page.pdf(
                path=pdf_path,
                format="A5",                # 모바일·태블릿 세로 화면에 맞춘 판형
                print_background=True,
                margin={"top": "14mm", "bottom": "14mm", "left": "11mm", "right": "11mm"},
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=(
                    "<div style='width:100%;font-size:7px;color:#8a94a6;padding:0 11mm;"
                    "display:flex;justify-content:space-between;font-family:sans-serif'>"
                    f"<span>{footer_label}</span>"
                    "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span></div>"),
            )
        finally:
            page.close()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._browser = self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
