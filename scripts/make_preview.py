"""README 용 미리보기 이미지(docs/preview.png) 생성: python scripts/make_preview.py output/latest.html"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

src = Path(sys.argv[1] if len(sys.argv) > 1 else "output/latest.html").resolve()
dst = Path(__file__).resolve().parents[1] / "docs" / "preview.png"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 430, "height": 900}, device_scale_factor=2)
    page.goto(src.as_uri(), wait_until="networkidle")
    page.add_style_tag(content="body{padding:14px}")
    page.screenshot(path=str(dst), clip={"x": 0, "y": 0, "width": 430, "height": 900})
    b.close()
print(dst)
