"""
src/ajaa/browser/allowlist.py

Navigation Route Interceptor and Allowlist (PRD Section 23.6 / Invariant I10).

Ensures the browser never navigates outside the per-application allowed domain,
protecting against malicious redirects in job postings.
"""
from __future__ import annotations

import urllib.parse
from typing import Set


class DisallowedNavigationError(Exception):
    """Raised when navigation outside the allowlist is intercepted."""
    pass


class NavigationAllowlist:
    """
    Maintains permitted origins and hosts for an active application session.
    """

    def __init__(self, apply_url: str, extra_allowed_hosts: set[str] | None = None) -> None:
        self.apply_url = apply_url
        parsed = urllib.parse.urlparse(apply_url)
        self.primary_host = parsed.netloc.lower()
        self.allowed_hosts: Set[str] = {self.primary_host}

        if extra_allowed_hosts:
            for h in extra_allowed_hosts:
                self.allowed_hosts.add(h.lower())

        # Standard trusted CDNs / subresources that forms load
        self.allowed_resource_hosts: Set[str] = {
            "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "assets.greenhouse.io",
            "boards.cdn.greenhouse.io",
        }

    def is_navigation_allowed(self, url: str) -> bool:
        """
        Check if a top-level page navigation to url is permitted.
        Only URLs matching the primary host or explicit allowlist are permitted.
        """
        if url.startswith("about:blank") or url.startswith("data:"):
            return True

        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            return True  # Relative URL navigation

        # Strip port if present
        host_without_port = host.split(":")[0]

        # Exact match
        if host in self.allowed_hosts or host_without_port in self.allowed_hosts:
            return True

        # Allow subdomain navigation under primary host (e.g. login.greenhouse.io for greenhouse.io)
        for allowed in self.allowed_hosts:
            if host_without_port.endswith("." + allowed):
                return True

        return False

    def verify_navigation(self, url: str) -> None:
        """Raise DisallowedNavigationError if url is not allowed."""
        if not self.is_navigation_allowed(url):
            raise DisallowedNavigationError(
                f"Navigation blocked by security allowlist (Invariant I10): "
                f"Target '{url}' is outside permitted hosts: {sorted(list(self.allowed_hosts))}"
            )
