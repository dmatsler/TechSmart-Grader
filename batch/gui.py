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

_SAVE_DIR        = _ROOT
_ACTIVE_UNIT_FILE = _SAVE_DIR / "active_unit.json"
_DEFAULT_OUTPUT  = Path.home() / "Desktop" / "techsmart_grades"


def _load_active_unit() -> str:
    if _ACTIVE_UNIT_FILE.exists():
        try:
            return json.loads(_ACTIVE_UNIT_FILE.read_text()).get("unit", "3_3")
        except Exception:
            pass
    return "3_3"


def _save_active_unit(slug: str) -> None:
    _ACTIVE_UNIT_FILE.write_text(json.dumps({"unit": slug}, indent=2))


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

        # Current unit's gradeable assignments — rebuilt when unit changes
        self._current_assignments: list[tuple[str, str]] = \
            get_unit_assignments(self._active_unit.get())

        self._build_unit_selector(root)
        self._build_credentials(root)
        self._build_gradebook_section(root)
        self._build_runs_section(root, _load_runs(self._active_unit.get()))
        self._build_action_row(root)
        self._build_progress(root)

    # -----------------------------------------------------------------------
    # Unit selector
    # -----------------------------------------------------------------------

    def _build_unit_selector(self, parent):
        frame = LabelFrame(parent, text=" Active Unit ", padx=8, pady=6)
        frame.pack(fill="x", padx=10, pady=(8, 2))

        Label(frame, text="Select unit to grade:").grid(
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

        Label(
            frame,
            text="  (changing unit reloads assignment columns and gradebook URL)",
            fg="gray", font=("Arial", 9)
        ).grid(row=0, column=2, sticky="w", padx=8)

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

    # -----------------------------------------------------------------------
    # Credentials
    # -----------------------------------------------------------------------

    def _build_credentials(self, parent):
        frame = LabelFrame(parent, text=" TechSmart Credentials ", padx=8, pady=6)
        frame.pack(fill="x", padx=10, pady=(2, 4))

        env_user, env_pass = self._read_env_credentials()

        Label(frame, text="Username:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self._username = StringVar(value=env_user)
        Entry(frame, textvariable=self._username, width=30).grid(
            row=0, column=1, padx=(0, 20)
        )

        Label(frame, text="Password:").grid(row=0, column=2, sticky="e", padx=(0, 4))
        self._password = StringVar(value=env_pass)
        Entry(frame, textvariable=self._password, show="*", width=30).grid(
            row=0, column=3
        )

        Label(
            frame,
            text="  (Tip: set TECHSMART_USERNAME / TECHSMART_PASSWORD in .env)",
            fg="gray", font=("Arial", 9)
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
        frame = LabelFrame(
            parent,
            text=" Gradebook URL  (paste once — assignment URLs are discovered automatically) ",
            padx=8, pady=8
        )
        frame.pack(fill="x", padx=10, pady=4)

        Label(frame, text="Gradebook URL:").grid(
            row=0, column=0, sticky="e", padx=(0, 6)
        )
        self._gradebook_url = StringVar(
            value=_load_gradebook_url(self._active_unit.get())
        )
        Entry(frame, textvariable=self._gradebook_url, width=70).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        Label(
            frame,
            text="e.g.  https://platform.techsmart.codes/gradebook/class/XXXXX/?unit_id=3&lesson_id=5",
            fg="gray", font=("Arial", 9)
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
        self._runs_wrapper = Frame(parent)
        self._runs_wrapper.pack(fill="both", padx=10, pady=4)
        self._runs_parent = parent
        self._populate_runs_wrapper(saved_runs)

    def _populate_runs_wrapper(self, saved_runs: list[dict]):
        """Build the runs box + sidebar inside self._runs_wrapper.

        Called both on initial build (from _build_runs_section) and on
        every unit change (from _rebuild_runs_section). The wrapper is
        assumed to exist and be empty.
        """
        self._runs_outer = LabelFrame(
            self._runs_wrapper,
            text=" Grade Runs  (each row = one composite grade; "
                 "check which assignments to include) ",
            padx=8, pady=6
        )
        self._runs_outer.pack(side="left", fill="both", expand=True)

        # Right-hand sidebar — live readout of how many boxes each run has checked
        self._counters_outer = LabelFrame(
            self._runs_wrapper,
            text=" Selected ", padx=8, pady=6
        )
        self._counters_outer.pack(side="right", fill="y", padx=(8, 0))

        # Inner frame is what we wipe-and-rebuild on every refresh
        self._counters_inner = Frame(self._counters_outer)
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
        canvas_frame = Frame(self._runs_outer)
        canvas_frame.pack(fill="both", expand=True)

        h_scroll = Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

        self._runs_canvas = Canvas(
            canvas_frame, height=160, xscrollcommand=h_scroll.set,
            highlightthickness=0
        )
        self._runs_canvas.pack(fill="both", expand=True)
        h_scroll.config(command=self._runs_canvas.xview)

        self._runs_inner = Frame(self._runs_canvas)
        self._runs_canvas.create_window((0, 0), window=self._runs_inner, anchor="nw")
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
        # Clear the wrapper's children but keep the wrapper itself
        for child in self._runs_wrapper.winfo_children():
            child.destroy()
        self._populate_runs_wrapper(saved_runs)

    def _populate_header_row(self):
        Label(
            self._runs_inner, text="Run Name", width=18, anchor="w",
            font=("Arial", 9, "bold")
        ).grid(row=0, column=0, padx=4, pady=2)

        # Spacer cells above the per-row [☑ All] [☐ None] buttons.
        # No header text — the buttons' meaning is self-evident from the icons.
        Label(self._runs_inner, text="", width=5).grid(row=0, column=1, padx=1)
        Label(self._runs_inner, text="", width=6).grid(row=0, column=2, padx=1)

        for col_idx, (_, label) in enumerate(self._current_assignments):
            Label(
                self._runs_inner, text=label, width=14, anchor="center",
                font=("Arial", 9, "bold"), wraplength=90
            ).grid(row=0, column=col_idx + 3, padx=2, pady=2)

        Label(
            self._runs_inner, text="", width=3
        ).grid(row=0, column=len(self._current_assignments) + 3)

        btn_frame = Frame(self._runs_outer)
        btn_frame.pack(fill="x", pady=(4, 0))
        tk.Button(
            btn_frame, text="+ Add Run", command=self._add_run_row,
            relief="flat", bg="#e0e0e0", padx=8
        ).pack(side="left")

    def _add_run_row(self, name: str = "Run", pre_checked: set[str] | None = None):
        row_idx = len(self._run_rows) + 1
        row_record: dict = {"check_vars": {}}

        name_var = StringVar(value=name)
        # Trace fires per-keystroke as the user edits the name — sidebar
        # updates live so they see "Run A: 5 of 14" become "Warmups: 5 of 14"
        # as they type.
        name_var.trace_add("write", lambda *_: self._refresh_run_counters())
        Entry(
            self._runs_inner, textvariable=name_var, width=18
        ).grid(row=row_idx, column=0, padx=4, pady=2)
        row_record["name_var"] = name_var

        # Per-row bulk-toggle buttons — scoped to THIS run only, never global.
        # Captured row_record via default arg to dodge late-binding closure bugs
        # (without this, all buttons would point at whichever was the last row
        # built when the lambda finally fires).
        all_btn = tk.Button(
            self._runs_inner, text="☑ All",
            command=lambda rr=row_record: self._select_all_in_run(rr),
            relief="flat", bg="#dbeafe", fg="#1d4ed8",
            font=("Arial", 8), padx=4
        )
        all_btn.grid(row=row_idx, column=1, padx=(2, 1))

        none_btn = tk.Button(
            self._runs_inner, text="☐ None",
            command=lambda rr=row_record: self._select_none_in_run(rr),
            relief="flat", bg="#e5e7eb",
            font=("Arial", 8), padx=4
        )
        none_btn.grid(row=row_idx, column=2, padx=(1, 2))

        for col_idx, (aid, _) in enumerate(self._current_assignments):
            bv = BooleanVar(value=(pre_checked is not None and aid in pre_checked))
            # Trace fires when a checkbox is clicked OR when [All]/[None]
            # programmatically calls bv.set(...) — both paths trigger refresh.
            bv.trace_add("write", lambda *_: self._refresh_run_counters())
            cb = tk.Checkbutton(self._runs_inner, variable=bv)
            cb.grid(row=row_idx, column=col_idx + 3, padx=2)
            row_record["check_vars"][aid] = bv

        def _delete(rr=row_record, ri=row_idx):
            for widget in self._runs_inner.grid_slaves(row=ri):
                widget.destroy()
            if rr in self._run_rows:
                self._run_rows.remove(rr)
            self._refresh_run_counters()

        del_btn = tk.Button(
            self._runs_inner, text="✕", fg="red", relief="flat",
            command=_delete, font=("Arial", 9), padx=2
        )
        del_btn.grid(row=row_idx, column=len(self._current_assignments) + 3, padx=2)
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

        Called whenever a checkbox flips, a run name changes, or a run is
        added or deleted. Cheap at this scale (≤ 10 runs typical), so we
        rebuild rather than track individual labels.
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

        if not self._run_rows:
            Label(
                inner, text="(no runs)", anchor="w",
                font=("Arial", 9, "italic"), fg="gray"
            ).pack(anchor="w", pady=2)
            return

        for rr in self._run_rows:
            name = rr["name_var"].get().strip() or "Run"
            checked = sum(1 for bv in rr["check_vars"].values() if bv.get())
            Label(
                inner,
                text=f"{name}: {checked} of {total}",
                anchor="w", font=("Arial", 10)
            ).pack(anchor="w", pady=1)

    # -----------------------------------------------------------------------
    # Action row
    # -----------------------------------------------------------------------

    def _build_action_row(self, parent):
        # ── Row 1: Grade button + Stop button + output folder ────────────────
        row1 = Frame(parent, pady=4)
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

        Label(row1, text="  Output folder:").pack(side="left")
        Entry(row1, textvariable=self._output_dir, width=45).pack(
            side="left", padx=4
        )
        tk.Button(
            row1, text="Browse…", command=self._browse_output,
            relief="flat", bg="#e0e0e0", padx=6
        ).pack(side="left")

        # ── Row 2: Options checkboxes ─────────────────────────────────────────
        row2 = Frame(parent, pady=2)
        row2.pack(fill="x", padx=10)

        self._headless_var = BooleanVar(value=False)
        tk.Checkbutton(
            row2, text="Run browser headless (hidden)",
            variable=self._headless_var
        ).pack(side="left", padx=(0, 20))

        self._refresh_context_var = BooleanVar(value=False)
        tk.Checkbutton(
            row2, text="Refresh assignment context cache",
            variable=self._refresh_context_var
        ).pack(side="left", padx=(0, 20))

        self._anonymize_var = BooleanVar(value=False)
        tk.Checkbutton(
            row2, text="Anonymize student names in reports",
            variable=self._anonymize_var
        ).pack(side="left")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self._output_dir.set(d)

    # -----------------------------------------------------------------------
    # Progress log
    # -----------------------------------------------------------------------

    def _build_progress(self, parent):
        frame = LabelFrame(parent, text=" Progress ", padx=6, pady=6)
        frame.pack(fill="both", expand=True, padx=10, pady=(4, 8))

        self._log = Text(
            frame, font=("Courier", 10), state="disabled",
            bg="#1e1e1e", fg="#d4d4d4", wrap="none"
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

        # Buttons use tk.Button with fixed width so they're equal-sized and readable
        tk.Button(
            footer,
            text="✔  Confirm All & Write Reports",
            command=_on_write,
            bg="#16a34a", fg="white", font=("Arial", 11, "bold"),
            relief="raised", padx=20, pady=12, cursor="hand2",
            width=30, height=2
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            footer,
            text="Skip Review — Write Reports Now\n(pending stay excluded from grades)",
            command=_on_cancel,
            bg="#64748b", fg="white", font=("Arial", 11, "bold"),
            relief="raised", padx=20, pady=12, cursor="hand2",
            width=30, height=2
        ).pack(side="left")

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
