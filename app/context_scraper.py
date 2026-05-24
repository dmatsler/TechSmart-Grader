"""
Context Scraper — scrapes assignment REQUIREMENTS from TechSmart and
merges them into the cache. Starter code and solution code now come from
hand-curated markdown files (see load_unit_from_markdown.py); the scraper
no longer touches those fields.

Why this changed:
  The student-facing TechSmart pages don't expose solution code, and the
  "starter" the scraper was grabbing was actually whatever code was in
  the first student's editor (fully implemented submissions, not blank
  starters). This made the line-count integrity check unable to fire.
  Markdown sources for starter/solution give us a real source of truth.

How it works now:
  1. Discover assignment URLs from the gradebook (unchanged).
  2. For each assignment, navigate to its page and extract requirements
     text only.
  3. Hash the requirements. Re-scrape an assignment only when its live
     requirements hash differs from the cached hash.
  4. PRESERVE everything else in each cache entry — starter_code,
     solution_code, their hashes, and assignment_type — because those
     are populated by load_unit_from_markdown.py from the hand-curated
     unit_X_Y_solutions.md and unit_X_Y_starter_code.md files.
  5. Cache is stored as context_cache_{unit_slug}.json in the project root.

Recommended order of operations for a unit:
  1. Run load_unit_from_markdown.py first to populate starter_code,
     solution_code, and assignment_type from your markdown files.
  2. Run refresh_context_cache() to fill in requirements.
  Either order works — the two operations are independent; they update
  disjoint fields and preserve each other's work.

Usage (from batch runner, before grading):
    from app.context_scraper import refresh_context_cache, load_context_cache
    await refresh_context_cache(
        unit_slug="3_6",
        gradebook_url="https://...",
        username="...",
        password="...",
        progress_callback=print,
    )
    cache = load_context_cache("3_6")
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
    await page.wait_for_load_state("domcontentloaded")

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
    await page.goto(TECHSMART_BASE, wait_until="domcontentloaded")

    if "/login" in page.url or "accounts/login" in page.url:
        raise RuntimeError("Login failed — check TechSmart credentials in .env")


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
    page, context, gradebook_url: str, unit_slug: str,
    progress_callback: Optional[Callable] = None
) -> list[dict]:
    """Discover assignment URLs by delegating to scraper.discover_assignment_urls,
    which navigates TechSmart correctly (the gradebook column headers don't contain
    <a> tags — the assignment URL is only accessible by clicking through a student
    cell, and scraper.py already does that dance).

    Source of truth for which assignments exist in this unit:
    UNIT_REGISTRY[unit_slug]["fallback_assignments"] (you maintain this manually).

    Returns list of {title, href, assignment_id} dicts in the shape
    _scrape_assignment_context expects.
    """
    from batch.scraper import discover_assignment_urls
    from app.config_loader import UNIT_REGISTRY

    unit = UNIT_REGISTRY.get(unit_slug, {})
    fallback_assignments = unit.get("fallback_assignments", [])

    if not fallback_assignments:
        if progress_callback:
            progress_callback(
                f"  ⚠ No fallback_assignments listed for {unit_slug!r} in UNIT_REGISTRY. "
                f"Add the assignment IDs and titles to config_loader.py before running "
                f"the context refresh."
            )
        return []

    assignment_ids = [aid for aid, _ in fallback_assignments]
    title_by_id = dict(fallback_assignments)

    # Delegate URL discovery to scraper.py — its click-through navigation works
    url_by_id = await discover_assignment_urls(
        page, context, gradebook_url, assignment_ids, progress_callback
    )

    assignments = []
    for aid in assignment_ids:
        url = url_by_id.get(aid)
        if not url:
            continue  # discover_assignment_urls already logged the miss
        assignments.append({
            "title": title_by_id.get(aid, aid),
            "href": url,
            "assignment_id": aid,
        })

    if progress_callback:
        progress_callback(f"  Discovered URLs for {len(assignments)} assignments\n")

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
    assignment: dict,
    cached: dict,
    progress_callback: Optional[Callable] = None,
) -> dict | None:
    """Scrape (or return cached) REQUIREMENTS for one assignment.

    Starter code, solution code, and assignment_type are NOT touched here;
    they come from load_unit_from_markdown.py and are preserved verbatim
    from the cached entry.

    Returns updated context dict, or None if nothing changed and a cached
    entry already exists. Returns a partial new entry (just requirements
    plus metadata) when no cached entry exists yet — load_unit_from_markdown
    can fill in the code fields later.
    """
    title = assignment["title"]
    href = assignment.get("href", "")

    if not href:
        if progress_callback:
            progress_callback(f"    ⚠ No link found for: {title}")
        return None

    # Navigate to assignment page
    try:
        await page.goto(href, wait_until="domcontentloaded")
        await page.wait_for_timeout(800)
    except Exception as e:
        if progress_callback:
            progress_callback(f"    ✗ Could not load {title}: {e}")
        return None

    # Extract requirements — the only field the scraper still owns
    requirements = await _extract_requirements(page)
    req_hash = _content_hash(requirements)

    # Identify the cache slot. Prefer the assignment_id from UNIT_REGISTRY
    # (canonical) over slugifying the title (lossy).
    assignment_id = assignment.get("assignment_id") or _title_to_id(
        title, assignment.get("unit_slug", "unknown")
    )
    cached_entry = cached.get(assignment_id, {})

    # Change detection: requirements is the only field this scraper updates,
    # so a hash match on requirements means nothing has changed for us.
    if cached_entry and cached_entry.get("req_hash") == req_hash:
        if progress_callback:
            progress_callback(f"    ✓ {title} — unchanged (using cache)")
        return cached_entry

    if progress_callback:
        status = "requirements updated" if cached_entry else "new (requirements only)"
        progress_callback(f"    ↻ {title} — {status}")

    # Build the updated entry by PRESERVING everything else from the
    # cached entry (starter_code, solution_code, their hashes, the
    # assignment_type that load_unit_from_markdown set, etc.) and
    # touching only the requirements-related fields.
    updated_entry = dict(cached_entry)
    updated_entry.update({
        "assignment_id": assignment_id,
        "title": title,
        "requirements": requirements,
        "req_hash": req_hash,
        "scraped_at": datetime.now().isoformat(),
    })
    # When no markdown has been loaded yet, make sure these fields exist
    # with empty defaults so consumers don't KeyError. The markdown loader
    # will fill them in on its next run without disturbing requirements.
    updated_entry.setdefault("starter_code", "")
    updated_entry.setdefault("solution_code", "")
    updated_entry.setdefault("starter_hash", "")
    updated_entry.setdefault("solution_hash", "")
    updated_entry.setdefault("assignment_type", "")

    return updated_entry


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

        try:
            await _login(page, username, password)

            assignments = await _discover_assignments(
                page, context, gradebook_url, unit_slug, progress_callback
            )

            for assignment in assignments:
                assignment["unit_slug"] = unit_slug
                result = await _scrape_assignment_context(
                    page, assignment, cached, progress_callback
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
