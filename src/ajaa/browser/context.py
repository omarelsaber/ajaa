"""
src/ajaa/browser/context.py

Playwright Browser Context Manager & Route Interceptor.

Ensures:
  - Navigation allowlist route interception (Invariant I10)
  - Process isolation
  - Headless/headed configuration
  - Clean lifecycle management
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from ajaa.browser.allowlist import NavigationAllowlist


@contextmanager
def create_browser_session(
    apply_url: str,
    headless: bool = True,
    extra_allowed_hosts: set[str] | None = None,
) -> Generator[tuple[Browser, BrowserContext, Page], None, None]:
    """
    Launches an isolated Playwright Chromium session with strict route filtering.
    """
    allowlist = NavigationAllowlist(apply_url, extra_allowed_hosts=extra_allowed_hosts)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )

        page = context.new_page()

        # Intercept route navigations to enforce NavigationAllowlist (Invariant I10)
        def route_interceptor(route: Any) -> None:
            url = route.request.url
            if route.request.is_navigation_request():
                if not allowlist.is_navigation_allowed(url):
                    route.abort()
                    return
            route.continue_()

        page.route("**/*", route_interceptor)

        try:
            yield browser, context, page
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
