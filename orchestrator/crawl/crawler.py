"""SiteCrawler: a working BFS crawler that produces a SiteModel for the
Planner. This is plumbing, not the "smart" part of the pipeline — no LLM
calls happen here.

Link discovery has two mechanisms:
  - `_enqueue_links`: real `<a href>` tags (works for traditional sites).
  - `_discover_via_clicks`: clicks buttons/nav-like elements and checks
    whether `page.url` changed. SPA routers (React Router, Vue Router,
    Angular Router, ...) drive in-app navigation via `history.pushState`
    under the hood, which updates `page.url` even without a full page
    reload — so this catches client-side routes that have no crawlable
    `href` at all. It does not catch a same-URL content swap (e.g. a
    tab/modal that changes what's shown without changing the URL); that
    would need tracking "virtual pages" by DOM signature instead of URL,
    which is a known remaining gap, not attempted here.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from orchestrator.schemas import ButtonInfo, FormFieldInfo, FormInfo, LinkInfo, PageInfo, SiteModel

logger = logging.getLogger(__name__)

DESTRUCTIVE_PATTERN = re.compile(r"delete|remove|cancel|deactivate", re.IGNORECASE)

# Broader than DESTRUCTIVE_PATTERN: elements the crawler must never click while
# exploring, even though they aren't "destructive" from the Planner's point of
# view. Logout/sign-out would end the authenticated crawl session mid-BFS. This
# keyword list is necessarily incomplete (other phrasings, other languages) —
# _looks_logged_out() below is the real defense, this is just a cheap first line.
_UNSAFE_TO_CLICK_PATTERN = re.compile(
    DESTRUCTIVE_PATTERN.pattern + r"|log[\s-]?(out|off)|sign[\s-]?(out|off)|disconnect|exit",
    re.IGNORECASE,
)

_MAX_CLICK_CANDIDATES_PER_PAGE = 8
# A page already exposing this many real same-origin <a href> links doesn't
# need the riskier button-click discovery — that mechanism exists for pages
# with no crawlable hrefs at all (client-side-routed SPAs), not as a bonus
# pass over pages that are already fully href-navigable.
_MIN_REAL_LINKS_TO_SKIP_CLICK_DISCOVERY = 3
# Bounds total loop iterations (clicked *and* skipped) per page, so a page
# with many icon-only or transiently-failing elements can't burn the whole
# crawl's wall-clock budget on candidates that never even get clicked.
_MAX_CLICK_CONSIDERATIONS_PER_PAGE = _MAX_CLICK_CANDIDATES_PER_PAGE * 3

# Extracts everything the Planner needs from a single page in one round trip.
_EXTRACT_JS = """
() => {
  const forms = Array.from(document.querySelectorAll('form')).map((f) => ({
    action: f.getAttribute('action'),
    method: f.getAttribute('method'),
    fields: Array.from(f.querySelectorAll('input, select, textarea')).map((el) => ({
      name: el.getAttribute('name'),
      field_type: (el.getAttribute('type') || el.tagName).toLowerCase(),
      required: el.hasAttribute('required'),
      pattern: el.getAttribute('pattern'),
      label: (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('placeholder') || null,
    })),
  }));

  const navLinks = Array.from(document.querySelectorAll('nav a[href], header a[href], [role="navigation"] a[href]'))
    .map((a) => ({ text: (a.innerText || '').trim(), href: a.getAttribute('href') }))
    .filter((l) => l.href && l.text);

  const buttons = Array.from(
    document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a.btn')
  )
    .map((b) => ({ text: (b.innerText || b.value || '').trim() }))
    .filter((b) => b.text);

  const allLinks = Array.from(document.querySelectorAll('a[href]'))
    .map((a) => a.getAttribute('href'))
    .filter(Boolean);

  return { forms, navLinks, buttons, allLinks, title: document.title };
}
"""


def _normalize_url(url: str) -> str:
    """Strips fragments and trailing slashes so equivalent URLs dedupe."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _normalize_click_discovered_url(url: str) -> str:
    """Like `_normalize_url`, but keeps a fragment that looks like a
    client-side route (starts with "/"). Hash-routed SPAs (Vue Router, old
    React Router, AngularJS) encode navigation state entirely in the
    fragment — stripping it the way `_normalize_url` does would collapse
    every distinct route down to the same base URL and silently drop them
    all as duplicates.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    fragment = parsed.fragment if parsed.fragment.startswith("/") else ""
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, fragment))


def _structural_signature(url: str, extracted: dict) -> str:
    """Collapses near-identical pages (e.g. /product/123, /product/456) into
    the same signature so BFS doesn't re-crawl 50 list-item pages as 50 pages.
    """
    path_shape = re.sub(r"\d+", "#", urlparse(url).path)

    def bucket(n: int) -> int:
        return (n // 5) * 5

    parts = [
        path_shape,
        f"forms={bucket(len(extracted['forms']))}",
        f"buttons={bucket(len(extracted['buttons']))}",
        f"navlinks={bucket(len(extracted['navLinks']))}",
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


class SiteCrawler:
    """BFS, same-origin, depth- and page-count-bounded, wall-clock-timeout-bounded."""

    def crawl(
        self,
        url: str,
        credentials: dict | None = None,
        max_depth: int = 3,
        max_pages: int = 20,
        timeout_s: int = 90,
        on_page=None,
    ) -> SiteModel:
        """`on_page`, if given, is called with each `PageInfo` as soon as
        it's crawled (for a live dashboard) — purely observational, never
        allowed to affect crawl behavior or abort it on error."""
        notes: list[str] = []
        partial = False
        pages: list[PageInfo] = []
        seen_urls: set[str] = {_normalize_url(url)}
        seen_signatures: set[str] = set()
        click_discovery_enabled = True
        origin = urlparse(url).netloc
        start_time = time.monotonic()

        def time_left() -> bool:
            return (time.monotonic() - start_time) < timeout_s

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                if credentials:
                    try:
                        self._login(page, url, credentials)
                    except (PlaywrightError, PlaywrightTimeoutError, ValueError) as exc:
                        notes.append(f"Login failed, continuing unauthenticated: {exc}")
                        partial = True

                queue: deque[tuple[str, int]] = deque([(url, 0)])

                while queue and len(pages) < max_pages and time_left():
                    current_url, depth = queue.popleft()

                    try:
                        page.goto(current_url, wait_until="networkidle", timeout=15_000)
                        extracted = page.evaluate(_EXTRACT_JS)
                    except (PlaywrightError, PlaywrightTimeoutError) as exc:
                        notes.append(f"Failed to load/extract {current_url}: {exc}")
                        partial = True
                        continue

                    signature = _structural_signature(current_url, extracted)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)

                    page_info = self._to_page_info(page, current_url, extracted, signature)
                    pages.append(page_info)
                    logger.info("Crawled %s (depth=%d, pages=%d/%d)", current_url, depth, len(pages), max_pages)
                    if on_page is not None:
                        try:
                            on_page(page_info)
                        except Exception:  # noqa: BLE001 - dashboard callback must never break a crawl
                            logger.exception("on_page callback failed, continuing crawl")

                    if depth < max_depth:
                        self._enqueue_links(extracted, current_url, origin, depth, seen_urls, queue)
                        real_link_count = self._count_same_origin_links(extracted, current_url, origin)
                        if click_discovery_enabled and real_link_count < _MIN_REAL_LINKS_TO_SKIP_CLICK_DISCOVERY:
                            logged_out = self._discover_via_clicks(
                                page, current_url, origin, depth, seen_urls, queue, time_left,
                                require_authenticated=credentials is not None,
                            )
                            if logged_out:
                                click_discovery_enabled = False
                                notes.append(
                                    "Click-based route discovery appeared to log the crawl session "
                                    "out; disabled for the remainder of the crawl."
                                )
                                partial = True

                if not time_left():
                    notes.append(f"Hit the {timeout_s}s wall-clock timeout before exhausting the crawl frontier.")
                    partial = True
                if len(pages) >= max_pages:
                    notes.append(f"Hit max_pages={max_pages} before exhausting the crawl frontier.")

                context.close()
                browser.close()
        except Exception as exc:  # noqa: BLE001 - never let a crawl failure crash the pipeline
            logger.exception("Crawl aborted with an unexpected error")
            notes.append(f"Crawl aborted with an unexpected error: {exc}")
            partial = True

        return SiteModel(start_url=url, pages=pages, partial=partial, notes=notes)

    @staticmethod
    def _to_page_info(page: Page, url: str, extracted: dict, signature: str) -> PageInfo:
        try:
            accessibility_snapshot = page.accessibility.snapshot()
        except Exception:
            accessibility_snapshot = None

        forms = [
            FormInfo(
                action=f.get("action"),
                method=f.get("method"),
                fields=[FormFieldInfo(**field) for field in f.get("fields", [])],
            )
            for f in extracted["forms"]
        ]
        nav_links = [LinkInfo(text=l["text"], href=l["href"]) for l in extracted["navLinks"]]
        buttons = [
            ButtonInfo(text=b["text"], is_destructive=bool(DESTRUCTIVE_PATTERN.search(b["text"])))
            for b in extracted["buttons"]
        ]

        return PageInfo(
            url=url,
            title=extracted.get("title", ""),
            accessibility_snapshot=accessibility_snapshot,
            forms=forms,
            nav_links=nav_links,
            buttons=buttons,
            structural_signature=signature,
        )

    @staticmethod
    def _enqueue_links(
        extracted: dict,
        current_url: str,
        origin: str,
        depth: int,
        seen_urls: set[str],
        queue: deque[tuple[str, int]],
    ) -> None:
        for href in extracted.get("allLinks", []):
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            try:
                absolute = urljoin(current_url, href)
            except ValueError:
                continue
            if urlparse(absolute).netloc != origin:
                continue
            normalized = _normalize_url(absolute)
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            queue.append((absolute, depth + 1))

    @staticmethod
    def _count_same_origin_links(extracted: dict, current_url: str, origin: str) -> int:
        """How many real, crawlable `<a href>` links this page already
        exposes (regardless of whether they're new or already seen). Used to
        decide whether click-discovery is even worth its risk on this page —
        it exists for apps with *no* crawlable hrefs at all, so a page that's
        already fully href-navigable shouldn't need it.
        """
        count = 0
        for href in extracted.get("allLinks", []):
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            try:
                absolute = urljoin(current_url, href)
            except ValueError:
                continue
            if urlparse(absolute).netloc != origin:
                continue
            count += 1
        return count

    @staticmethod
    def _looks_logged_out(page: Page) -> bool:
        """Heuristic: a visible password field showing up mid-crawl, on a
        crawl that started authenticated, is a strong signal the last click
        ended the session (logout, session expiry, etc.) regardless of what
        label the control had — this is the real defense against unsafe
        clicks, since no keyword list can cover every phrasing/language.
        """
        try:
            return page.locator('input[type="password"]').count() > 0
        except PlaywrightError:
            return False

    @staticmethod
    def _discover_via_clicks(
        page: Page,
        current_url: str,
        origin: str,
        depth: int,
        seen_urls: set[str],
        queue: deque[tuple[str, int]],
        time_left,
        require_authenticated: bool = False,
    ) -> bool:
        """Clicks a bounded set of buttons/nav-like elements to discover
        client-side routes that have no real `<a href>` at all. Never clicks
        anything destructive/logout-like or anything that would submit a
        form (see _UNSAFE_TO_CLICK_PATTERN and the form-submit check below).
        Always restores `page` to `current_url` before/after each attempt so
        one candidate's navigation can't affect the next.

        Returns True if a click appeared to log the crawl session out (only
        checked when `require_authenticated` is set) — the caller should
        stop calling this for the rest of the crawl when that happens.
        """
        try:
            candidates = page.locator(
                'nav button, header button, [role="navigation"] button, '
                'button, [role="button"], a.btn'
            )
            count = candidates.count()
        except PlaywrightError:
            return False

        tried = 0
        considered = 0
        for i in range(count):
            if tried >= _MAX_CLICK_CANDIDATES_PER_PAGE or not time_left():
                break
            if considered >= _MAX_CLICK_CONSIDERATIONS_PER_PAGE:
                break
            considered += 1

            element = candidates.nth(i)
            try:
                text = (element.inner_text(timeout=1_000) or "").strip()
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
            if not text or _UNSAFE_TO_CLICK_PATTERN.search(text):
                continue

            try:
                tag = element.evaluate("el => el.tagName.toLowerCase()")
                input_type = element.get_attribute("type")
                inside_form = element.evaluate("el => el.closest('form') !== null")
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
            # A <button> with no explicit type defaults to type="submit" when
            # inside a <form> — skip anything that could trigger a real submit.
            if input_type == "submit" or (tag == "button" and input_type is None and inside_form):
                continue

            tried += 1
            try:
                element.click(timeout=3_000)
                page.wait_for_load_state("networkidle", timeout=5_000)
            except (PlaywrightError, PlaywrightTimeoutError):
                pass

            if require_authenticated and SiteCrawler._looks_logged_out(page):
                logger.warning("Click on %r appears to have logged the crawl session out", text)
                try:
                    page.goto(current_url, wait_until="networkidle", timeout=10_000)
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass
                return True

            new_url = page.url
            if urlparse(new_url).netloc == origin:
                normalized = _normalize_click_discovered_url(new_url)
                if normalized not in seen_urls:
                    seen_urls.add(normalized)
                    queue.append((new_url, depth + 1))
                    logger.info("Discovered %s via click on %r", new_url, text)

            if _normalize_url(page.url) != _normalize_url(current_url):
                try:
                    page.goto(current_url, wait_until="networkidle", timeout=10_000)
                except (PlaywrightError, PlaywrightTimeoutError):
                    return False  # can't reliably continue trying candidates from here
        return False

    @staticmethod
    def _login(page: Page, url: str, credentials: dict) -> None:
        """Best-effort generic login.

        TODO (team): this heuristic fills the first email/username + password
        fields it finds using common selectors. Replace with an app-specific
        login flow if it doesn't resolve on the target app, or extend
        `credentials` with explicit selectors (already supported below via
        `username_selector` / `password_selector` / `submit_selector`).
        """
        login_url = credentials.get("login_url", url)
        page.goto(login_url, wait_until="networkidle", timeout=15_000)

        username = credentials.get("username") or credentials.get("email")
        password = credentials.get("password")
        if not username or not password:
            raise ValueError("credentials must include a username/email and a password")

        user_selector = credentials.get(
            "username_selector", "input[type=email], input[name*=user], input[name*=email]"
        )
        pass_selector = credentials.get("password_selector", "input[type=password]")
        submit_selector = credentials.get("submit_selector", "button[type=submit], input[type=submit]")

        page.fill(user_selector, username, timeout=5_000)
        page.fill(pass_selector, password, timeout=5_000)
        page.click(submit_selector, timeout=5_000)

        # `networkidle` alone is unreliable here: some apps chain several
        # async calls after submit (e.g. a Firebase/Identity Toolkit auth
        # round trip followed by a profile fetch and *then* the client-side
        # redirect), with gaps between them long enough for the network to
        # look briefly idle before the login actually completes. Wait for
        # the URL to actually change away from the login page first, and
        # only fall back to a bare networkidle wait if it never does (some
        # apps render the post-login view at the same URL).
        try:
            page.wait_for_url(lambda current: current != login_url, timeout=20_000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_load_state("networkidle", timeout=15_000)
