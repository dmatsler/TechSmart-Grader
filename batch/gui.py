"""
TechSmart Batch Grader — Tkinter GUI

Run with:
    python -m batch.gui

The teacher selects a unit, pastes ONE gradebook URL (saved per unit),
configures grade runs, and clicks Grade. Flagged submissions open a
review dialog before reports are written.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar, Canvas, Entry, Frame, IntVar, Label, LabelFrame,
    Scrollbar, StringVar, Text, Tk, Toplevel, messagebox
)
import tkinter as tk
from tkinter import filedialog, ttk

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from batch.batch_runner import (
    recompute_after_review,
    run_full_pipeline,
)
from app.config_loader import UNIT_REGISTRY, get_unit_assignments
from batch.report import write_csv, write_html, write_detail_csv

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_SAVE_DIR         = _ROOT
_ACTIVE_UNIT_FILE = _SAVE_DIR / "active_unit.json"
_ACTIVE_THEME_FILE = _SAVE_DIR / "active_theme.json"
_DEFAULT_OUTPUT   = Path.home() / "Desktop" / "techsmart_grades"


def _load_active_unit() -> str:
    if _ACTIVE_UNIT_FILE.exists():
        try:
            return json.loads(_ACTIVE_UNIT_FILE.read_text()).get("unit", "3_3")
        except Exception:
            pass
    return "3_3"


def _save_active_unit(slug: str) -> None:
    _ACTIVE_UNIT_FILE.write_text(json.dumps({"unit": slug}, indent=2))


def _load_active_theme() -> str:
    """Return the saved theme name, or 'Dark Modern' if nothing's saved
    or the saved name isn't a known theme. Handles four failure modes
    silently:
      - file doesn't exist (first launch)
      - JSON malformed (manually edited, corrupted)
      - "theme" key missing from JSON
      - theme name no longer exists in THEMES (renamed/removed)
    All four fall back to the default rather than crash the launch.
    """
    if _ACTIVE_THEME_FILE.exists():
        try:
            name = json.loads(_ACTIVE_THEME_FILE.read_text()).get("theme", "")
            if name in THEMES:
                return name
        except Exception:
            pass
    return "Dark Modern"


def _save_active_theme(name: str) -> None:
    _ACTIVE_THEME_FILE.write_text(json.dumps({"theme": name}, indent=2))


def _gradebook_file(unit_slug: str) -> Path:
    return _SAVE_DIR / f"gradebook_url_{unit_slug}.json"


def _load_gradebook_url(unit_slug: str) -> str:
    f = _gradebook_file(unit_slug)
    if f.exists():
        try:
            return json.loads(f.read_text()).get("url", "")
        except Exception:
            pass
    return ""


def _save_gradebook_url(unit_slug: str, url: str) -> None:
    _gradebook_file(unit_slug).write_text(json.dumps({"url": url}, indent=2))


def _runs_file(unit_slug: str) -> Path:
    return _SAVE_DIR / f"saved_runs_{unit_slug}.json"


def _load_runs(unit_slug: str) -> list[dict]:
    f = _runs_file(unit_slug)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return [{"name": "All Assignments", "included_ids": []}]


def _save_runs(unit_slug: str, runs: list[dict]) -> None:
    _runs_file(unit_slug).write_text(json.dumps(runs, indent=2))


# ---------------------------------------------------------------------------
# Theme palettes
# ---------------------------------------------------------------------------
# Each theme is a dict mapping semantic role names (e.g. "bg", "text") to
# concrete hex colors. Adding a new theme = adding a new entry; no code
# changes elsewhere. See _restyle_widgets() for how these are applied.
#
# Notes:
#   • Progress log (log_bg/log_fg) is hardcoded dark across all themes.
#     Log output reads more like a terminal than a document; light log
#     panels feel wrong even in light themes (cf. VS Code, Xcode).
#   • Semantic colors (Grade=green, Stop=red, Delete=red) are constant
#     across themes — handled as literals in the widget code, not here.

THEMES: dict[str, dict[str, str]] = {
    "Light Modern": {
        "bg":                "#d1d5db",
        "bg_elevated":       "#ffffff",
        "text":              "#1f2937",
        "text_muted":        "#6b7280",
        "entry_bg":          "#ffffff",
        "entry_text":        "#1f2937",
        "border":            "#d1d5db",
        "button_neutral_bg": "#e0e0e0",
        "button_neutral_fg": "#1f2937",
        "button_action_bg":  "#dbeafe",
        "button_action_fg":  "#1d4ed8",
        "button_dim_bg":     "#9ca3af",
        "button_dim_fg":     "#334155",
    },
    "Dark Modern": {
        "bg":                "#1e1e1e",
        "bg_elevated":       "#252526",
        "text":              "#d4d4d4",
        "text_muted":        "#858585",
        "entry_bg":          "#3c3c3c",
        "entry_text":        "#d4d4d4",
        "border":            "#3c3c3c",
        "button_neutral_bg": "#3c3c3c",
        "button_neutral_fg": "#d4d4d4",
        "button_action_bg":  "#1e3a5f",
        "button_action_fg":  "#93c5fd",
        "button_dim_bg":     "#48484a",
        "button_dim_fg":     "#d4d4d4",
    },
}

# Constant across all themes (see note above)
LOG_BG = "#1e1e1e"
LOG_FG = "#d4d4d4"


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

class BatchGraderApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("TechSmart Batch Grader")
        root.geometry("1150x820")
        root.resizable(True, True)

        self._run_rows: list[dict] = []
        self._output_dir = StringVar(value=str(_DEFAULT_OUTPUT))
        self._active_unit = StringVar(value=_load_active_unit())

        # Theme — defaults to Dark Modern (matches current GUI look).
        # Persistence (loading saved choice on startup) added in a later commit.
        self._theme_name = _load_active_theme()
        self._theme = THEMES[self._theme_name]
        # Registry for tracked-widget restyling. _apply_theme() iterates these
        # lists. Populated as widgets are built; Commit 2 adds the actual
        # registration and the _apply_theme() / _restyle_widgets() methods.
        self._theme_widgets: dict[str, list] = {
            "bg":                [],
            "bg_elevated":       [],
            "border":            [],
            "text":              [],
            "text_muted":        [],
            "entry":             [],  # both bg + text (+ insertbackground)
            "button_neutral":    [],  # both bg + fg
            "button_action":     [],
            "button_dim":        [],
            "checkbutton":       [],  # tuples of (widget, bg_slot)
        }

        # Tracks (canvas, rect_id) pairs for the bg rectangles painted by
        # _make_panel. Theme switch updates these via canvas.itemconfig()
        # because canvas items aren't widgets — they're drawing primitives
        # addressed by ID.
        self._theme_canvas_rects: list[tuple] = []

        # Apply theme to root window (overrides macOS system bg)
        root.configure(bg=self._theme["bg"])

        # Switch ttk's theme engine off of macOS "aqua" so style.configure()
        # actually takes effect for ttk.Combobox in both macOS system modes.
        # Aqua's renderer overrides our color config when macOS is in dark
        # system mode, which is why Light Modern dropdowns were unreadable
        # on a dark-mode mac. "clam" is theme-agnostic and respects configure.
        # Bounded blast radius: ttk.Combobox is the only ttk widget in this app.
        ttk.Style().theme_use("clam")

        # Current unit's gradeable assignments — rebuilt when unit changes
        self._current_assignments: list[tuple[str, str]] = \
            get_unit_assignments(self._active_unit.get())

        self._build_unit_selector(root)
        self._build_credentials(root)
        self._build_gradebook_section(root)
        self._build_runs_section(root, _load_runs(self._active_unit.get()))
        self._build_action_row(root)
        self._build_progress(root)

        # Run one theme-apply pass after all widgets exist. This handles two
        # things that don't happen during widget construction:
        #   1. ttk.Style.configure("TCombobox", ...) — the combos get
        #      clam's defaults until configure() runs at least once.
        #   2. Idempotent re-confirmation of the registry walk, since the
        #      same theme that was used at creation time is applied here.
        self._apply_theme(self._theme_name)
    

    # -----------------------------------------------------------------------
    # Panel helper — custom replacement for tk.LabelFrame
    # -----------------------------------------------------------------------
    #
    # tk.LabelFrame on macOS uses the system "group box" renderer, which
    # partially ignores the bg parameter. To get full theme control we
    # build the equivalent visual structure manually:
    #
    #   outer Frame (border color, 1px padding)
    #     └─ inner Frame (bg_elevated, holds title + content)
    #           ├─ title row (Label, bold)
    #           └─ content Frame (where caller packs widgets)
    #
    # highlightthickness=0 and bd=0 on the inner Frame disable macOS Aqua's
    # native border rendering, which can otherwise show through as system
    # gray and defeat our bg setting.
    #
    # Returns (outer, content). Caller packs `outer` into the parent and
    # packs content widgets into `content`.

    def _make_panel(
        self, parent, title: str,
        padx: int = 8, pady: int = 6,
    ) -> tuple[tk.Frame, tk.Frame]:
        """Custom-themed equivalent of LabelFrame using a Canvas underlay.

        macOS Aqua overrides tk.Frame bg in some system/theme combinations.
        tk.Canvas is rendered entirely by Tk (not delegated to Aqua) and
        always respects bg. So we use a Canvas as the background painter
        and embed a holder Frame on top of it for content.

        Returns (outer, content). Caller packs `outer` into the parent and
        packs widgets into `content`.
        """
        outer = tk.Frame(
            parent,
            bg=self._theme["border"],
            padx=1, pady=1,
        )

        # Canvas as the background painter. We don't rely on Canvas's bg
        # parameter (Tk-on-macOS sometimes still leaks system colors through);
        # instead we draw an explicit filled rectangle covering the canvas
        # below the embedded widgets. create_rectangle is a real drawing
        # primitive and Tk cannot override it with system colors.
        painter = tk.Canvas(
            outer,
            bg=self._theme["bg_elevated"],
            highlightthickness=0, bd=0,
        )
        painter.pack(fill="both", expand=True)
        # The bg rectangle — sized initially, resized on every <Configure>.
        bg_rect_id = painter.create_rectangle(
            0, 0, 1, 1,
            fill=self._theme["bg_elevated"],
            outline="",
        )

        # Holder Frame sits on top of the canvas via create_window.
        # Title and content get packed into here normally.
        holder = tk.Frame(
            painter,
            bg=self._theme["bg_elevated"],
            highlightthickness=0, bd=0,
        )
        # NW anchor at (0,0) means holder's top-left aligns with canvas's
        # top-left. The holder will be resized by us in the <Configure> bind.
        canvas_window_id = painter.create_window(
            (0, 0), window=holder, anchor="nw",
        )

        # Title row
        title_lbl = tk.Label(
            holder, text=title,
            bg=self._theme["bg_elevated"], fg=self._theme["text"],
            font=("Helvetica", 12, "bold"),
            anchor="w",
        )
        title_lbl.pack(fill="x", padx=padx, pady=(pady, 2))

        # Content frame
        content = tk.Frame(
            holder,
            bg=self._theme["bg_elevated"],
            highlightthickness=0, bd=0,
        )
        content.pack(fill="both", expand=True, padx=padx, pady=(0, pady))

        # Two-way sizing:
        # 1. When the canvas resizes (window resize), stretch the embedded
        #    holder to fill it horizontally.
        # 2. When the holder's natural size changes (content added/removed),
        #    tell the canvas to be that tall.
        def _on_canvas_resize(event):
            # Both width AND height so the embedded holder fills the canvas
            # as it grows (lets panels with expand=True like Progress
            # actually grow vertically).
            painter.itemconfigure(canvas_window_id, width=event.width, height=event.height)
            painter.coords(bg_rect_id, 0, 0, event.width, event.height)

        def _on_holder_resize(event):
            painter.configure(height=event.height)

        painter.bind("<Configure>", _on_canvas_resize)
        holder.bind("<Configure>", _on_holder_resize)

        # Ensure the bg rectangle is drawn beneath the embedded holder
        painter.tag_lower(bg_rect_id)

        # Register for future theme switches
        self._theme_widgets["border"].append(outer)
        self._theme_widgets["bg_elevated"].append(painter)
        self._theme_widgets["bg_elevated"].append(holder)
        self._theme_widgets["bg_elevated"].append(content)
        self._theme_widgets["bg_elevated"].append(title_lbl)
        self._theme_widgets["text"].append(title_lbl)

        # Canvas item, not a widget — tracked separately, updated by
        # _apply_theme via painter.itemconfig(rect_id, fill=...).
        self._theme_canvas_rects.append((painter, bg_rect_id))

        return outer, content


    # -----------------------------------------------------------------------
    # Unit selector
    # -----------------------------------------------------------------------

    def _build_unit_selector(self, parent):
        # Wrapper Frame hosts the Active Unit panel (left, expanding) and
        # the Theme panel (right, content-width). Same pattern as
        # _populate_runs_wrapper's Grade Runs + Selected sidebar.
        self._unit_row_wrapper = Frame(parent, bg=self._theme["bg"])
        self._unit_row_wrapper.pack(fill="x", padx=10, pady=(8, 2))
        self._theme_widgets["bg"].append(self._unit_row_wrapper)

        # ── Left: Active Unit panel ─────────────────────────────────────────
        outer, frame = self._make_panel(
            self._unit_row_wrapper, " Active Unit ", padx=8, pady=6,
        )
        outer.pack(side="left", fill="x", expand=True)

        self._themed_label(frame, "Select unit to grade:").grid(
            row=0, column=0, sticky="e", padx=(0, 8)
        )

        unit_slugs  = list(UNIT_REGISTRY.keys())
        unit_labels = [UNIT_REGISTRY[s]["label"] for s in unit_slugs]

        self._unit_combo = ttk.Combobox(
            frame,
            values=unit_labels,
            state="readonly",
            width=40,
        )
        current_idx = unit_slugs.index(self._active_unit.get()) \
            if self._active_unit.get() in unit_slugs else 0
        self._unit_combo.current(current_idx)
        self._unit_combo.grid(row=0, column=1, sticky="w")
        self._unit_combo.bind("<<ComboboxSelected>>", self._on_unit_changed)

        self._themed_label(
            frame,
            "  (changing unit reloads assignment columns and gradebook URL)",
            fg_slot="text_muted",
            font=("Arial", 9),
        ).grid(row=0, column=2, sticky="w", padx=8)

        # ── Right: Theme panel (combobox added in Piece B) ──────────────────
        theme_outer, theme_frame = self._make_panel(
            self._unit_row_wrapper, " Theme ", padx=8, pady=6,
        )
        theme_outer.pack(side="right", fill="y", padx=(8, 0))

        # Populated from THEMES.keys() so adding new themes in Phase 2
        # (High Contrast variants) automatically extends the dropdown
        # without touching this method.
        theme_names = list(THEMES.keys())
        self._theme_combo = ttk.Combobox(
            theme_frame,
            values=theme_names,
            state="readonly",
            width=18,
        )
        self._theme_combo.current(theme_names.index(self._theme_name))
        self._theme_combo.pack(padx=4, pady=2)
        self._theme_combo.bind("<<ComboboxSelected>>", self._on_theme_changed)

    def _on_unit_changed(self, event=None):
        unit_slugs = list(UNIT_REGISTRY.keys())
        idx = self._unit_combo.current()
        new_slug = unit_slugs[idx]
        if new_slug == self._active_unit.get():
            return

        self._active_unit.set(new_slug)
        _save_active_unit(new_slug)

        # Reload assignments for new unit
        self._current_assignments = get_unit_assignments(new_slug)

        # Reload gradebook URL
        self._gradebook_url.set(_load_gradebook_url(new_slug))

        # Rebuild runs section with new assignment columns
        saved_runs = _load_runs(new_slug)
        self._rebuild_runs_section(saved_runs)

        # Clear the highlighted-text state so the combo doesn't sit visually
        # "still selected" after the choice is made.
        self._unit_combo.selection_clear()
    
    def _on_theme_changed(self, event=None):
        """Switch the active theme when the user picks from the dropdown."""
        new_name = self._theme_combo.get()
        if new_name == self._theme_name:
            return
        self._apply_theme(new_name)
        _save_active_theme(new_name)
        self._log_msg(f"[theme] switched to: {new_name}")
        # Clear the highlighted-text state so the combo doesn't sit visually
        # "still selected" after the choice is made.
        self._theme_combo.selection_clear()
    
    def _apply_theme(self, name: str):
        """Walk every theme-registered widget and re-color it for `name`.

        Each slot in self._theme_widgets corresponds to one or two color
        keys in the palette:
          - bg, bg_elevated, border   → widget.configure(bg=…)
          - text, text_muted          → widget.configure(fg=…)
          - entry                     → both (entry_bg + entry_text)
          - button_*                  → both (button_*_bg + button_*_fg)

        Canvas-painted bg rectangles are addressed by item ID, so they
        live in self._theme_canvas_rects and get itemconfig() not
        widget.configure().
        """
        self._theme_name = name
        self._theme = THEMES[name]
        t = self._theme  # alias for readability below

        # Root window — one-off, not in the registry.
        self.root.configure(bg=t["bg"])

        # bg-only slots
        for w in self._theme_widgets["bg"]:
            w.configure(bg=t["bg"])
        for w in self._theme_widgets["bg_elevated"]:
            w.configure(bg=t["bg_elevated"])
        for w in self._theme_widgets["border"]:
            w.configure(bg=t["border"])

        # fg-only slots
        for w in self._theme_widgets["text"]:
            w.configure(fg=t["text"])
        for w in self._theme_widgets["text_muted"]:
            w.configure(fg=t["text_muted"])

        # bg + fg slots
        for w in self._theme_widgets["entry"]:
            w.configure(
                bg=t["entry_bg"],
                fg=t["entry_text"],
                insertbackground=t["entry_text"],
                highlightbackground=t["border"],
                highlightcolor=t["border"],
            )
        for w in self._theme_widgets["button_neutral"]:
            w.configure(bg=t["button_neutral_bg"], fg=t["button_neutral_fg"])
        for w in self._theme_widgets["button_action"]:
            w.configure(bg=t["button_action_bg"], fg=t["button_action_fg"])
        for w in self._theme_widgets["button_dim"]:
            w.configure(bg=t["button_dim_bg"], fg=t["button_dim_fg"])

        # Checkbuttons — each (widget, bg_slot) pair, because per-widget bg
        # context varies (action-row checkbuttons sit on root bg, run-row
        # checkbuttons sit inside elevated panels). selectcolor matches bg
        # so the check box reads as part of its surround.
        for cb, bg_slot in self._theme_widgets["checkbutton"]:
            bg = t[bg_slot]
            cb.configure(
                bg=bg, fg=t["text"],
                selectcolor=bg,
                activebackground=bg, activeforeground=t["text"],
            )

        # Canvas-painted rectangles (item IDs, not widgets)
        for canvas, rect_id in self._theme_canvas_rects:
            canvas.itemconfig(rect_id, fill=t["bg_elevated"])

        # ttk.Combobox — using the "clam" theme engine (set in __init__),
        # which respects both configure() and map(). The map() call covers
        # state-specific styling: a state="readonly" combobox uses different
        # internal style states, and without explicit mapping those states
        # can override the base configure values.
        style = ttk.Style()
        style.configure(
            "TCombobox",
            fieldbackground=t["entry_bg"],
            background=t["bg_elevated"],
            foreground=t["entry_text"],
            arrowcolor=t["text"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", t["entry_bg"])],
            background=[("readonly", t["bg_elevated"])],
            foreground=[("readonly", t["entry_text"])],
            arrowcolor=[("readonly", t["text"])],
        )

        # Force-rebuild the dynamic Selected-sidebar counter labels with
        # current theme colors. They're recreated on every checkbox flip
        # and run rename, so we don't register them — instead we trigger
        # a rebuild here so they pick up the new theme.
        self._refresh_run_counters()

    # -----------------------------------------------------------------------
    # Themed widget helpers
    # -----------------------------------------------------------------------
    #
    # Each helper creates a widget pre-themed for the current palette and
    # registers it in the appropriate _theme_widgets slot(s) so it follows
    # future theme switches. Extra kwargs pass through to the underlying
    # tk widget unchanged (font, anchor, width, textvariable, etc.).
    #
    # Slot parameters are keyword-only (the `*` in each signature) so they
    # can't collide with regular widget kwargs and so they're explicit at
    # the call site.

    def _themed_frame(self, parent, *, slot="bg_elevated", **kwargs):
        """Frame with theme-driven bg. slot is the palette/registry key:
        'bg_elevated' for panel interiors, 'bg' for root-level layout
        frames like rows in the action area.
        """
        f = Frame(parent, bg=self._theme[slot], **kwargs)
        self._theme_widgets[slot].append(f)
        return f

    def _themed_label(self, parent, text, *,
                      fg_slot="text", bg_slot="bg_elevated", **kwargs):
        """Label with theme-driven bg + fg. fg_slot is 'text' or
        'text_muted'; bg_slot is 'bg_elevated' (default, for labels inside
        panels) or 'bg' (for labels on root-level frames).
        """
        lbl = tk.Label(
            parent, text=text,
            bg=self._theme[bg_slot], fg=self._theme[fg_slot],
            **kwargs,
        )
        self._theme_widgets[bg_slot].append(lbl)
        self._theme_widgets[fg_slot].append(lbl)
        return lbl

    def _themed_entry(self, parent, **kwargs):
        """Entry with theme-driven bg, fg, insertbackground (cursor color),
        and highlight border colors. Without explicit highlight colors,
        macOS draws the Entry's outer frame using *system* colors — so a
        Light Modern entry on a dark-mode mac picks up a heavy dark frame
        that visually clashes with the light panel.
        """
        e = Entry(
            parent,
            bg=self._theme["entry_bg"],
            fg=self._theme["entry_text"],
            insertbackground=self._theme["entry_text"],
            highlightthickness=1,
            highlightbackground=self._theme["border"],
            highlightcolor=self._theme["border"],
            **kwargs,
        )
        self._theme_widgets["entry"].append(e)
        return e

    def _themed_checkbutton(self, parent, *, bg_slot="bg_elevated", **kwargs):
        """Checkbutton with theme-driven bg, fg, selectcolor, and active
        states. bg_slot is 'bg_elevated' (default, panel interiors) or
        'bg' (action-row checkboxes on root bg).
        """
        bg = self._theme[bg_slot]
        cb = tk.Checkbutton(
            parent,
            bg=bg, fg=self._theme["text"],
            selectcolor=bg,
            activebackground=bg, activeforeground=self._theme["text"],
            **kwargs,
        )
        self._theme_widgets["checkbutton"].append((cb, bg_slot))
        return cb

    # -----------------------------------------------------------------------
    # Credentials
    # -----------------------------------------------------------------------

    def _build_credentials(self, parent):
        outer, frame = self._make_panel(parent, " TechSmart Credentials ", padx=8, pady=6)
        outer.pack(fill="x", padx=10, pady=(4,4))

        env_user, env_pass = self._read_env_credentials()

        self._themed_label(frame, "Username:").grid(
            row=0, column=0, sticky="e", padx=(0, 4)
        )
        self._username = StringVar(value=env_user)
        self._themed_entry(frame, textvariable=self._username, width=30).grid(
            row=0, column=1, padx=(0, 20)
        )

        self._themed_label(frame, "Password:").grid(
            row=0, column=2, sticky="e", padx=(0, 4)
        )
        self._password = StringVar(value=env_pass)
        self._themed_entry(
            frame, textvariable=self._password, show="*", width=30,
        ).grid(row=0, column=3)

        self._themed_label(
            frame,
            "  (Tip: set TECHSMART_USERNAME / TECHSMART_PASSWORD in .env)",
            fg_slot="text_muted",
            font=("Arial", 9),
        ).grid(row=0, column=4, padx=10, sticky="w")

    def _read_env_credentials(self) -> tuple[str, str]:
        env_path = _ROOT / ".env"
        user, pw = "", ""
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "TECHSMART_USERNAME":
                    user = v
                elif k == "TECHSMART_PASSWORD":
                    pw = v
        user = user or os.environ.get("TECHSMART_USERNAME", "")
        pw   = pw   or os.environ.get("TECHSMART_PASSWORD", "")
        return user, pw

    # -----------------------------------------------------------------------
    # Gradebook URL
    # -----------------------------------------------------------------------

    def _build_gradebook_section(self, parent):
        outer, frame = self._make_panel(
            parent,
            " Gradebook URL  (paste once — assignment URLs are discovered automatically) ",
            padx=8, pady=8,
        )
        outer.pack(fill="x", padx=10, pady=4)

        self._themed_label(frame, "Gradebook URL:").grid(
            row=0, column=0, sticky="e", padx=(0,6)
        )
        self._gradebook_url = StringVar(
            value=_load_gradebook_url(self._active_unit.get())
        )
        self._themed_entry(
            frame, textvariable=self._gradebook_url, width=70,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self._themed_label(
            frame,
            "e.g.  https://platform.techsmart.codes/gradebook/class/XXXXX/?unit_id=3&lesson_id=5",
            fg_slot="text_muted",
            font=("Arial", 9),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))
        frame.columnconfigure(1, weight=1)

    # -----------------------------------------------------------------------
    # Grade runs
    # -----------------------------------------------------------------------

    def _build_runs_section(self, parent, saved_runs: list[dict]):
        """Create the wrapper Frame once and fill it. The wrapper itself
        is a permanent fixture in the parent's pack order — only its
        contents get torn down and rebuilt on unit change.
        """
        self._runs_wrapper = Frame(parent, bg=self._theme["bg"])
        self._runs_wrapper.pack(fill="both", padx=8, pady=8)
        # Register so theme switching updates the wrapper's bg too
        self._theme_widgets["bg"].append(self._runs_wrapper)
        self._runs_parent = parent
        self._populate_runs_wrapper(saved_runs)

    def _populate_runs_wrapper(self, saved_runs: list[dict]):
        """Build the runs box + sidebar inside self._runs_wrapper.

        Called both on initial build (from _build_runs_section) and on
        every unit change (from _rebuild_runs_section). The wrapper is
        assumed to exist and be empty.
        """
        runs_outer_border, self._runs_outer = self._make_panel(
            self._runs_wrapper,
            " Grade Runs  (each row = one composite grade; "
            "check which assignments to include) ",
            padx=8, pady=6,
        )
        runs_outer_border.pack(side="left", fill="both", expand=True)

        # Right-hand sidebar — live readout of how many boxes each run has checked
        counters_outer_border, self._counters_outer = self._make_panel(
            self._runs_wrapper,
            " Selected ",
            padx=8, pady=6,
        )
        counters_outer_border.pack(side="right", fill="y", padx=(8, 0))

        # Inner frame is what we wipe-and-rebuild on every refresh
        self._counters_inner = self._themed_frame(
            self._counters_outer, slot="bg_elevated",
        )
        self._counters_inner.pack(fill="both", expand=True)

        self._init_runs_canvas()
        self._populate_header_row()
        for run in saved_runs:
            self._add_run_row(
                run.get("name", "Run"),
                set(run.get("included_ids", [])),
            )
        # Initial paint — handles the empty-runs case (each _add_run_row
        # call already triggers a refresh, but the loop is a no-op when
        # there are no saved runs).
        self._refresh_run_counters()

    def _init_runs_canvas(self):
        canvas_frame = self._themed_frame(self._runs_outer, slot="bg_elevated")
        canvas_frame.pack(fill="both", expand=True)

        h_scroll = Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

        # Canvas isn't covered by a helper (single caller; see Phase 1c.1
        # design notes) — register it inline.
        self._runs_canvas = Canvas(
            canvas_frame, height=160,
            bg=self._theme["bg_elevated"],
            xscrollcommand=h_scroll.set,
            highlightthickness=0,
        )
        self._theme_widgets["bg_elevated"].append(self._runs_canvas)
        self._runs_canvas.pack(fill="both", expand=True)
        h_scroll.config(command=self._runs_canvas.xview)

        self._runs_inner = self._themed_frame(self._runs_canvas, slot="bg_elevated")
        # Inset the content so run rows aren't flush with the canvas edge
        self._runs_canvas.create_window((10,6), window=self._runs_inner, anchor="nw")
        self._runs_inner.bind(
            "<Configure>",
            lambda e: self._runs_canvas.configure(
                scrollregion=self._runs_canvas.bbox("all")
            )
        )

        # Enable trackpad/mouse horizontal scrolling on macOS and Windows
        def _on_scroll(event):
            # macOS: delta is in units; Windows: delta is 120 per notch
            delta = 0
            if event.num == 4:          # Linux scroll left
                delta = -1
            elif event.num == 5:        # Linux scroll right
                delta = 1
            elif hasattr(event, 'delta'):
                delta = -1 if event.delta > 0 else 1
            self._runs_canvas.xview_scroll(delta, "units")

        for widget in (self._runs_canvas, self._runs_inner):
            widget.bind("<MouseWheel>",       _on_scroll)
            widget.bind("<Shift-MouseWheel>", _on_scroll)
            widget.bind("<Button-4>",         _on_scroll)
            widget.bind("<Button-5>",         _on_scroll)

    def _rebuild_runs_section(self, saved_runs: list[dict]):
        """Wipe the runs box + sidebar and rebuild them inside the existing
        wrapper. The wrapper itself stays put — destroying it would re-pack
        at the bottom of the parent and break the layout (Progress pane
        would jump above the runs section).
        """
        self._run_rows.clear()

        # Drop stale registry entries before destroying anything. Every
        # widget about to be destroyed is a descendant of self._runs_wrapper.
        # Calling .configure() on a destroyed widget throws TclError; cleaning
        # up explicitly here is more robust than wrapping _apply_theme in
        # try/except (which would also silently absorb real bugs).
        wrapper_prefix = str(self._runs_wrapper) + "."
        for slot, widgets in self._theme_widgets.items():
            if slot == "checkbutton":
                # Tuples of (widget, bg_slot) — filter by the widget's path.
                self._theme_widgets[slot] = [
                    (w, bg_slot) for w, bg_slot in widgets
                    if not str(w).startswith(wrapper_prefix)
                ]
            else:
                self._theme_widgets[slot] = [
                    w for w in widgets if not str(w).startswith(wrapper_prefix)
                ]
        self._theme_canvas_rects = [
            (c, rid) for c, rid in self._theme_canvas_rects
            if not str(c).startswith(wrapper_prefix)
        ]

        # Clear the wrapper's children but keep the wrapper itself
        for child in self._runs_wrapper.winfo_children():
            child.destroy()
        self._populate_runs_wrapper(saved_runs)

    def _populate_header_row(self):
        self._themed_label(
            self._runs_inner, "Run Name", width=18, anchor="w",
            font=("Arial", 9, "bold"),
        ).grid(row=0, column=0, padx=2, pady=6)

        # Spacer cells above the per-row [☑ All] [☐ None] buttons.
        # No header text — the buttons' meaning is self-evident from the icons.
        self._themed_label(self._runs_inner, "", width=5).grid(row=0, column=1, padx=1)
        self._themed_label(self._runs_inner, "", width=6).grid(row=0, column=2, padx=1)

        for col_idx, (_, label) in enumerate(self._current_assignments):
            self._themed_label(
                self._runs_inner, label, width=14, anchor="center",
                font=("Arial", 9, "bold"), wraplength=90,
            ).grid(row=0, column=col_idx + 3, padx=4, pady=4)

        self._themed_label(
            self._runs_inner, "", width=3,
        ).grid(row=0, column=len(self._current_assignments) + 3)

        btn_frame = self._themed_frame(self._runs_outer, slot="bg_elevated")
        btn_frame.pack(fill="x", pady=(4, 0))
        add_btn = tk.Label(
            btn_frame, text="+ Add Run",
            relief="flat", bg=self._theme["button_neutral_bg"],
            fg=self._theme["button_neutral_fg"],
            padx=8, pady=2, cursor="hand2"
        )
        add_btn.pack(side="left")
        add_btn.bind("<Button-1>", lambda e: self._add_run_row())
        # Hover effect — read normal bg from self._theme at Leave time so
        # it self-corrects after theme switch (instead of captured-at-creation).
        add_btn.bind("<Enter>", lambda e: add_btn.config(
            bg="#cccccc" if self._theme_name == "Light Modern" else "#4a4a4a"
        ))
        add_btn.bind("<Leave>", lambda e: add_btn.config(
            bg=self._theme["button_neutral_bg"]
        ))
        self._theme_widgets["button_neutral"].append(add_btn)

    def _add_run_row(self, name: str = "Run", pre_checked: set[str] | None = None):
        row_idx = len(self._run_rows) + 1
        row_record: dict = {"check_vars": {}}

        name_var = StringVar(value=name)
        # Trace fires per-keystroke as the user edits the name — sidebar
        # updates live so they see "Run A: 5 of 14" become "Warmups: 5 of 14"
        # as they type.
        name_var.trace_add("write", lambda *_: self._refresh_run_counters())
        self._themed_entry(
            self._runs_inner, textvariable=name_var, width=18,
        ).grid(row=row_idx, column=0, padx=4, pady=2)
        row_record["name_var"] = name_var

        # Per-row bulk-toggle buttons — scoped to THIS run only, never global.
        # Captured row_record via default arg to dodge late-binding closure bugs
        # (without this, all buttons would point at whichever was the last row
        # built when the lambda finally fires).
        all_btn = tk.Label(
            self._runs_inner, text="☑ All",
            relief="raised",
            bg=self._theme["button_action_bg"], fg=self._theme["button_action_fg"],
            font=("Arial", 8), padx=4, pady=1, cursor="hand2"
        )
        all_btn.grid(row=row_idx, column=1, padx=(2, 1))
        all_btn.bind("<Button-1>", lambda e, rr=row_record: self._select_all_in_run(rr))

        # Hover effect — Leave reads normal bg from self._theme so it
        # self-corrects after theme switch.
        all_btn.bind("<Enter>", lambda e: all_btn.config(
            bg="#bfdbfe" if self._theme_name == "Light Modern" else "#2a4a7a"
        ))
        all_btn.bind("<Leave>", lambda e: all_btn.config(
            bg=self._theme["button_action_bg"]
        ))
        self._theme_widgets["button_action"].append(all_btn)

        none_btn = tk.Label(
            self._runs_inner, text="☐ None",
            relief="raised",
            bg=self._theme["button_dim_bg"], fg=self._theme["button_dim_fg"],
            font=("Arial", 8), padx=4, pady=1, cursor="hand2"
        )
        none_btn.grid(row=row_idx, column=2, padx=(1, 2))
        none_btn.bind("<Button-1>", lambda e, rr=row_record: self._select_none_in_run(rr))

        none_btn.bind("<Enter>", lambda e: none_btn.config(
            bg="#6b7280" if self._theme_name == "Light Modern" else "#5a5a5c"
        ))
        none_btn.bind("<Leave>", lambda e: none_btn.config(
            bg=self._theme["button_dim_bg"]
        ))
        self._theme_widgets["button_dim"].append(none_btn)

        for col_idx, (aid, _) in enumerate(self._current_assignments):
            bv = BooleanVar(value=(pre_checked is not None and aid in pre_checked))
            # Trace fires when a checkbox is clicked OR when [All]/[None]
            # programmatically calls bv.set(...) — both paths trigger refresh.
            bv.trace_add("write", lambda *_: self._refresh_run_counters())
            cb = self._themed_checkbutton(self._runs_inner, variable=bv)
            cb.grid(row=row_idx, column=col_idx + 3, padx=2)
            row_record["check_vars"][aid] = bv

        def _delete(rr=row_record, ri=row_idx):
            # Collect widget paths BEFORE destruction so we can filter them
            # out of the theme registries. Same reasoning as the
            # _rebuild_runs_section cleanup, just scoped to one row: without
            # this, destroyed widgets stay registered and TclError fires on
            # the next theme switch — and worse, the error aborts the rest
            # of _apply_theme so widgets registered AFTER the dead one in
            # later slots (buttons, checkbuttons) silently don't update.
            doomed_paths = {str(w) for w in self._runs_inner.grid_slaves(row=ri)}
            for slot, widgets in self._theme_widgets.items():
                if slot == "checkbutton":
                    self._theme_widgets[slot] = [
                        (w, bg_slot) for w, bg_slot in widgets
                        if str(w) not in doomed_paths
                    ]
                else:
                    self._theme_widgets[slot] = [
                        w for w in widgets if str(w) not in doomed_paths
                    ]
            for widget in self._runs_inner.grid_slaves(row=ri):
                widget.destroy()
            if rr in self._run_rows:
                self._run_rows.remove(rr)
            self._refresh_run_counters()

        # tk.Label-styled-button (not tk.Button) — same pattern as every
        # other button in this app. tk.Button on macOS Aqua ignores our bg
        # config and renders with native system colors, which leaves a
        # dark patch in Light Modern (and a subtly-off patch in Dark Modern).
        # fg="red" stays as a semantic constant (delete = red, unchanged
        # across themes), but bg is theme-driven.
        del_btn = tk.Label(
            self._runs_inner, text="✕", fg="red",
            bg=self._theme["bg_elevated"],
            relief="raised", borderwidth=1,
            font=("Arial", 9), padx=6, pady=2,
            cursor="hand2",
        )
        del_btn.grid(row=row_idx, column=len(self._current_assignments) + 3, padx=(2,10))
        del_btn.bind("<Button-1>", lambda e: _delete())
        # Subtle hover — slight darken on Light Modern, slight lighten on
        # Dark Modern. Leave reads from self._theme so it self-corrects
        # after theme switch.
        del_btn.bind("<Enter>", lambda e: del_btn.config(
            bg="#dddddd" if self._theme_name == "Light Modern" else "#3a3a3a"
        ))
        del_btn.bind("<Leave>", lambda e: del_btn.config(
            bg=self._theme["bg_elevated"]
        ))
        self._theme_widgets["bg_elevated"].append(del_btn)
        row_record["del_btn"] = del_btn
        self._run_rows.append(row_record)

        self._runs_canvas.update_idletasks()
        self._runs_canvas.configure(scrollregion=self._runs_canvas.bbox("all"))
        self._refresh_run_counters()

    # -----------------------------------------------------------------------
    # Per-run select all / none helpers
    # -----------------------------------------------------------------------

    def _select_all_in_run(self, row_record: dict):
        """Check every assignment box in a single run row."""
        for bv in row_record["check_vars"].values():
            bv.set(True)

    def _select_none_in_run(self, row_record: dict):
        """Uncheck every assignment box in a single run row."""
        for bv in row_record["check_vars"].values():
            bv.set(False)

    # -----------------------------------------------------------------------
    # Per-run counter sidebar
    # -----------------------------------------------------------------------

    def _refresh_run_counters(self):
        """Wipe and rebuild the right-hand 'Selected' sidebar.

        Called whenever a checkbox flips, a run name changes, a run is
        added or deleted, OR the theme changes (via _apply_theme). Cheap
        at this scale (≤ 10 runs typical), so we rebuild rather than track
        individual labels. Labels here are NOT registered in _theme_widgets
        — they're recreated frequently, so we just read current theme
        colors directly at create-time.
        """
        # Defensive: during unit-switch teardown the inner frame is destroyed
        # and recreated. If a stray trace fires in between, bail out cleanly.
        inner = getattr(self, "_counters_inner", None)
        if inner is None:
            return
        try:
            if not inner.winfo_exists():
                return
        except tk.TclError:
            return

        # Wipe existing labels
        for w in inner.winfo_children():
            w.destroy()

        total = len(self._current_assignments)
        t = self._theme  # alias

        if not self._run_rows:
            Label(
                inner, text="(no runs)", anchor="w",
                font=("Arial", 9, "italic"),
                bg=t["bg_elevated"], fg="gray",
            ).pack(anchor="w", padx=8, pady=2)
            return

        for rr in self._run_rows:
            name = rr["name_var"].get().strip() or "Run"
            checked = sum(1 for bv in rr["check_vars"].values() if bv.get())
            Label(
                inner,
                text=f"{name}: {checked} of {total}",
                anchor="w", font=("Arial", 10),
                bg=t["bg_elevated"], fg=t["text"],
            ).pack(anchor="w", padx=8, pady=2)

    # -----------------------------------------------------------------------
    # Action row
    # -----------------------------------------------------------------------

    def _build_action_row(self, parent):
        # ── Row 1: Grade button + Stop button + output folder ────────────────
        row1 = self._themed_frame(parent, slot="bg", pady=4)
        row1.pack(fill="x", padx=10)

        self._grade_btn = tk.Label(
            row1, text="▶  Grade All Runs",
            bg="#1a7a1a", fg="white", font=("Arial", 13, "bold"),
            relief="raised", padx=20, pady=10,
            cursor="hand2"
        )
        self._grade_btn.pack(side="left")
        self._grade_btn.bind("<Button-1>", lambda e: self._start_grading())
        self._grade_btn.bind("<Enter>",
                             lambda e: self._grade_btn.config(bg="#145214"))
        self._grade_btn.bind("<Leave>",
                             lambda e: self._grade_btn.config(bg="#1a7a1a"))

        # Stop button — hidden when not grading
        self._stop_btn = tk.Label(
            row1, text="■  Stop Grading",
            bg="#b91c1c", fg="white", font=("Arial", 13, "bold"),
            relief="raised", padx=16, pady=10,
            cursor="hand2"
        )
        # Don't pack yet — only show during grading
        self._stop_btn.bind("<Button-1>", lambda e: self._request_stop())
        self._stop_btn.bind("<Enter>",
                            lambda e: self._stop_btn.config(bg="#7f1d1d"))
        self._stop_btn.bind("<Leave>",
                            lambda e: self._stop_btn.config(bg="#b91c1c"))

        self._themed_label(row1, "  Output folder:", bg_slot="bg").pack(side="left")
        self._themed_entry(
            row1, textvariable=self._output_dir, width=45,
        ).pack(side="left", padx=4)
        browse_btn = tk.Label(
            row1, text="Browse…",
            relief="flat",
            bg=self._theme["button_neutral_bg"], fg=self._theme["button_neutral_fg"],
            padx=6, pady=2, cursor="hand2"
        )
        browse_btn.pack(side="left")
        browse_btn.bind("<Button-1>", lambda e: self._browse_output())
        # Hover effect — Leave reads from self._theme so it self-corrects
        # after theme switch (was capturing _browse_normal at creation).
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(
            bg="#cccccc" if self._theme_name == "Light Modern" else "#4a4a4a"
        ))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(
            bg=self._theme["button_neutral_bg"]
        ))
        # Register browse_btn for theme switching (mechanical — the hover
        # lambdas already reference self._theme_name so they self-update).
        self._theme_widgets["button_neutral"].append(browse_btn)

        # ── Row 2: Options checkboxes ─────────────────────────────────────────
        row2 = self._themed_frame(parent, slot="bg", pady=2)
        row2.pack(fill="x", padx=10)

        self._headless_var = BooleanVar(value=False)
        self._themed_checkbutton(
            row2, text="Run browser headless (hidden)",
            variable=self._headless_var, bg_slot="bg",
        ).pack(side="left", padx=(0, 20))

        self._refresh_context_var = BooleanVar(value=False)
        self._themed_checkbutton(
            row2, text="Refresh assignment context cache",
            variable=self._refresh_context_var, bg_slot="bg",
        ).pack(side="left", padx=(0, 20))

        self._anonymize_var = BooleanVar(value=False)
        self._themed_checkbutton(
            row2, text="Anonymize student names in reports",
            variable=self._anonymize_var, bg_slot="bg",
        ).pack(side="left")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self._output_dir.set(d)

    # -----------------------------------------------------------------------
    # Progress log
    # -----------------------------------------------------------------------

    def _build_progress(self, parent):
        outer, frame = self._make_panel(parent, " Progress ", padx=6, pady=6)
        outer.pack(fill="both", expand=True, padx=10, pady=(4,8))

        self._log = Text(
            frame, font=("Courier", 10), state="disabled",
            bg=LOG_BG, fg=LOG_FG, wrap="none"
        )
        scroll_y = Scrollbar(frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

    def _log_msg(self, msg: str):
        def _do():
            # Only auto-scroll if user hasn't scrolled up (bottom fraction >= 0.95)
            at_bottom = self._log.yview()[1] >= 0.95
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            if at_bottom:
                self._log.see("end")
            self._log.configure(state="disabled")
        self.root.after(0, _do)

    # -----------------------------------------------------------------------
    # Grading orchestration
    # -----------------------------------------------------------------------

    def _start_grading(self):
        username = self._username.get().strip()
        password = self._password.get().strip()
        if not username or not password:
            messagebox.showerror("Missing credentials",
                                 "Please enter your TechSmart username and password.")
            return

        gradebook_url = self._gradebook_url.get().strip()
        if not gradebook_url:
            messagebox.showerror("Missing gradebook URL",
                                 "Please paste your TechSmart gradebook URL.")
            return

        if not self._run_rows:
            messagebox.showerror("No runs defined",
                                 "Add at least one grade run before grading.")
            return

        runs: dict[str, list[str]] = {}
        saved_runs_data = []
        for rr in self._run_rows:
            run_name = rr["name_var"].get().strip() or "Run"
            included = [aid for aid, bv in rr["check_vars"].items() if bv.get()]
            if included:
                runs[run_name] = included
                saved_runs_data.append({"name": run_name, "included_ids": included})

        if not runs:
            messagebox.showerror("No assignments selected",
                                 "Check at least one assignment in at least one run.")
            return

        unit_slug = self._active_unit.get()
        _save_gradebook_url(unit_slug, gradebook_url)
        _save_runs(unit_slug, saved_runs_data)

        assignment_ids = list({aid for ids in runs.values() for aid in ids})
        output_dir = Path(self._output_dir.get().strip() or str(_DEFAULT_OUTPUT))
        headless = self._headless_var.get()

        # Show stop button + swap grade button appearance
        self._grade_btn.configure(text="⏳ Grading…", bg="#555555")
        self._stop_btn.pack(side="left", padx=(8, 0))
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        # Cancellation plumbing — stored on self for the stop button to reach
        self._grading_loop = None   # set inside thread once loop is created
        self._cancel_event = None   # asyncio.Event — set when stop clicked
        self._anonymize = self._anonymize_var.get()

        refresh_context = self._refresh_context_var.get()
        thread = threading.Thread(
            target=self._grading_thread,
            args=(username, password, gradebook_url,
                  assignment_ids, runs, unit_slug, output_dir, headless, refresh_context),
            daemon=True,
        )
        thread.start()

    def _request_stop(self):
        """Called when the Stop button is clicked. Signals the grading loop
        to stop gracefully and write reports with whatever's been graded."""
        if self._grading_loop is None or self._cancel_event is None:
            return
        self._log_msg("\n⏹  Stop requested — finishing in-flight tasks and writing reports...")
        # Schedule the event.set() call on the grading loop from main thread
        self._grading_loop.call_soon_threadsafe(self._cancel_event.set)
        self._stop_btn.configure(text="⏹ Stopping…", bg="#7f1d1d")

    def _grading_thread(
        self, username, password, gradebook_url,
        assignment_ids, runs, unit_slug, output_dir, headless,
        refresh_context=False
    ):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._grading_loop = loop  # expose to stop button
            self._cancel_event = asyncio.Event()  # created on this loop

            all_students, counters = loop.run_until_complete(
                run_full_pipeline(
                    username=username,
                    password=password,
                    gradebook_url=gradebook_url,
                    assignment_ids=assignment_ids,
                    runs=runs,
                    unit_slug=unit_slug,
                    refresh_context=refresh_context,
                    progress_callback=self._log_msg,
                    headless=headless,
                    cancel_event=self._cancel_event,
                )
            )
            loop.close()
            self._grading_loop = None

            # Print summary block
            self._print_summary(counters)

            # Check for flagged submissions
            flagged = [
                (student_name, student_result, ar)
                for student_name, student_result in all_students.items()
                for ar in student_result.assignment_results
                if ar.pending
            ]

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if flagged:
                self._log_msg(
                    f"\n⚠  {len(flagged)} submission(s) need review "
                    "before reports can be written."
                )
                # Open review dialog on the main thread, then continue
                done_event = threading.Event()
                self.root.after(
                    0,
                    lambda: self._open_review_dialog(
                        flagged, all_students, runs, unit_slug,
                        output_dir, timestamp, done_event
                    )
                )
                done_event.wait()   # block until teacher dismisses the dialog
                # Re-compute grades with confirmed scores
                recompute_after_review(all_students, runs, unit_slug)
            else:
                self._write_reports(all_students, runs, output_dir, timestamp)

        except Exception as exc:
            import traceback
            self._log_msg(f"\n❌ Fatal error: {exc}")
            self._log_msg(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror(
                "Error", f"Grading failed:\n{exc}"
            ))
        finally:
            self.root.after(0, self._restore_idle_ui)

    def _restore_idle_ui(self):
        """Return the UI to its idle state after grading finishes/stops."""
        self._grade_btn.configure(text="▶  Grade All Runs", bg="#1a7a1a")
        self._stop_btn.pack_forget()
        self._stop_btn.configure(text="■  Stop Grading", bg="#b91c1c")

    def _print_summary(self, counters: dict[str, int]) -> None:
        """Print the final grading summary block to the progress log."""
        total = sum(counters.values())
        graded = counters.get("graded", 0)
        pct = (graded / total * 100) if total else 0.0
        self._log_msg("")
        self._log_msg("=" * 50)
        self._log_msg("GRADING SUMMARY")
        self._log_msg("=" * 50)
        self._log_msg(f"  ✓ Successfully graded:    {graded} / {total}  ({pct:.1f}%)")
        self._log_msg(f"  ⚠ Flagged / needs review: {counters.get('flagged', 0)}")
        self._log_msg(f"  ✗ API errors:             {counters.get('api_errors', 0)}")
        self._log_msg(f"  ⊘ Not started (auto 0):   {counters.get('not_started', 0)}")
        self._log_msg(f"  ⊘ Cancelled:              {counters.get('cancelled', 0)}")
        if counters.get("errors", 0):
            self._log_msg(f"  ✗ Other errors:           {counters.get('errors', 0)}")
        self._log_msg("=" * 50)
        self._log_msg("")

    # -----------------------------------------------------------------------
    # Flagged submission review dialog
    # -----------------------------------------------------------------------

    def _open_review_dialog(
        self, flagged, all_students, runs, unit_slug,
        output_dir, timestamp, done_event
    ):
        points_map: dict[int, int] = {0: 0, 1: 50, 2: 75, 3: 100}

        dialog = Toplevel(self.root)
        dialog.title(f"⚠ Review {len(flagged)} Flagged Submission(s) Before Writing Reports")
        dialog.geometry("1050x640")
        dialog.configure(bg="white")   # force white — overrides macOS dark mode
        dialog.grab_set()   # modal — must dismiss before main window responds

        # ── Header ──────────────────────────────────────────────────────────
        header_frame = Frame(dialog, bg="#fffbeb", pady=10)
        header_frame.pack(fill="x", padx=12, pady=(10, 4))
        Label(
            header_frame,
            text=f"⚠  {len(flagged)} submission(s) were flagged for integrity review.",
            bg="#fffbeb", font=("Arial", 12, "bold"), fg="#92400e"
        ).pack(anchor="w", padx=10)
        Label(
            header_frame,
            text="Review each one below. Set the correct score using the dropdown, "
                 "then click 'Write Reports' when done.\n"
                 "Submissions you don't change will keep the grader's computed score.",
            bg="#fffbeb", font=("Arial", 10), fg="#78350f", justify="left"
        ).pack(anchor="w", padx=10, pady=(4, 0))

        # ── Scrollable table ─────────────────────────────────────────────────
        table_frame = Frame(dialog, bg="white")
        table_frame.pack(fill="both", expand=True, padx=12, pady=8)

        canvas = Canvas(table_frame, bg="white", highlightthickness=0)
        scrollbar = Scrollbar(table_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = Frame(canvas, bg="white")
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # ── Vertical trackpad/mousewheel scrolling ──────────────────────────
        def _on_scroll(event):
            delta = 0
            if event.num == 4:
                delta = -1           # Linux scroll up
            elif event.num == 5:
                delta = 1            # Linux scroll down
            elif hasattr(event, "delta"):
                # macOS: delta is typically ±1/±2 per tick; Windows: ±120
                if abs(event.delta) >= 120:
                    delta = -int(event.delta / 120)
                else:
                    delta = -int(event.delta)
            if delta != 0:
                canvas.yview_scroll(delta, "units")

        # Bind to both canvas and inner frame so the event fires anywhere
        # the mouse pointer might be over the table
        for widget in (canvas, inner, dialog):
            widget.bind("<MouseWheel>", _on_scroll)
            widget.bind("<Shift-MouseWheel>", _on_scroll)
            widget.bind("<Button-4>", _on_scroll)
            widget.bind("<Button-5>", _on_scroll)

        # Column headers
        col_widths = [18, 22, 12, 10, 45, 14]
        headers = ["Student", "Assignment", "TS Status",
                   "Score", "Flag Reason(s)", "Override Score"]
        for c, (h, w) in enumerate(zip(headers, col_widths)):
            tk.Label(
                inner, text=h, width=w, anchor="w",
                font=("Arial", 9, "bold"),
                relief="ridge", bg="#1d4ed8", fg="white", padx=4
            ).grid(row=0, column=c, padx=1, pady=1, sticky="nsew")

        # Override vars — one IntVar per flagged submission
        override_vars: list[tuple] = []  # (student_result, ar, IntVar)

        for row_num, (student_name, student_result, ar) in enumerate(flagged, start=1):
            bg_color = "#ffffff"  # force white — avoids system dark mode bleed

            tk.Label(inner, text=student_name, width=18, anchor="w",
                  bg=bg_color, fg="#1f2937", relief="groove",
                  font=("Arial", 9), padx=4
                  ).grid(row=row_num, column=0, padx=1, pady=1, sticky="nsew")

            tk.Label(inner, text=ar.assignment_title, width=24, anchor="w",
                  bg=bg_color, fg="#1f2937", relief="groove",
                  font=("Arial", 9), padx=4, wraplength=170
                  ).grid(row=row_num, column=1, padx=1, pady=1, sticky="nsew")

            tk.Label(inner, text=ar.ts_status, width=12, anchor="center",
                  bg=bg_color, fg="#1f2937", relief="groove", font=("Arial", 9)
                  ).grid(row=row_num, column=2, padx=1, pady=1, sticky="nsew")

            tk.Label(inner, text=f"{ar.rubric_score}/3  ({ar.points}pt)",
                  width=12, anchor="center",
                  bg=bg_color, fg="#1f2937", relief="groove", font=("Arial", 9)
                  ).grid(row=row_num, column=3, padx=1, pady=1, sticky="nsew")

            reasons_text = (
                "\n".join(f"• {r[:90]}" for r in ar.flag_reasons)
                if ar.flag_reasons else "(no reason recorded — possible API error)"
            )
            tk.Label(inner, text=reasons_text, width=48, anchor="w",
                  bg=bg_color, fg="#92400e", relief="groove",
                  font=("Arial", 8), justify="left", wraplength=340, padx=4
                  ).grid(row=row_num, column=4, padx=1, pady=1, sticky="nsew")

            # Score override dropdown
            override_var = IntVar(value=ar.rubric_score)
            score_options = [
                f"{score} / 3  ({pts} pts)"
                for score, pts in sorted(points_map.items())
            ]
            combo = ttk.Combobox(
                inner, values=score_options,
                width=16, state="readonly"
            )
            combo.current(ar.rubric_score)   # pre-select computed score
            combo.grid(row=row_num, column=5, padx=4, pady=2)

            override_vars.append((student_result, ar, override_var, combo))

        # ── Footer buttons ───────────────────────────────────────────────────
        footer = Frame(dialog, pady=8, bg="white")
        footer.pack(fill="x", padx=12)

        def _on_write():
            # Apply overrides
            for student_result, ar, _, combo in override_vars:
                selected_idx = combo.current()
                new_score = sorted(points_map.keys())[selected_idx]
                ar.rubric_score = new_score
                ar.points = points_map[new_score]
                ar.pending = False   # confirmed

            dialog.destroy()
            # Write reports from the main thread after dialog closes
            self.root.after(
                0,
                lambda: self._write_reports(
                    all_students, runs, output_dir, timestamp
                )
            )
            done_event.set()

        def _on_cancel():
            # Write reports anyway with pending scores as-is
            # (pending rows excluded from grade averages)
            dialog.destroy()
            self.root.after(
                0,
                lambda: self._write_reports(
                    all_students, runs, output_dir, timestamp
                )
            )
            done_event.set()

        # tk.Label-as-button pattern: native tk.Button on macOS ignores bg/fg
        # because the OS draws system Aqua buttons. Using Label with raised
        # relief + manual click binding gives us full color control.

        confirm_btn = tk.Label(
            footer,
            text="✔  Confirm All & Write Reports",
            bg="#16a34a", fg="white", font=("Arial", 11, "bold"),
            relief="raised", padx=20, pady=12, cursor="hand2",
            width=30, height=2
        )
        confirm_btn.pack(side="left", padx=(0, 12))
        confirm_btn.bind("<Button-1>", lambda e: _on_write())
        # Hover darkens slightly — same pattern as the main Grade button
        confirm_btn.bind("<Enter>", lambda e: confirm_btn.config(bg="#15803d"))
        confirm_btn.bind("<Leave>", lambda e: confirm_btn.config(bg="#16a34a"))

        cancel_btn = tk.Label(
            footer,
            text="Skip Review — Write Reports Now\n(pending stay excluded from grades)",
            bg="#64748b", fg="white", font=("Arial", 11, "bold"),
            relief="raised", padx=20, pady=12, cursor="hand2",
            width=30, height=2
        )
        cancel_btn.pack(side="left")
        cancel_btn.bind("<Button-1>", lambda e: _on_cancel())
        cancel_btn.bind("<Enter>", lambda e: cancel_btn.config(bg="#475569"))
        cancel_btn.bind("<Leave>", lambda e: cancel_btn.config(bg="#64748b"))

    # -----------------------------------------------------------------------
    # Report writing
    # -----------------------------------------------------------------------

    def _write_reports(self, all_students, runs, output_dir, timestamp):
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            csv_path    = output_dir / f"grades_{timestamp}.csv"
            html_path   = output_dir / f"grades_{timestamp}.html"
            detail_path = output_dir / f"grades_detail_{timestamp}.csv"

            # ── Anonymization (local mapping only — never shared) ────────────
            # If the anonymize checkbox was ticked, build a mapping from real
            # student name → "Student1-Last, Student1-First" and write reports
            # with the anonymized data. The mapping is saved to a clearly
            # labeled local file so you can decode later if needed.
            if getattr(self, "_anonymize", False):
                all_students_anon, mapping = self._anonymize_students(all_students)
                mapping_path = output_dir / f"DO_NOT_SHARE_student_names_{timestamp}.json"
                import json as _json
                mapping_path.write_text(
                    _json.dumps(mapping, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                write_csv(all_students_anon, runs, csv_path)
                write_html(all_students_anon, runs, html_path)
                write_detail_csv(all_students_anon, detail_path)
                self._log_msg(f"\n🔒 Reports anonymized. Mapping saved locally to:")
                self._log_msg(f"   {mapping_path}")
                self._log_msg(f"   ⚠  KEEP THIS FILE PRIVATE — do not share it.")
            else:
                write_csv(all_students, runs, csv_path)
                write_html(all_students, runs, html_path)
                write_detail_csv(all_students, detail_path)

            self._log_msg(f"\n{'=' * 50}")
            self._log_msg("✅ Done!")
            self._log_msg(f"   Summary CSV:  {csv_path}")
            self._log_msg(f"   HTML report:  {html_path}")
            self._log_msg(f"   Detail CSV:   {detail_path}")
            self._log_msg(f"{'=' * 50}")

            messagebox.showinfo(
                "Grading Complete", f"Reports saved to:\n{output_dir}"
            )
        except Exception as exc:
            import traceback
            self._log_msg(f"\n❌ Error writing reports: {exc}")
            self._log_msg(traceback.format_exc())

    def _anonymize_students(self, all_students):
        """Return a copy of all_students with names replaced by StudentN,
        plus a mapping dict from real name → anonymized name.

        Students are numbered by alphabetical order of real name so the
        numbering is deterministic and stable across runs.
        """
        import copy
        sorted_names = sorted(all_students.keys())
        mapping: dict[str, str] = {
            real: f"Student{i+1}-Last, Student{i+1}-First"
            for i, real in enumerate(sorted_names)
        }

        # Deep copy so we don't mutate the live data (still shown in review dialog)
        anon_students = {}
        for real_name, student_result in all_students.items():
            fake_name = mapping[real_name]
            copied = copy.deepcopy(student_result)
            copied.student_name = fake_name
            for ar in copied.assignment_results:
                ar.student_name = fake_name
            anon_students[fake_name] = copied

        return anon_students, mapping


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = Tk()
    app = BatchGraderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
