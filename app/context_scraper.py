"""
Context Scraper — scrapes assignment requirements, starter code, and
solution code directly from TechSmart and caches them locally.

How it works:
  1. Navigate the gradebook to auto-discover all assignment column headers.
  2. For each assignment, navigate to its page and extract:
       - Requirements text
       - Starter code (the template given to students)
       - Solution code URL → navigate and extract solution code
  3. Hash each piece of content. On subsequent runs, only re-scrape if
     the live content hash differs from the cached hash (change detection).
  4. Cache is stored as context_cache_{unit_slug}.json in the project root.

Usage (from batch runner, before grading):
    from app.context_scraper import refresh_context_cache, load_context_cache
    await refresh_context_cache(
        unit_slug="3_5",
        gradebook_url="https://...",
        username="...",
        password="...",
        progress_callback=print,
    )
    cache = load_context_cache("3_5")
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TECHSMART_BASE = "https://platform.techsmart.codes"
CACHE_DIR = _ROOT  # cache files live in project root alongside configs

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(unit_slug: str) -> Path:
    return CACHE_DIR / f"context_cache_{unit_slug}.json"


def load_context_cache(unit_slug: str) -> dict[str, dict]:
    """Load cached assignment contexts. Returns empty dict if no cache exists."""
    path = _cache_path(unit_slug)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("assignments", {})


def _save_cache(unit_slug: str, assignments: dict[str, dict]) -> None:
    data = {
        "unit_slug": unit_slug,
        "last_updated": datetime.now().isoformat(),
        "assignments": assignments,
    }
    _cache_path(unit_slug).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

async def _login(page, username: str, password: str) -> None:
    """Login using the same robust flow as the student scraper."""
    await page.goto(TECHSMART_BASE)
    await page.wait_for_load_state("networkidle")

    # If already logged in, skip
    if "/login" not in page.url and "accounts/login" not in page.url:
        try:
            await page.wait_for_selector('input[name="username"]', timeout=3_000)
        except Exception:
            return  # Already logged in, no login form visible

    await page.wait_for_selector('input[name="username"]', state="visible", timeout=15_000)
    await page.click('input[name="username"]')
    await page.fill('input[name="username"]', username)

    await page.wait_for_selector('input[name="password"]', state="visible", timeout=15_000)
    await page.click('input[name="password"]')
    await page.fill('input[name="password"]', password)

    await page.click('button[type="submit"]')
    await page.wait_for_timeout(3000)
    await page.goto(TECHSMART_BASE, wait_until="networkidle")

    if "/login" in page.url or "accounts/login" in page.url:
        raise RuntimeError("Login failed — check TechSmart credentials in .env")


async def _extract_code_from_page(page) -> str:
    """Extract code from a TechSmart code page (CodeMirror editor)."""
    try:
        code = await page.evaluate(
            "() => { const el = document.querySelector('.CodeMirror'); "
            "return el && el.CodeMirror ? el.CodeMirror.getValue() : ''; }"
        )
        return (code or "").strip()
    except Exception:
        return ""


async def _extract_requirements(page) -> str:
    """Extract assignment requirements text from an assignment page."""
    try:
        # TechSmart assignment pages have instructions/requirements in
        # various containers — try several selectors
        selectors = [
            ".ts-assignment-instructions",
            ".ts-coding-instructions",
            "[class*='instructions']",
            "[class*='requirements']",
            ".ts-lesson-content",
            "main",
        ]
        for selector in selectors:
            el = page.locator(selector).first
            if await el.count() > 0:
                text = await el.inner_text()
                if text and len(text.strip()) > 20:
                    return text.strip()
        # Fallback: get all visible text from the page body
        return await page.inner_text("body")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Assignment discovery from gradebook
# ---------------------------------------------------------------------------

async def _discover_assignments(
    page, gradebook_url: str, progress_callback: Optional[Callable] = None
) -> list[dict]:
    """Navigate the gradebook and return a list of assignment dicts:
    [{assignment_id, title, column_index, assignment_page_url}]
    """
    await page.goto(gradebook_url, wait_until="networkidle")
    await page.wait_for_selector(
        "th.ts-gradebook-assignments-table-header-cell", timeout=20_000
    )

    assignments = await page.evaluate("""
        () => {
            const headers = Array.from(document.querySelectorAll(
                'th.ts-gradebook-assignments-table-header-cell'
            ));
            return headers.map((th, idx) => {
                const titleEl = th.querySelector(
                    'p.ts-gradebook-assignments-table-header-cell__content__title, '
                    + '[class*="title"]'
                );
                const linkEl = th.querySelector('a[href]');
                return {
                    title: titleEl ? titleEl.textContent.trim() : '',
                    href: linkEl ? linkEl.href : '',
                    col_index: idx,
                };
            }).filter(a => a.title);
        }
    """)

    if progress_callback:
        progress_callback(f"  Discovered {len(assignments)} assignment columns")

    return assignments


def _title_to_id(title: str, unit_slug: str) -> str:
    """Convert a TechSmart assignment title to an internal assignment_id slug."""
    unit_prefix = unit_slug.replace("_", ".")  # "3_5" → "3.5"
    # Remove the unit prefix from the title if present
    clean = title
    if clean.startswith(unit_prefix):
        clean = clean[len(unit_prefix):].strip()
    # Slugify: lowercase, spaces and special chars → underscores
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", clean.lower()).strip("_")
    return f"{unit_slug}_{slug}_py"


# ---------------------------------------------------------------------------
# Per-assignment context scraping
# ---------------------------------------------------------------------------

async def _scrape_assignment_context(
    page,
    context_page,   # second tab for solution code
    assignment: dict,
    cached: dict,
    progress_callback: Optional[Callable] = None,
) -> dict | None:
    """Scrape (or return cached) context for one assignment.

    Returns updated context dict, or None if nothing changed.
    """
    title = assignment["title"]
    href = assignment.get("href", "")

    if not href:
        if progress_callback:
            progress_callback(f"    ⚠ No link found for: {title}")
        return None

    # Navigate to assignment page
    try:
        await page.goto(href, wait_until="networkidle")
        await page.wait_for_timeout(800)
    except Exception as e:
        if progress_callback:
            progress_callback(f"    ✗ Could not load {title}: {e}")
        return None

    # Extract requirements
    requirements = await _extract_requirements(page)
    req_hash = _content_hash(requirements)

    # Extract starter code
    starter_code = await _extract_code_from_page(page)
    starter_hash = _content_hash(starter_code)

    # Find solution code link on the assignment page
    solution_code = ""
    solution_hash = ""
    try:
        solution_href = await page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href]'));
                const sol = links.find(a =>
                    a.textContent.toLowerCase().includes('solution') ||
                    a.href.includes('/code/')
                );
                return sol ? sol.href : '';
            }
        """)
        if solution_href:
            await context_page.goto(solution_href, wait_until="networkidle")
            await context_page.wait_for_timeout(500)
            solution_code = await _extract_code_from_page(context_page)
            solution_hash = _content_hash(solution_code)
    except Exception:
        pass

    # Check if anything changed vs cache
    assignment_id = _title_to_id(title, assignment.get("unit_slug", "unknown"))
    cached_entry = cached.get(assignment_id, {})

    changed = (
        cached_entry.get("req_hash") != req_hash
        or cached_entry.get("starter_hash") != starter_hash
        or cached_entry.get("solution_hash") != solution_hash
    )

    if not changed and cached_entry:
        if progress_callback:
            progress_callback(f"    ✓ {title} — unchanged (using cache)")
        return cached_entry

    if progress_callback:
        status = "updated" if cached_entry else "new"
        progress_callback(f"    ↻ {title} — {status}")

    return {
        "assignment_id": assignment_id,
        "title": title,
        "requirements": requirements,
        "starter_code": starter_code,
        "solution_code": solution_code,
        "req_hash": req_hash,
        "starter_hash": starter_hash,
        "solution_hash": solution_hash,
        "scraped_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def refresh_context_cache(
    unit_slug: str,
    gradebook_url: str,
    username: str,
    password: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    headless: bool = False,
) -> dict[str, dict]:
    """Scrape assignment context for an entire unit, updating the cache
    only for assignments whose content has changed.

    Returns the full updated context dict {assignment_id: context_dict}.
    """
    from playwright.async_api import async_playwright

    cached = load_context_cache(unit_slug)
    updated: dict[str, dict] = dict(cached)  # start with what we have

    if progress_callback:
        progress_callback(f"Refreshing context cache for {unit_slug}...")

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        solution_tab = await context.new_page()  # dedicated tab for solution pages

        try:
            await _login(page, username, password)

            assignments = await _discover_assignments(
                page, gradebook_url, progress_callback
            )

            for assignment in assignments:
                assignment["unit_slug"] = unit_slug
                result = await _scrape_assignment_context(
                    page, solution_tab, assignment, cached, progress_callback
                )
                if result:
                    aid = result.get("assignment_id", _title_to_id(
                        assignment["title"], unit_slug
                    ))
                    updated[aid] = result

        finally:
            await browser.close()

    _save_cache(unit_slug, updated)

    if progress_callback:
        progress_callback(
            f"Context cache saved — {len(updated)} assignments for {unit_slug}"
        )

    return updated
