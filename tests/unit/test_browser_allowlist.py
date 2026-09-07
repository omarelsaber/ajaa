"""
tests/unit/test_browser_allowlist.py

Unit tests for NavigationAllowlist enforcing Invariant I10.
"""
import pytest
from ajaa.browser.allowlist import DisallowedNavigationError, NavigationAllowlist


def test_allowlist_permits_primary_host():
    al = NavigationAllowlist("https://boards.greenhouse.io/cloudflare/jobs/12345")
    assert al.is_navigation_allowed("https://boards.greenhouse.io/cloudflare/jobs/12345")
    assert al.is_navigation_allowed("https://boards.greenhouse.io/other/path")
    assert al.is_navigation_allowed("/relative/path")
    assert al.is_navigation_allowed("about:blank")


def test_allowlist_permits_subdomains():
    al = NavigationAllowlist("https://greenhouse.io/jobs/1")
    assert al.is_navigation_allowed("https://boards.greenhouse.io/jobs/1")
    assert al.is_navigation_allowed("https://auth.greenhouse.io/login")


def test_allowlist_blocks_unauthorized_external_redirects():
    al = NavigationAllowlist("https://boards.greenhouse.io/company/jobs/123")
    assert not al.is_navigation_allowed("https://evil-phishing-site.com/steal-creds")
    assert not al.is_navigation_allowed("https://google.com")
    assert not al.is_navigation_allowed("https://greenhouse.io.attacker.org")

    with pytest.raises(DisallowedNavigationError):
        al.verify_navigation("https://evil-phishing-site.com/steal-creds")
