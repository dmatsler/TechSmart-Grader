"""
TechSmart submission scraper.

Uses Playwright (Firefox) to log in, auto-discover assignment URLs from the
gradebook, then extract every student's code + submission status.

Key DOM facts (verified from live inspector):
  - Code lives in a CodeMirror instance → extracted via JS `.CodeMirror.getValue()`
  - Student list is a custom MDL menu: li.ts-teacher-quick-grade__menu-item
  - Names are "Last, First" in span.ts-teacher-quick-grade__student-name
  - li[disabled] items have no viewable submission → skip, mark not_started
  - Status is encoded in icon classes inside each list item
  - Gradebook column headers: th.ts-gradebook-assignments-table-header-cell
    with title in p.ts-gradebook-assignments-table-header-cell__content__title
  - Student cells: td.ts-gradebook-assignments-table-cell--assigned
  - More Actions button: button#ts-grade-info-dialog-action-menu__button
  - View item: li#ts-grade-info-dialog-action-menu__menu__list-item--view
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

TECHSMART_BASE = "https://platform.techsmart.codes"
LOGIN_URL = TECHSMART_BASE

# ---------------------------------------------------------------------------
# Mapping: internal assignment_id → TechSmart gradebook column title
# ---------------------------------------------------------------------------
ASSIGNMENT_TITLE_MAP = {
    "3_3_animating_shapes_1_technique1practice1_py":        "Animating Shapes (1)",
    "3_3_animating_shapes_2_technique1practice2_py":        "Animating Shapes (2)",
    "3_3_animating_rect_shapes_1_technique2practice1_py":   "Animating Rect Shapes (1)",
    "3_3_animating_rect_shapes_2_technique2practice2_py":   "Animating Rect Shapes (2)",
    "3_3_adjust_animation_speed_1_technique3practice1_py":  "Adjust Animation Speed (1)",
    "3_3_adjust_animation_speed_2_technique3practice2_py":  "Adjust Animation Speed (2)",
    "3_3_backgrounds_and_trails_1_technique4practice1_py":  "Backgrounds and Trails (1)",
    "3_3_backgrounds_and_trails_2_technique4practice2_py":  "Backgrounds and Trails (2)",
    "3_3_stick_dance_random_stickdancerandom_solution_py":  "Stick Dance: Random",
    "3_3_healthful_ufo_healthfulufo_solution_py":           "Healthful UFO",
    "3_3_stick_dance_smooth_stickdancesmooth_solution_py":  "Stick Dance: Smooth",
    "3_3_bouncing_ball_bouncingball_solution_py":           "Bouncing Ball",
    # Unit 3.5 — Mouse & Keyboard
    "3_5_saving_a_tuple_1_technique1practice1_py":        "Saving a Tuple (1)",
    "3_5_saving_a_tuple_2_technique1practice2_py":        "Saving a Tuple (2)",
    "3_5_follow_mouse_1_technique2practice1_py":          "Follow Mouse (1)",
    "3_5_follow_mouse_2_technique2practice2_py":          "Follow Mouse (2)",
    "3_5_check_event_key_1_technique3practice1_py":       "Check Event Key (1)",
    "3_5_check_event_key_2_technique3practice2_py":       "Check Event Key (2)",
    "3_5_move_arrow_keys_1_technique4practice1_py":       "Move With Arrow Keys (1)",
    "3_5_move_arrow_keys_2_technique4practice2_py":       "Move With Arrow Keys (2)",
    "3_5_sports_hero_sportshero_py":                      "Sports Hero",
    "3_5_virtual_jumprope_virtualjumprope_py":            "Virtual Jumprope",
    "3_5_custom_cursor_customcursor_py":                  "Custom Cursor",
    "3_5_zen_flycatcher_zenflycatcher_py":                "Zen Flycatcher",
    "3_5_color_picker_colorpicker_py":                    "Color Picker",
    "3_5_code_your_own_cyo3_5_py":                        "3.5 Code Your Own",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ScrapedSubmission:
    student_name: str
    submission_url: str
    code: str
    ts_status: str  # "turned_in" | "started_not_submitted" | "not_started"


# ---------------------------------------------------------------------------
# Status inference
# ---------------------------------------------------------------------------

def _infer_status(item_html: str, is_disabled: bool) -> str:
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
    await page.goto(LOGIN_URL)
    await page.wait_for_load_state("networkidle")

    await page.wait_for_selector(
        'input[name="username"]', state="visible", timeout=15_000
    )
    await page.click('input[name="username"]')
    await page.fill('input[name="username"]', username)

    await page.wait_for_selector(
        'input[name="password"]', state="visible", timeout=15_000
    )
    await page.click('input[name="password"]')
    await page.fill('input[name="password"]', password)

    await page.click('button[type="submit"]')

    # Wait then navigate home — bypasses any post-login redirect weirdness
    await page.wait_for_timeout(3000)
    await page.goto(TECHSMART_BASE, wait_until="networkidle")

    if "/login" in page.url or "accounts/login" in page.url:
        raise RuntimeError(
            "Login failed — still on login page. "
            "Check your TechSmart username and password in .env"
        )


# ---------------------------------------------------------------------------
# Gradebook auto-discovery
# ---------------------------------------------------------------------------

async def discover_assignment_urls(
    page: Page,
    context: BrowserContext,
    gradebook_url: str,
    assignment_ids: list[str],
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, str]:
    """
    Auto-discover /code/XXXXXXXX/ URLs for each assignment by:
      1. Reading gradebook column headers to find each assignment's column index
      2. Clicking the first assigned student cell in that column
      3. More Actions → View → grab the resulting URL
      4. Navigate back to gradebook for the next assignment
    """
    discovered: dict[str, str] = {}

    if progress_callback:
        progress_callback("  Loading gradebook...")

    await page.goto(gradebook_url, wait_until="networkidle")

    try:
        await page.wait_for_selector(
            "th.ts-gradebook-assignments-table-header-cell",
            timeout=20_000
        )
    except Exception:
        if progress_callback:
            progress_callback("  ✗ Gradebook table did not load — check gradebook URL")
        return discovered

    # Read all column headers → {title: col_index}
    col_map: dict[str, int] = await page.evaluate("""
        () => {
            const headers = Array.from(
                document.querySelectorAll(
                    'th.ts-gradebook-assignments-table-header-cell'
                )
            );
            const result = {};
            headers.forEach((th, idx) => {
                const el = th.querySelector(
                    'p.ts-gradebook-assignments-table-header-cell__content__title'
                );
                if (el) result[el.textContent.trim()] = idx;
            });
            return result;
        }
    """)

    if progress_callback:
        progress_callback(f"  Found {len(col_map)} assignment columns\n")

    for assignment_id in assignment_ids:
        ts_title = ASSIGNMENT_TITLE_MAP.get(assignment_id)
        if not ts_title:
            if progress_callback:
                progress_callback(f"  ⚠  No title mapping for {assignment_id}")
            continue

        col_idx = col_map.get(ts_title)
        if col_idx is None:
            if progress_callback:
                progress_callback(f"  ⚠  '{ts_title}' not found in gradebook")
            continue

        if progress_callback:
            progress_callback(f"  🔍 {ts_title}...")

        try:
            # Click first assigned cell in this column
            cell_found = await page.evaluate(f"""
                () => {{
                    const rows = Array.from(document.querySelectorAll(
                        'tr.ts-gradebook-assignments-table-row'
                    ));
                    for (const row of rows) {{
                        const cells = Array.from(row.querySelectorAll(
                            'td.ts-gradebook-assignments-table-cell'
                        ));
                        const cell = cells[{col_idx}];
                        if (cell && cell.classList.contains(
                            'ts-gradebook-assignments-table-cell--assigned'
                        )) {{
                            cell.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)

            if not cell_found:
                if progress_callback:
                    progress_callback(f"    ⚠  No assigned cells found")
                continue

            # Wait for More Actions button
            await page.wait_for_selector(
                "button#ts-grade-info-dialog-action-menu__button",
                state="visible", timeout=8_000
            )
            # Click More Actions
            await page.wait_for_selector(
                "button#ts-grade-info-dialog-action-menu__button",
                state="visible", timeout=8_000
            )
            await page.wait_for_timeout(500)
            await page.click("button#ts-grade-info-dialog-action-menu__button")
            await page.wait_for_timeout(800)

            # Wait for View item
            await page.wait_for_selector(
                "li#ts-grade-info-dialog-action-menu__menu__list-item--view",
                state="visible", timeout=8_000
            )

            # Click View — opens in a new tab
            async with context.expect_page() as new_page_info:
                await page.click(
                    "li#ts-grade-info-dialog-action-menu__menu__list-item--view"
                )
            new_tab = await new_page_info.value
            await new_tab.wait_for_load_state("networkidle")

            code_url = new_tab.url
            await new_tab.close()
            if "/code/" in code_url:
                discovered[assignment_id] = code_url
                if progress_callback:
                    progress_callback(f"    ✓ {code_url}")
            else:
                if progress_callback:
                    progress_callback(f"    ⚠  Unexpected URL: {code_url}")

            # Back to gradebook for next assignment
            await page.goto(gradebook_url, wait_until="networkidle")
            await page.wait_for_selector(
                "th.ts-gradebook-assignments-table-header-cell", timeout=20_000
            )
            await page.wait_for_timeout(800)

        except Exception as exc:
            if progress_callback:
                progress_callback(f"    ✗ Error: {exc}")
            try:
                await page.goto(gradebook_url, wait_until="networkidle")
                await page.wait_for_timeout(800)
            except Exception:
                pass

    return discovered


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------

async def _extract_code(page: Page) -> str:
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
    await page.goto(assignment_url, wait_until="networkidle")
    await page.wait_for_selector(".CodeMirror", timeout=20_000)
    # Extra settle time — TechSmart's MDL buttons need time to become interactive
    await page.wait_for_timeout(1500)

    students = await _get_student_list(page)
    if not students:
        if progress_callback:
            progress_callback("  ⚠  No students found in dropdown")
        return []

    results: list[ScrapedSubmission] = []
    total = len(students)

    for idx, s in enumerate(students):
        name = s["name"]
        status = _infer_status(s["html"], s["is_disabled"])
        label = f"  [{idx + 1}/{total}] {name}"

        if s["is_disabled"]:
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

        # Attempt click — reload page and retry once if it times out
        _click_ok = False
        for _attempt in range(2):
            try:
                await page.click("#ts-teacher-quick-grade-student-button",
                                 timeout=15_000)
                await page.wait_for_selector(
                    "ul.mdl-menu.mdl-js-menu"
                    "[for='ts-teacher-quick-grade-student-button']",
                    state="visible", timeout=5_000
                )
                _click_ok = True
                break
            except Exception:
                if _attempt == 0:
                    # First failure — reload and try once more
                    try:
                        await page.goto(assignment_url, wait_until="networkidle")
                        await page.wait_for_selector(".CodeMirror", timeout=15_000)
                        await page.wait_for_timeout(2000)
                    except Exception:
                        pass
                else:
                    break

        if not _click_ok:
            if progress_callback:
                progress_callback(f"{label} — click failed after reload (skipped)")
            results.append(ScrapedSubmission(
                student_name=name,
                submission_url=assignment_url,
                code="",
                ts_status=status,
            ))
            continue

        all_name_spans = page.locator(
            "ul.mdl-menu[for='ts-teacher-quick-grade-student-button'] "
            "li.ts-teacher-quick-grade__menu-item "
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
                progress_callback(f"{label} — not found in menu (skipped)")
            await page.keyboard.press("Escape")
            results.append(ScrapedSubmission(
                student_name=name,
                submission_url=assignment_url,
                code="",
                ts_status=status,
            ))
            continue

        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector(".CodeMirror", timeout=15_000)
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
    gradebook_url: str,
    assignment_ids: list[str],
    progress_callback: Optional[Callable[[str], None]] = None,
    headless: bool = False,
) -> dict[str, list[ScrapedSubmission]]:
    """
    Full pipeline: login → auto-discover URLs → scrape all assignments.

    Args:
        username:        TechSmart teacher login
        password:        TechSmart teacher password
        gradebook_url:   Stable gradebook URL (set once per unit)
        assignment_ids:  Which assignments to scrape
        progress_callback: Status updates
        headless:        Hide browser if True
    """
    results: dict[str, list[ScrapedSubmission]] = {}

    async with async_playwright() as pw:
        browser: Browser = await pw.firefox.launch(headless=headless)
        context: BrowserContext = await browser.new_context()
        page: Page = await context.new_page()

        if progress_callback:
            progress_callback("🔐 Logging in to TechSmart...")
        await login(page, username, password)
        if progress_callback:
            progress_callback("✓ Logged in.\n")

        if progress_callback:
            progress_callback("📖 Auto-discovering assignment URLs from gradebook...")
        assignment_urls = await discover_assignment_urls(
            page, context, gradebook_url, assignment_ids, progress_callback
        )
        if progress_callback:
            progress_callback(
                f"✓ Discovered {len(assignment_urls)}/{len(assignment_ids)} URLs\n"
            )

        for assignment_id, url in assignment_urls.items():
            display = ASSIGNMENT_TITLE_MAP.get(assignment_id, assignment_id)
            if progress_callback:
                progress_callback(f"📋 Scraping: {display}")

            try:
                submissions = await scrape_assignment(page, url, progress_callback)
                results[assignment_id] = submissions
                if progress_callback:
                    progress_callback(f"   ✓ Done — {len(submissions)} students\n")
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"   ✗ Error: {exc}\n")
                results[assignment_id] = []

            # Breathing pause between assignments — lets TechSmart settle
            await page.wait_for_timeout(2000)

        await browser.close()

    return results