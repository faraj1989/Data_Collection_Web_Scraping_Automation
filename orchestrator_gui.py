#!/usr/bin/env python3
"""
Libyana Automation Orchestrator GUI
Single executable GUI to manage all automation services
"""

import os
import sys
import subprocess
import time
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path
from datetime import datetime
import psutil

# ============================================================
# CONFIGURATION
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Scripts to manage
SCRIPTS = [
    {"name": "MAE Scraper", "file": "mae_scraper.py", "desc": "Exports MAE Current Alarms"},
    {"name": "NetEco Scraper", "file": "neteco_scraper.py", "desc": "Exports NetEco Current Alarms"},
    {"name": "Merge Reports", "file": "merge_noc_reports.py",
     "desc": "Merges MAE + NetEco reports"},
    {"name": "Telegram Bot", "file": "telegram_noc_bot.py", "desc": "Telegram NOC Bot for alarms"},
]

# Python executable
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


class OrchestratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Libyana Automation Orchestrator")
        self.root.geometry("800x650")
        self.root.minsize(700, 500)

        # Set icon if available
        try:
            self.root.iconbitmap(default=PROJECT_ROOT / "favicon.ico")
        except Exception:
            pass

        self.processes = {}
        self.monitor_thread = None
        self.running = False

        self.setup_ui()
        self.update_status()

    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header_frame, text="🚀 Libyana Automation Suite", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(header_frame, text=f"v3.0 | {PROJECT_ROOT}", font=("Segoe UI", 9), foreground="gray").pack(
            side=tk.RIGHT)

        # Status bar
        status_frame = ttk.LabelFrame(main_frame, text="Service Status", padding="5")
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.status_text = scrolledtext.ScrolledText(status_frame, height=8, font=("Consolas", 9))
        self.status_text.pack(fill=tk.X, expand=True)

        # Control buttons
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(control_frame, text="▶️ Start All Services", command=self.start_all, width=18).pack(side=tk.LEFT,
                                                                                                       padx=2)
        ttk.Button(control_frame, text="⏹ Stop All Services", command=self.stop_all, width=18).pack(side=tk.LEFT,
                                                                                                    padx=2)
        ttk.Button(control_frame, text="🔄 Restart Services", command=self.restart_all, width=18).pack(side=tk.LEFT,
                                                                                                      padx=2)
        ttk.Button(control_frame, text="📊 Refresh Status", command=self.update_status, width=18).pack(side=tk.LEFT,
                                                                                                      padx=2)
        ttk.Button(control_frame, text="📁 Open Logs", command=self.open_logs, width=18).pack(side=tk.LEFT, padx=2)

        # Individual controls
        script_frame = ttk.LabelFrame(main_frame, text="Individual Services", padding="5")
        script_frame.pack(fill=tk.BOTH, expand=True)

        # Create treeview for scripts
        columns = ("Status", "Name", "PID", "Description")
        self.tree = ttk.Treeview(script_frame, columns=columns, show="headings", height=6)

        self.tree.heading("Status", text="Status")
        self.tree.heading("Name", text="Service Name")
        self.tree.heading("PID", text="PID")
        self.tree.heading("Description", text="Description")

        self.tree.column("Status", width=80, anchor="center")
        self.tree.column("Name", width=180)
        self.tree.column("PID", width=80, anchor="center")
        self.tree.column("Description", width=300)

        # Scrollbar for tree
        tree_scroll = ttk.Scrollbar(script_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Individual control buttons
        ind_control_frame = ttk.Frame(main_frame)
        ind_control_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(ind_control_frame, text="▶️ Start Selected", command=self.start_selected, width=15).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(ind_control_frame, text="⏹ Stop Selected", command=self.stop_selected, width=15).pack(side=tk.LEFT,
                                                                                                         padx=2)
        ttk.Button(ind_control_frame, text="🔄 Restart Selected", command=self.restart_selected, width=15).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(ind_control_frame, text="📄 View Log", command=self.view_log, width=15).pack(side=tk.LEFT, padx=2)

        # Footer
        footer_frame = ttk.Frame(main_frame)
        footer_frame.pack(fill=tk.X, pady=(10, 0))

        self.footer_label = ttk.Label(footer_frame, text="Ready", font=("Segoe UI", 9), foreground="gray")
        self.footer_label.pack(side=tk.LEFT)

        ttk.Label(footer_frame, text=f"Python: {PYTHON_EXE}", font=("Segoe UI", 8), foreground="gray").pack(
            side=tk.RIGHT)

        # Log window
        self.log_window = None

    def log(self, message, level="INFO"):
        """Add message to log window."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.status_text.see(tk.END)
        self.footer_label.config(text=message)
        self.root.update_idletasks()

    def is_process_running(self, script_name):
        """Check if a process is running."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if script_name in cmdline and 'python' in cmdline:
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def update_status(self):
        """Update the status display."""
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Update each script
        for script in SCRIPTS:
            pid = self.is_process_running(script["file"])
            status = "✅ Running" if pid else "❌ Stopped"
            pid_display = str(pid) if pid else "-"

            self.tree.insert("", "end", values=(status, script["name"], pid_display, script["desc"]))

        self.log("Status updated", "INFO")

    def start_script(self, script):
        """Start a single script."""
        script_path = PROJECT_ROOT / script["file"]
        if not script_path.exists():
            self.log(f"❌ Script not found: {script_path}", "ERROR")
            return False

        # Check if already running
        if self.is_process_running(script["file"]):
            self.log(f"⚠️ {script['name']} is already running", "WARNING")
            return True

        log_file = LOG_DIR / f"{script['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        try:
            # Start process with CREATE_NO_WINDOW flag
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            child_env = os.environ.copy()
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            with open(log_file, "w", encoding="utf-8", errors="replace") as f:
                f.write(f"=== {script['name']} started at {datetime.now()} ===\n")
                f.write(f"Script: {script['file']}\n")
                f.write("=" * 60 + "\n\n")
                f.flush()

                proc = subprocess.Popen(
                    [PYTHON_EXE, str(script_path)],
                    cwd=str(PROJECT_ROOT),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=child_env,
                    creationflags=creationflags,
                    start_new_session=True,
                )

            self.processes[script["name"]] = proc
            self.log(f"✅ Started: {script['name']} (PID: {proc.pid})", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"❌ Failed to start {script['name']}: {e}", "ERROR")
            return False

    def start_all(self):
        """Start all scripts."""
        self.log("▶️ Starting all services...", "INFO")
        count = 0
        for script in SCRIPTS:
            if self.start_script(script):
                count += 1
            time.sleep(0.3)
        self.log(f"✅ Started {count}/{len(SCRIPTS)} services", "SUCCESS")
        self.update_status()

    def stop_script(self, script):
        """Stop a single script."""
        pid = self.is_process_running(script["file"])
        if not pid:
            self.log(f"⚠️ {script['name']} is not running", "WARNING")
            return True

        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
            self.log(f"✅ Stopped: {script['name']} (PID: {pid})", "SUCCESS")
            return True
        except psutil.NoSuchProcess:
            self.log(f"✅ {script['name']} already stopped", "INFO")
            return True
        except psutil.TimeoutExpired:
            try:
                proc.kill()
                self.log(f"✅ Killed: {script['name']} (PID: {pid})", "SUCCESS")
                return True
            except:
                self.log(f"❌ Failed to stop {script['name']}", "ERROR")
                return False
        except Exception as e:
            self.log(f"❌ Error stopping {script['name']}: {e}", "ERROR")
            return False

    def stop_all(self):
        """Stop all scripts."""
        self.log("⏹ Stopping all services...", "INFO")
        count = 0
        for script in SCRIPTS:
            if self.stop_script(script):
                count += 1
            time.sleep(0.3)
        self.log(f"✅ Stopped {count}/{len(SCRIPTS)} services", "SUCCESS")
        self.update_status()

    def restart_all(self):
        """Restart all scripts."""
        self.log("🔄 Restarting all services...", "INFO")
        self.stop_all()
        time.sleep(2)
        self.start_all()

    def start_selected(self):
        """Start selected script from tree."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a service first")
            return

        item = selection[0]
        values = self.tree.item(item, "values")
        script_name = values[1]

        for script in SCRIPTS:
            if script["name"] == script_name:
                self.start_script(script)
                break

        self.update_status()

    def stop_selected(self):
        """Stop selected script from tree."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a service first")
            return

        item = selection[0]
        values = self.tree.item(item, "values")
        script_name = values[1]

        for script in SCRIPTS:
            if script["name"] == script_name:
                self.stop_script(script)
                break

        self.update_status()

    def restart_selected(self):
        """Restart selected script from tree."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a service first")
            return

        item = selection[0]
        values = self.tree.item(item, "values")
        script_name = values[1]

        for script in SCRIPTS:
            if script["name"] == script_name:
                self.stop_script(script)
                time.sleep(1)
                self.start_script(script)
                break

        self.update_status()

    def view_log(self):
        """View log for selected script."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a service first")
            return

        item = selection[0]
        values = self.tree.item(item, "values")
        script_name = values[1]

        # Find latest log file
        log_files = list(LOG_DIR.glob(f"{script_name.replace(' ', '_')}_*.log"))
        if not log_files:
            messagebox.showinfo("No Logs", f"No log files found for {script_name}")
            return

        latest_log = max(log_files, key=lambda p: p.stat().st_mtime)

        # Open log in new window
        self.show_log_window(latest_log)

    def show_log_window(self, log_file):
        """Display log file in a new window."""
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.destroy()

        self.log_window = tk.Toplevel(self.root)
        self.log_window.title(f"Log Viewer - {log_file.name}")
        self.log_window.geometry("800x500")

        # Log text area
        log_text = scrolledtext.ScrolledText(self.log_window, font=("Consolas", 9))
        log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                log_text.insert(tk.END, content)
                log_text.see(tk.END)
        except Exception as e:
            log_text.insert(tk.END, f"Error reading log: {e}")

        # Bottom buttons
        btn_frame = ttk.Frame(self.log_window)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(btn_frame, text="🔄 Refresh", command=lambda: self.refresh_log(log_text, log_file)).pack(side=tk.LEFT,
                                                                                                           padx=2)
        ttk.Button(btn_frame, text="📋 Copy", command=lambda: self.copy_log(log_text)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📁 Open Folder", command=lambda: self.open_log_folder()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="❌ Close", command=self.log_window.destroy).pack(side=tk.RIGHT, padx=2)

    def refresh_log(self, log_text, log_file):
        """Refresh log content."""
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                log_text.delete(1.0, tk.END)
                log_text.insert(tk.END, content)
                log_text.see(tk.END)
        except Exception as e:
            log_text.insert(tk.END, f"Error refreshing log: {e}")

    def copy_log(self, log_text):
        """Copy log content to clipboard."""
        content = log_text.get(1.0, tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        messagebox.showinfo("Copied", "Log content copied to clipboard")

    def open_logs(self):
        """Open logs folder."""
        self.open_folder(LOG_DIR)

    def open_log_folder(self):
        """Open logs folder."""
        self.open_folder(LOG_DIR)

    def open_folder(self, folder):
        """Open folder in file explorer."""
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def on_closing(self):
        """Handle window closing."""
        if self.processes:
            result = messagebox.askyesno("Confirm Exit", "Services are running. Stop them before exiting?")
            if result:
                self.stop_all()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = OrchestratorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
