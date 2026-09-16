"""Render the landing hero's resting frame to a JPEG, with the same WebGL code that draws it live.

The hero (apps/web/components/landing/hero) is complete without JavaScript because the
server renders this image first: `HeroStill.tsx` shows `public/earth/still-1440.jpg`, and
the live renderer hides it once it draws. The image is the scene at rest -- Europe under
the limb, the sun rising beside the prompt -- with the copy and the prompt hidden, so it is
what the canvas paints, cover-fit at any size.

Re-run it whenever the scene changes:

    WEBGRAPH_WEB_BASE=http://localhost:3013 python tools/render_hero_still.py

It needs the web app running (any port; never :3000 while the owner uses it) and the
repository's Playwright. Headless Chromium renders WebGL2 through SwiftShader, so give it
the seconds it asks for; the result is identical to a GPU's but slower.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WEBGRAPH_WEB_BASE", "http://localhost:3013")
OUT = Path(__file__).resolve().parent.parent / "apps" / "web" / "public" / "earth" / "still-1440.jpg"
HIDE = ".hero-copy, .hero-prompt-slot, .hero-credit, header, .hero-frame { border-radius: 0 !important } .hero-copy, .hero-prompt-slot, .hero-credit, header { display: none !important }"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.goto(f"{BASE}/?field=tier:2", wait_until="networkidle", timeout=120_000)
        page.wait_for_selector("[data-hero-frame][data-field]", timeout=30_000)
        page.add_style_tag(content=HIDE)
        # The entrance settles in 1.5 s; the 2k textures follow the 512 ones. Wait for both.
        page.wait_for_timeout(9_000)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        page.locator(".hero-frame").screenshot(path=str(OUT), type="jpeg", quality=82)
        browser.close()
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
