"""
TechSmart submission scraper.

Uses Playwright (Firefox) to log in, navigate to each assignment's code-viewer
page, and extract every student's code + submission status.

Key DOM facts (verified from live inspector):
  - Code lives in a CodeMirror instance → extracted via JS `.CodeMirror.getValue()`
  - Student list is a custom MDL menu: li.ts-teacher-quick-grade__menu-item
  - Names are "Last, First" in span.ts-teacher-quick-grade__student-name
  - li[disabled] items have no viewable submission → skip navigation, mark not_started
  - Status is encoded in icon classes inside each list item
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

TECHSMART_BASE = "https://platform.techsmart.codes"
LOGIN_URL = f"{TECHSMART_BASE}/accounts/login/"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScrapedSubmission:
    student_name: str        # "Last, First"
    submission_url: str      # actual URL Playwright was on when code was read
    code: str                # raw student code (empty string if nothing found)
    ts_status: str           # "turned_in" | "started_not_submitted" | "not_started"


# ---------------------------------------------------------------------------
# Status inference from dropdown HTML
# ---------------------------------------------------------------------------

def _infer_status(item_html: str, is_disabled: bool) -> str:
    """
    Infer SubmissionStatus from a dropdown <li> element's HTML and disabled state.

    Icon mapping observed in the live DOM:
      disabled=true + content_paste icon  → not_started  (no navigable submission)
      ts-grade-indicator__full-grade div  → turned_in
      material-icons-outlined + assignment icon → started_not_submitted
      anything else not disabled          → not_started (fallback)
    """
    if is_disabled:
        return "not_started"
    if "ts-grade-indicator__full-grade" in item_html:
        return "turned_in"
    if "material-icons-outlined" in item_html and "assignment" in item_html:
        return "started_not_submitted"
    return "not_started"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def login(page: Page, username: str, password: str) -> None:
    """Navigate to TechSmart login and authenticate."""
    await page.goto(LOGIN_URL)
    await page.wait_for_load_state("networkidle")

    # Fill username — TechSmart uses a standard Django login form
    await page.fill('input[name="username"]', username)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"], input[type="submit"], [type="submit"]')
    await page.wait_for_load_state("networkidle")

    # Quick sanity check: if we're still on the login page, credentials failed
    if "/login" in page.url or "/accounts/login" in page.url:
        raise RuntimeError(
            "Login failed — still on login page after submit. "
            "Check your TechSmart username and password in .env"
        )


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

async def _extract_code(page: Page) -> str:
    """Pull raw code text from the CodeMirror editor via JavaScript."""
    try:
        code = await page.evaluate(
            "() => { const el = document.querySelector('.CodeMirror'); "
            "return el && el.CodeMirror ? el.CodeMirror.getValue() : ''; }"
        )
        return code or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Student list extraction
# ---------------------------------------------------------------------------

async def _get_student_list(page: Page) -> list[dict]:
    """
    Read all students from the dropdown without clicking.
    Returns a list of dicts: {name, html, is_disabled}
    """
    return await page.evaluate("""
        () => Array.from(
            document.querySelectorAll('li.ts-teacher-quick-grade__menu-item')
        ).map(li => ({
            name: (li.querySelector('span.ts-teacher-quick-grade__student-name')
                      ?.textContent ?? '').trim(),
            html: li.outerHTML,
            is_disabled: li.getAttribute('disabled') !== null
        }))
    """)


# ---------------------------------------------------------------------------
# Per-assignment scrape
# ---------------------------------------------------------------------------

async def scrape_assignment(
    page: Page,
    assignment_url: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> list[ScrapedSubmission]:
    """
    Navigate to one assignment URL and scrape every student's code.

    Navigation strategy:
      1. Land on the assignment URL (TechSmart defaults to some student).
      2. Read the full student list from the MDL dropdown (names + statuses).
      3. For each non-disabled student, open the dropdown and click their name.
         Playwright waits for the full page reload before extracting code.
      4. Disabled items → record as not_started with empty code (no submission).
    """
    await page.goto(assignment_url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector(".CodeMirror", timeout=20_000)

    # Snapshot the full student list before any navigation
    students = await _get_student_list(page)

    if not students:
        if progress_callback:
            progress_callback("  ⚠  No students found in dropdown — wrong URL?")
        return []

    results: list[ScrapedSubmission] = []
    total = len(students)

    for idx, s in enumerate(students):
        name = s["name"]
        status = _infer_status(s["html"], s["is_disabled"])
        label = f"  [{idx + 1}/{total}] {name}"

        if s["is_disabled"]:
            # No navigable submission — record empty and move on
            if progress_callback:
                progress_callback(f"{label} — no submission (skipped)")
            results.append(ScrapedSubmission(
                student_name=name,
                submission_url=assignment_url,
                code="",
                ts_status="not_started",
            ))
            continue

        if progress_callback:
            progress_callback(f"{label}...")

        # Open the MDL dropdown
        await page.click("#ts-teacher-quick-grade-student-button")
        # Wait for the menu to be visible
        await page.wait_for_selector(
            "ul.mdl-menu.mdl-js-menu", state="visible", timeout=5_000
        )

        # Find and click this student's <span> inside the menu
        # We locate all name spans that are currently visible in the open menu
        all_name_spans = page.locator(
            "ul.mdl-menu li.ts-teacher-quick-grade__menu-item "
            "span.ts-teacher-quick-grade__student-name"
        )
        count = await all_name_spans.count()
        clicked = False
        for i in range(count):
            span = all_name_spans.nth(i)
            text = await span.text_content()
            if text and text.strip() == name:
                await span.click()
                clicked = True
                break

        if not clicked:
            if progress_callback:
                progress_callback(f"{label} — could not find in menu (skipped)")
            # Close menu and continue
            await page.keyboard.press("Escape")
            results.append(ScrapedSubmission(
                student_name=name,
                submission_url=assignment_url,
                code="",
                ts_status=status,
            ))
            continue

        # Wait for full page reload to this student's submission
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector(".CodeMirror", timeout=15_000)
        # Small buffer for CodeMirror to fully render its content
        await page.wait_for_timeout(600)

        code = await _extract_code(page)
        results.append(ScrapedSubmission(
            student_name=name,
            submission_url=page.url,
            code=code,
            ts_status=status,
        ))

        if progress_callback:
            lines = len([l for l in code.splitlines() if l.strip()])
            progress_callback(f"    ✓ {lines} non-blank lines  [{status}]")

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def scrape_all_assignments(
    username: str,
    password: str,
    assignment_urls: dict[str, str],           # {assignment_id: url}
    progress_callback: Optional[Callable[[str], None]] = None,
    headless: bool = False,
) -> dict[str, list[ScrapedSubmission]]:
    """
    Log in once, then scrape every requested assignment.

    Args:
        username:          TechSmart teacher login
        password:          TechSmart teacher password
        assignment_urls:   Mapping of assignment_id → TechSmart code-viewer URL
                           Only assignments with a non-empty URL are scraped.
        progress_callback: Called with a status string after each step.
        headless:          Set True to hide the browser window entirely.

    Returns:
        Dict of {assignment_id: [ScrapedSubmission, ...]}
    """
    results: dict[str, list[ScrapedSubmission]] = {}

    async with async_playwright() as pw:
        browser: Browser = await pw.firefox.launch(headless=headless)
        context: BrowserContext = await browser.new_context()
        page: Page = await context.new_page()

        # --- Login ---
        if progress_callback:
            progress_callback("🔐 Logging in to TechSmart...")
        await login(page, username, password)
        if progress_callback:
            progress_callback("✓ Logged in.\n")

        # --- Scrape each assignment ---
        for assignment_id, url in assignment_urls.items():
            if not url or not url.strip():
                continue

            display = assignment_id.replace("_", " ").title()
            if progress_callback:
                progress_callback(f"📋 Scraping: {display}")
                progress_callback(f"   {url}")

            try:
                submissions = await scrape_assignment(page, url.strip(), progress_callback)
                results[assignment_id] = submissions
                if progress_callback:
                    progress_callback(
                        f"   ✓ Done — {len(submissions)} students\n"
                    )
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"   ✗ Error: {exc}\n")
                results[assignment_id] = []

        await browser.close()

    return results


# ---------------------------------------------------------------------------
# Quick CLI test (python -m batch.scraper)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from pathlib import Path

    # Load .env if present
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    user = os.environ.get("TECHSMART_USERNAME", "")
    pw_  = os.environ.get("TECHSMART_PASSWORD", "")
    url  = os.environ.get("TEST_ASSIGNMENT_URL", "")

    if not all([user, pw_, url]):
        print("Set TECHSMART_USERNAME, TECHSMART_PASSWORD, TEST_ASSIGNMENT_URL in .env")
    else:
        async def _test():
            res = await scrape_all_assignments(
                user, pw_, {"test_assignment": url},
                progress_callback=print, headless=False
            )
            for s in res.get("test_assignment", []):
                print(f"{s.student_name} | {s.ts_status} | {len(s.code)} chars")

        asyncio.run(_test())