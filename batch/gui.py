"""
TechSmart Batch Grader — Tkinter GUI

Run with:
    python -m batch.gui
  or:
    python batch/gui.py

Layout:
  ┌─ Credentials ──────────────────────────────────────────────┐
  │  Username: [___________]  Password: [___________]          │
  └────────────────────────────────────────────────────────────┘
  ┌─ Assignment URLs (paste once, auto-saved) ─────────────────┐
  │  Animating Shapes 1:   [https://platform.techsmart.codes/…]│
  │  Animating Shapes 2:   [https://…                        ] │
  │  … (all 12 assignments)                                    │
  └────────────────────────────────────────────────────────────┘
  ┌─ Grade Runs ───────────────────────────────────────────────┐
  │  Run Name   [AS1] [AS2] [AR1] [AR2] [S1] [S2] [B1] [B2]… │
  │  [Run 1 ▢]   ☑    ☑    ☑    ☑    ☑   ☑   ☑   ☑  …    │
  │  [Run 2 ▢]   ☐    ☐    ☐    ☐    ☐   ☐   ☐   ☐  …    │
  │  [+ Add Run]                                               │
  └────────────────────────────────────────────────────────────┘
  [ ▶ Grade All Runs ]     Output: ~/Desktop/techsmart_grades/
  ┌─ Progress ─────────────────────────────────────────────────┐
  │  > Logging in...                                           │
  └────────────────────────────────────────────────────────────┘
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
    BooleanVar, Canvas, Entry, Frame, Label, LabelFrame, Scrollbar,
    StringVar, Text, Tk, messagebox, ttk
)
from tkinter import filedialog
import tkinter as tk

# Allow imports from repo root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from batch.batch_runner import run_full_pipeline
from batch.report import write_csv, write_html, write_detail_csv

# ---------------------------------------------------------------------------
# Assignment definitions (id, short label, default include-in-grade)
# ---------------------------------------------------------------------------

ASSIGNMENTS = [
    ("3_3_animating_shapes_1_technique1practice1_py",        "Anim Shapes 1",   True),
    ("3_3_animating_shapes_2_technique1practice2_py",        "Anim Shapes 2",   True),
    ("3_3_animating_rect_shapes_1_technique2practice1_py",   "Rect Shapes 1",   True),
    ("3_3_animating_rect_shapes_2_technique2practice2_py",   "Rect Shapes 2",   True),
    ("3_3_adjust_animation_speed_1_technique3practice1_py",  "Speed 1",         True),
    ("3_3_adjust_animation_speed_2_technique3practice2_py",  "Speed 2",         True),
    ("3_3_backgrounds_and_trails_1_technique4practice1_py",  "Backgrounds 1",   True),
    ("3_3_backgrounds_and_trails_2_technique4practice2_py",  "Backgrounds 2",   True),
    ("3_3_stick_dance_random_stickdancerandom_solution_py",  "Stick Dance Rnd", True),
    ("3_3_healthful_ufo_healthfulufo_solution_py",           "Healthful UFO",   True),
    ("3_3_stick_dance_smooth_stickdancesmooth_solution_py",  "Stick Dance Smt", True),
    ("3_3_bouncing_ball_bouncingball_solution_py",           "Bouncing Ball",   True),
]

ASSIGNMENT_IDS   = [a[0] for a in ASSIGNMENTS]
ASSIGNMENT_LABELS = [a[1] for a in ASSIGNMENTS]

# Where we save the URL config and runs config
_SAVE_DIR  = _ROOT
_URLS_FILE = _SAVE_DIR / "assignment_urls.json"
_RUNS_FILE = _SAVE_DIR / "saved_runs.json"

# Default output folder
_DEFAULT_OUTPUT = Path.home() / "Desktop" / "techsmart_grades"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_urls() -> dict[str, str]:
    if _URLS_FILE.exists():
        try:
            return json.loads(_URLS_FILE.read_text())
        except Exception:
            pass
    return {aid: "" for aid in ASSIGNMENT_IDS}


def _save_urls(urls: dict[str, str]) -> None:
    _URLS_FILE.write_text(json.dumps(urls, indent=2))


def _load_runs() -> list[dict]:
    """Returns list of {name, included_ids}"""
    if _RUNS_FILE.exists():
        try:
            return json.loads(_RUNS_FILE.read_text())
        except Exception:
            pass
    # Default: one run with all assignments checked
    return [{"name": "All Assignments", "included_ids": ASSIGNMENT_IDS[:]}]


def _save_runs(runs: list[dict]) -> None:
    _RUNS_FILE.write_text(json.dumps(runs, indent=2))


# ---------------------------------------------------------------------------
# Main GUI window
# ---------------------------------------------------------------------------

class BatchGraderApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("TechSmart Batch Grader")
        root.geometry("1100x820")
        root.resizable(True, True)

        # State
        self._urls: dict[str, StringVar] = {}
        self._run_rows: list[dict] = []   # each: {name_var, check_vars, frame}
        self._output_dir = StringVar(value=str(_DEFAULT_OUTPUT))

        # Load saved data
        saved_urls = _load_urls()
        saved_runs = _load_runs()

        # Build UI
        self._build_credentials(root)
        self._build_urls_section(root, saved_urls)
        self._build_runs_section(root, saved_runs)
        self._build_action_row(root)
        self._build_progress(root)

    # -----------------------------------------------------------------------
    # Credentials section
    # -----------------------------------------------------------------------

    def _build_credentials(self, parent):
        frame = LabelFrame(parent, text=" TechSmart Credentials ", padx=8, pady=6)
        frame.pack(fill="x", padx=10, pady=(8, 4))

        # Try to pre-fill from .env
        env_user, env_pass = self._read_env_credentials()

        Label(frame, text="Username:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self._username = StringVar(value=env_user)
        Entry(frame, textvariable=self._username, width=30).grid(row=0, column=1, padx=(0, 20))

        Label(frame, text="Password:").grid(row=0, column=2, sticky="e", padx=(0, 4))
        self._password = StringVar(value=env_pass)
        Entry(frame, textvariable=self._password, show="*", width=30).grid(row=0, column=3)

        Label(
            frame,
            text="  (Tip: add TECHSMART_USERNAME and TECHSMART_PASSWORD to .env to auto-fill)",
            fg="gray", font=("Arial", 9)
        ).grid(row=0, column=4, padx=10, sticky="w")

    def _read_env_credentials(self) -> tuple[str, str]:
        """Load credentials from .env if present."""
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
        # Also check environment
        user = user or os.environ.get("TECHSMART_USERNAME", "")
        pw   = pw   or os.environ.get("TECHSMART_PASSWORD", "")
        return user, pw

    # -----------------------------------------------------------------------
    # Assignment URLs section (scrollable)
    # -----------------------------------------------------------------------

    def _build_urls_section(self, parent, saved_urls: dict):
        outer = LabelFrame(
            parent, text=" Assignment URLs  (paste the TechSmart /code/XXXXX/ URL for each) ",
            padx=8, pady=6
        )
        outer.pack(fill="x", padx=10, pady=4)

        # Two-column grid for the 12 assignments
        for idx, (aid, label, _) in enumerate(ASSIGNMENTS):
            row, col_offset = divmod(idx, 2)
            col_offset *= 3  # label, entry, spacer

            Label(outer, text=f"{label}:", anchor="e", width=16).grid(
                row=row, column=col_offset, sticky="e", padx=(4, 4)
            )
            sv = StringVar(value=saved_urls.get(aid, ""))
            self._urls[aid] = sv
            Entry(outer, textvariable=sv, width=52).grid(
                row=row, column=col_offset + 1, sticky="ew", padx=(0, 16)
            )

        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(4, weight=1)

    # -----------------------------------------------------------------------
    # Grade runs section
    # -----------------------------------------------------------------------

    def _build_runs_section(self, parent, saved_runs: list[dict]):
        self._runs_outer = LabelFrame(
            parent,
            text=" Grade Runs  (each row = one composite grade; check which assignments count) ",
            padx=8, pady=6
        )
        self._runs_outer.pack(fill="both", padx=10, pady=4)

        # Scrollable canvas for the checkbox grid (many columns)
        canvas_frame = Frame(self._runs_outer)
        canvas_frame.pack(fill="both", expand=True)

        h_scroll = Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")

        self._runs_canvas = Canvas(
            canvas_frame, height=150, xscrollcommand=h_scroll.set,
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

        # Header row: assignment short labels
        Label(self._runs_inner, text="Run Name", width=18, anchor="w",
              font=("Arial", 9, "bold")).grid(row=0, column=0, padx=4, pady=2)
        for col_idx, label in enumerate(ASSIGNMENT_LABELS):
            Label(
                self._runs_inner, text=label, font=("Arial", 8, "bold"),
                width=10, wraplength=80, justify="center"
            ).grid(row=0, column=col_idx + 1, padx=2, pady=2)
        # Delete column header
        Label(self._runs_inner, text="", width=4).grid(
            row=0, column=len(ASSIGNMENT_LABELS) + 1
        )

        # Load saved runs
        for run_data in saved_runs:
            self._add_run_row(
                name=run_data.get("name", "Run"),
                checked_ids=set(run_data.get("included_ids", ASSIGNMENT_IDS)),
            )

        # "+ Add Run" button
        tk.Button(
            self._runs_outer, text="+ Add Run",
            command=lambda: self._add_run_row(),
            relief="flat", bg="#e0e0e0", padx=8
        ).pack(anchor="w", pady=(4, 0))

    def _add_run_row(self, name: str = "New Run", checked_ids: set | None = None):
        if checked_ids is None:
            checked_ids = set(ASSIGNMENT_IDS)

        row_idx = len(self._run_rows) + 1  # +1 for header

        name_var = StringVar(value=name)
        Entry(self._runs_inner, textvariable=name_var, width=18).grid(
            row=row_idx, column=0, padx=4, pady=1
        )

        check_vars: dict[str, BooleanVar] = {}
        for col_idx, (aid, label, _) in enumerate(ASSIGNMENTS):
            bv = BooleanVar(value=(aid in checked_ids))
            check_vars[aid] = bv
            tk.Checkbutton(
                self._runs_inner, variable=bv, padx=0
            ).grid(row=row_idx, column=col_idx + 1, padx=0)

        # Delete button
        def _delete(rr=None):
            if rr is not None:
                # Destroy all widgets in this row
                for w in self._runs_inner.grid_slaves(row=self._run_rows.index(rr) + 1):
                    w.destroy()
                self._run_rows.remove(rr)

        row_record = {"name_var": name_var, "check_vars": check_vars}
        del_btn = tk.Button(
            self._runs_inner, text="✕", fg="red", relief="flat",
            command=lambda rr=row_record: _delete(rr),
            font=("Arial", 9), padx=2
        )
        del_btn.grid(row=row_idx, column=len(ASSIGNMENTS) + 1, padx=2)

        row_record["del_btn"] = del_btn
        self._run_rows.append(row_record)

        # Scroll canvas to show new row
        self._runs_canvas.update_idletasks()
        self._runs_canvas.configure(scrollregion=self._runs_canvas.bbox("all"))

    # -----------------------------------------------------------------------
    # Action row
    # -----------------------------------------------------------------------

    def _build_action_row(self, parent):
        frame = Frame(parent, pady=6)
        frame.pack(fill="x", padx=10)

        self._grade_btn = tk.Button(
            frame, text="▶  Grade All Runs", command=self._start_grading,
            bg="#2e7d32", fg="white", font=("Arial", 11, "bold"),
            relief="flat", padx=16, pady=6
        )
        self._grade_btn.pack(side="left")

        Label(frame, text="  Output folder:").pack(side="left")
        Entry(frame, textvariable=self._output_dir, width=40).pack(side="left", padx=4)
        tk.Button(
            frame, text="Browse…",
            command=self._browse_output,
            relief="flat", bg="#e0e0e0", padx=6
        ).pack(side="left")

        self._headless_var = BooleanVar(value=False)
        tk.Checkbutton(
            frame, text="Run browser headless (hidden)", variable=self._headless_var
        ).pack(side="left", padx=10)

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

        self._log = Text(frame, font=("Courier", 10), state="disabled",
                         bg="#1e1e1e", fg="#d4d4d4", wrap="none")
        scroll_y = Scrollbar(frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

    def _log_msg(self, msg: str):
        """Append a line to the progress log (thread-safe)."""
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.root.after(0, _do)

    # -----------------------------------------------------------------------
    # Grading orchestration
    # -----------------------------------------------------------------------

    def _start_grading(self):
        """Validate inputs, save state, then launch grading on a background thread."""
        username = self._username.get().strip()
        password = self._password.get().strip()
        if not username or not password:
            messagebox.showerror("Missing credentials",
                                 "Please enter your TechSmart username and password.")
            return

        if not self._run_rows:
            messagebox.showerror("No runs defined",
                                 "Add at least one grade run before grading.")
            return

        # Collect URLs
        assignment_urls = {aid: sv.get().strip() for aid, sv in self._urls.items()}
        _save_urls(assignment_urls)

        # Collect runs
        runs: dict[str, list[str]] = {}
        saved_runs_data = []
        for rr in self._run_rows:
            run_name = rr["name_var"].get().strip() or "Run"
            included = [aid for aid, bv in rr["check_vars"].items() if bv.get()]
            if included:
                runs[run_name] = included
                saved_runs_data.append({"name": run_name, "included_ids": included})
        _save_runs(saved_runs_data)

        if not runs:
            messagebox.showerror("No assignments selected",
                                 "Check at least one assignment in at least one run.")
            return

        # Only scrape assignments that have a URL AND are in at least one run
        needed_ids = set(aid for ids in runs.values() for aid in ids)
        urls_to_scrape = {
            aid: url for aid, url in assignment_urls.items()
            if aid in needed_ids and url
        }
        if not urls_to_scrape:
            messagebox.showerror(
                "No URLs entered",
                "Paste at least one TechSmart assignment URL for the assignments you've selected."
            )
            return

        output_dir = Path(self._output_dir.get().strip() or str(_DEFAULT_OUTPUT))
        headless = self._headless_var.get()

        # Disable button while running
        self._grade_btn.configure(state="disabled", text="⏳ Grading…")

        # Clear log
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        # Run in background thread so GUI stays responsive
        thread = threading.Thread(
            target=self._grading_thread,
            args=(username, password, urls_to_scrape, runs, output_dir, headless),
            daemon=True,
        )
        thread.start()

    def _grading_thread(self, username, password, urls_to_scrape, runs, output_dir, headless):
        """Background thread: runs async pipeline then calls report writers."""
        try:
            # asyncio event loop for Playwright
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            all_students = loop.run_until_complete(
                run_full_pipeline(
                    username=username,
                    password=password,
                    assignment_urls=urls_to_scrape,
                    runs=runs,
                    progress_callback=self._log_msg,
                    headless=headless,
                )
            )
            loop.close()

            # Write reports
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir.mkdir(parents=True, exist_ok=True)

            csv_path   = output_dir / f"grades_{timestamp}.csv"
            html_path  = output_dir / f"grades_{timestamp}.html"
            detail_path = output_dir / f"grades_detail_{timestamp}.csv"

            write_csv(all_students, runs, csv_path)
            write_html(all_students, runs, html_path)
            write_detail_csv(all_students, detail_path)

            self._log_msg(f"\n{'=' * 50}")
            self._log_msg(f"✅ Done!")
            self._log_msg(f"   Summary CSV:  {csv_path}")
            self._log_msg(f"   HTML report:  {html_path}")
            self._log_msg(f"   Detail CSV:   {detail_path}")
            self._log_msg(f"{'=' * 50}")

            self.root.after(0, lambda: messagebox.showinfo(
                "Grading Complete",
                f"Reports saved to:\n{output_dir}"
            ))

        except Exception as exc:
            import traceback
            self._log_msg(f"\n❌ Fatal error: {exc}")
            self._log_msg(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror(
                "Error", f"Grading failed:\n{exc}"
            ))

        finally:
            self.root.after(0, lambda: self._grade_btn.configure(
                state="normal", text="▶  Grade All Runs"
            ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = Tk()
    app = BatchGraderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()