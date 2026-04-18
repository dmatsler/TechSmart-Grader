"""
TechSmart Batch Grader — Tkinter GUI

Run with:
    python -m batch.gui

The teacher pastes ONE gradebook URL (stable, set once per unit).
Assignment URLs are auto-discovered from the gradebook — no manual pasting needed.
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
    BooleanVar, Canvas, Entry, Frame, Label, LabelFrame,
    Scrollbar, StringVar, Text, Tk, messagebox
)
import tkinter as tk
from tkinter import filedialog

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from batch.batch_runner import run_full_pipeline
from batch.report import write_csv, write_html, write_detail_csv

# ---------------------------------------------------------------------------
# Assignment definitions
# ---------------------------------------------------------------------------

ASSIGNMENTS = [
    ("3_3_animating_shapes_1_technique1practice1_py",        "Anim Shapes 1"),
    ("3_3_animating_shapes_2_technique1practice2_py",        "Anim Shapes 2"),
    ("3_3_animating_rect_shapes_1_technique2practice1_py",   "Rect Shapes 1"),
    ("3_3_animating_rect_shapes_2_technique2practice2_py",   "Rect Shapes 2"),
    ("3_3_adjust_animation_speed_1_technique3practice1_py",  "Speed 1"),
    ("3_3_adjust_animation_speed_2_technique3practice2_py",  "Speed 2"),
    ("3_3_backgrounds_and_trails_1_technique4practice1_py",  "Backgrounds 1"),
    ("3_3_backgrounds_and_trails_2_technique4practice2_py",  "Backgrounds 2"),
    ("3_3_stick_dance_random_stickdancerandom_solution_py",  "Stick Dance Rnd"),
    ("3_3_healthful_ufo_healthfulufo_solution_py",           "Healthful UFO"),
    ("3_3_stick_dance_smooth_stickdancesmooth_solution_py",  "Stick Dance Smt"),
    ("3_3_bouncing_ball_bouncingball_solution_py",           "Bouncing Ball"),
]

ASSIGNMENT_IDS    = [a[0] for a in ASSIGNMENTS]
ASSIGNMENT_LABELS = [a[1] for a in ASSIGNMENTS]

_SAVE_DIR       = _ROOT
_GRADEBOOK_FILE = _SAVE_DIR / "gradebook_url.json"
_RUNS_FILE      = _SAVE_DIR / "saved_runs.json"
_DEFAULT_OUTPUT = Path.home() / "Desktop" / "techsmart_grades"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_gradebook_url() -> str:
    if _GRADEBOOK_FILE.exists():
        try:
            return json.loads(_GRADEBOOK_FILE.read_text()).get("url", "")
        except Exception:
            pass
    return ""


def _save_gradebook_url(url: str) -> None:
    _GRADEBOOK_FILE.write_text(json.dumps({"url": url}, indent=2))


def _load_runs() -> list[dict]:
    if _RUNS_FILE.exists():
        try:
            return json.loads(_RUNS_FILE.read_text())
        except Exception:
            pass
    return [{"name": "All Assignments", "included_ids": []}]


def _save_runs(runs: list[dict]) -> None:
    _RUNS_FILE.write_text(json.dumps(runs, indent=2))


# ---------------------------------------------------------------------------
# Main GUI
# ---------------------------------------------------------------------------

class BatchGraderApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("TechSmart Batch Grader")
        root.geometry("1100x780")
        root.resizable(True, True)

        self._run_rows: list[dict] = []
        self._output_dir = StringVar(value=str(_DEFAULT_OUTPUT))

        saved_runs = _load_runs()

        self._build_credentials(root)
        self._build_gradebook_section(root)
        self._build_runs_section(root, saved_runs)
        self._build_action_row(root)
        self._build_progress(root)

    # -----------------------------------------------------------------------
    # Credentials
    # -----------------------------------------------------------------------

    def _build_credentials(self, parent):
        frame = LabelFrame(parent, text=" TechSmart Credentials ", padx=8, pady=6)
        frame.pack(fill="x", padx=10, pady=(8, 4))

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
            text="  (Tip: add TECHSMART_USERNAME / TECHSMART_PASSWORD to .env)",
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
    # Gradebook URL (replaces 12 individual URL fields)
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
        self._gradebook_url = StringVar(value=_load_gradebook_url())
        Entry(frame, textvariable=self._gradebook_url, width=70).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        Label(
            frame,
            text="e.g.  https://platform.techsmart.codes/gradebook/class/XXXXX/?unit_id=3&lesson_id=3",
            fg="gray", font=("Arial", 9)
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))
        frame.columnconfigure(1, weight=1)

    # -----------------------------------------------------------------------
    # Grade runs
    # -----------------------------------------------------------------------

    def _build_runs_section(self, parent, saved_runs: list[dict]):
        self._runs_outer = LabelFrame(
            parent,
            text=" Grade Runs  (each row = one composite grade; "
                 "check which assignments to include) ",
            padx=8, pady=6
        )
        self._runs_outer.pack(fill="both", padx=10, pady=4)

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

        # Header row
        Label(
            self._runs_inner, text="Run Name", width=18, anchor="w",
            font=("Arial", 9, "bold")
        ).grid(row=0, column=0, padx=4, pady=2)
        for col_idx, label in enumerate(ASSIGNMENT_LABELS):
            Label(
                self._runs_inner, text=label, font=("Arial", 8, "bold"),
                width=10, wraplength=80, justify="center"
            ).grid(row=0, column=col_idx + 1, padx=2, pady=2)
        Label(self._runs_inner, text="", width=4).grid(
            row=0, column=len(ASSIGNMENT_LABELS) + 1
        )

        for run_data in saved_runs:
            self._add_run_row(
                name=run_data.get("name", "Run"),
                checked_ids=set(run_data.get("included_ids", [])),
            )

        tk.Button(
            self._runs_outer, text="+ Add Run",
            command=lambda: self._add_run_row(),
            relief="flat", bg="#e0e0e0", padx=8
        ).pack(anchor="w", pady=(4, 0))

    def _add_run_row(self, name: str = "New Run", checked_ids: set | None = None):
        if checked_ids is None:
            checked_ids = set()

        row_idx = len(self._run_rows) + 1

        name_var = StringVar(value=name)
        Entry(self._runs_inner, textvariable=name_var, width=18).grid(
            row=row_idx, column=0, padx=4, pady=1
        )

        check_vars: dict[str, BooleanVar] = {}
        for col_idx, (aid, label) in enumerate(ASSIGNMENTS):
            bv = BooleanVar(value=(aid in checked_ids))
            check_vars[aid] = bv
            tk.Checkbutton(
                self._runs_inner, variable=bv
            ).grid(row=row_idx, column=col_idx + 1, padx=0)

        row_record = {"name_var": name_var, "check_vars": check_vars}

        def _delete(rr=row_record):
            grid_row = self._run_rows.index(rr) + 1
            for w in self._runs_inner.grid_slaves(row=grid_row):
                w.destroy()
            self._run_rows.remove(rr)

        del_btn = tk.Button(
            self._runs_inner, text="✕", fg="red", relief="flat",
            command=_delete, font=("Arial", 9), padx=2
        )
        del_btn.grid(row=row_idx, column=len(ASSIGNMENTS) + 1, padx=2)
        row_record["del_btn"] = del_btn
        self._run_rows.append(row_record)

        self._runs_canvas.update_idletasks()
        self._runs_canvas.configure(
            scrollregion=self._runs_canvas.bbox("all")
        )

    # -----------------------------------------------------------------------
    # Action row
    # -----------------------------------------------------------------------

    def _build_action_row(self, parent):
        frame = Frame(parent, pady=6)
        frame.pack(fill="x", padx=10)

        self._grade_btn = tk.Label(
            frame, text="▶  Grade All Runs",
            bg="#1a7a1a", fg="white", font=("Arial", 13, "bold"),
            relief="raised", padx=20, pady=10,
            cursor="hand2"
        )
        self._grade_btn.pack(side="left")
        self._grade_btn.bind("<Button-1>", lambda e: self._start_grading())
        self._grade_btn.bind(
            "<Enter>", lambda e: self._grade_btn.config(bg="#145214")
        )
        self._grade_btn.bind(
            "<Leave>", lambda e: self._grade_btn.config(bg="#1a7a1a")
        )

        Label(frame, text="  Output folder:").pack(side="left")
        Entry(frame, textvariable=self._output_dir, width=40).pack(
            side="left", padx=4
        )
        tk.Button(
            frame, text="Browse…", command=self._browse_output,
            relief="flat", bg="#e0e0e0", padx=6
        ).pack(side="left")

        self._headless_var = BooleanVar(value=False)
        tk.Checkbutton(
            frame, text="Run browser headless (hidden)",
            variable=self._headless_var
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
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.root.after(0, _do)

    # -----------------------------------------------------------------------
    # Grading
    # -----------------------------------------------------------------------

    def _start_grading(self):
        username = self._username.get().strip()
        password = self._password.get().strip()
        if not username or not password:
            messagebox.showerror(
                "Missing credentials",
                "Please enter your TechSmart username and password."
            )
            return

        gradebook_url = self._gradebook_url.get().strip()
        if not gradebook_url:
            messagebox.showerror(
                "Missing gradebook URL",
                "Please paste your TechSmart gradebook URL."
            )
            return

        if not self._run_rows:
            messagebox.showerror(
                "No runs defined",
                "Add at least one grade run before grading."
            )
            return

        # Collect runs
        runs: dict[str, list[str]] = {}
        saved_runs_data = []
        for rr in self._run_rows:
            run_name = rr["name_var"].get().strip() or "Run"
            included = [aid for aid, bv in rr["check_vars"].items() if bv.get()]
            if included:
                runs[run_name] = included
                saved_runs_data.append({"name": run_name, "included_ids": included})

        if not runs:
            messagebox.showerror(
                "No assignments selected",
                "Check at least one assignment in at least one run."
            )
            return

        # Save state
        _save_gradebook_url(gradebook_url)
        _save_runs(saved_runs_data)

        # Collect all unique assignment IDs needed
        assignment_ids = list({
            aid for ids in runs.values() for aid in ids
        })

        output_dir = Path(self._output_dir.get().strip() or str(_DEFAULT_OUTPUT))
        headless = self._headless_var.get()

        self._grade_btn.configure(text="⏳ Grading…", bg="#555555")

        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        thread = threading.Thread(
            target=self._grading_thread,
            args=(username, password, gradebook_url,
                  assignment_ids, runs, output_dir, headless),
            daemon=True,
        )
        thread.start()

    def _grading_thread(
        self, username, password, gradebook_url,
        assignment_ids, runs, output_dir, headless
    ):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            all_students = loop.run_until_complete(
                run_full_pipeline(
                    username=username,
                    password=password,
                    gradebook_url=gradebook_url,
                    assignment_ids=assignment_ids,
                    runs=runs,
                    progress_callback=self._log_msg,
                    headless=headless,
                )
            )
            loop.close()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir.mkdir(parents=True, exist_ok=True)

            csv_path    = output_dir / f"grades_{timestamp}.csv"
            html_path   = output_dir / f"grades_{timestamp}.html"
            detail_path = output_dir / f"grades_detail_{timestamp}.csv"

            write_csv(all_students, runs, csv_path)
            write_html(all_students, runs, html_path)
            write_detail_csv(all_students, detail_path)

            self._log_msg(f"\n{'=' * 50}")
            self._log_msg("✅ Done!")
            self._log_msg(f"   Summary CSV:  {csv_path}")
            self._log_msg(f"   HTML report:  {html_path}")
            self._log_msg(f"   Detail CSV:   {detail_path}")
            self._log_msg(f"{'=' * 50}")

            self.root.after(0, lambda: messagebox.showinfo(
                "Grading Complete", f"Reports saved to:\n{output_dir}"
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
                text="▶  Grade All Runs", bg="#1a7a1a"
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