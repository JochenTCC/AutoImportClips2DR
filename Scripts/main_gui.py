#!/usr/bin/env python
import os
import re
import threading
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

from _ingest_modules.config import WEEKDAYS_DE, VALID_EXTENSIONS
from _ingest_modules.ingest_worker import run_ingest_process, run_cleanup_process
from main_ColMgmt import automate_color_management_by_bin

class ResolveIngestGUI:
    def __init__(self, root, config=None):
        self.root = root
        self.config = config if config is not None else {}
        
        self.root.title("Resolve Ingest Automation (Modular)")
        self.root.geometry("750x760")
        self.root.minsize(650, 650)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        self.format_permanently_locked = False
        
        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure("Dark.TCheckbutton", background=self.bg_color, foreground=self.fg_color, focuscolor=self.bg_color)
        self.style.map("Dark.TCheckbutton", background=[('disabled', self.bg_color)], foreground=[('disabled', '#888888')])
        
        # Style für die Fortschrittsanzeige anpassen (Dunkles Design)
        self.style.configure("Horizontal.TProgressbar", thickness=15, troughcolor="#333333", background=self.btn_color)
        
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        # --- Bereich: Strukturierung & Automatisierung ---
        self.frame_options = tk.LabelFrame(root, text=" Strukturierung & Automatisierung ", 
                                           font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_options.pack(pady=5, padx=15, fill=tk.X)
        
        self.frame_row1 = tk.Frame(self.frame_options, bg=self.bg_color)
        self.frame_row1.pack(fill=tk.X, padx=5, pady=2)
        
        self.lbl_format = tk.Label(self.frame_row1, text="Format für Unterordner:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_format.pack(side=tk.LEFT, padx=5, pady=5)
        
        self.format_keys = [
            "1. Datum in Kurzform (YYMMDD)",
            "2. Wochentag in Kurzform (Mo, Di, ...)",
            "3. Durchgezählte Tage ab Projektstart (Tag-01, Tag-02, ...)",
            "4. Alles in einem Verzeichnis"
        ]
        self.formats = {
            self.format_keys[0]: "YYMMDD",
            self.format_keys[1]: "WEEKDAY",
            self.format_keys[2]: "COUNTER",
            self.format_keys[3]: "NONE"
        }
        
        self.combo_format = ttk.Combobox(self.frame_row1, values=self.format_keys, state="readonly", width=45)
        self.combo_format.current(0)
        self.combo_format.pack(side=tk.LEFT, padx=10, pady=5, fill=tk.X, expand=True)
        
        self.frame_row2 = tk.Frame(self.frame_options, bg=self.bg_color)
        self.frame_row2.pack(fill=tk.X, padx=5, pady=2)
        
        self.var_create_pancakes = tk.BooleanVar(value=True)
        self.chk_pancakes = ttk.Checkbutton(
            self.frame_row2, 
            text="Clips automatisch in Kamera-Pancake-Timelines einfügen", 
            variable=self.var_create_pancakes,
            style="Dark.TCheckbutton"
        )
        self.chk_pancakes.pack(side=tk.LEFT, padx=5, pady=2)
        
        self.frame_row3 = tk.Frame(self.frame_options, bg=self.bg_color)
        self.frame_row3.pack(fill=tk.X, padx=5, pady=2)
        
        self.var_auto_col = tk.BooleanVar(value=False)
        self.chk_auto_col = ttk.Checkbutton(
            self.frame_row3, 
            text="Nach Import automatisch Input Color Space zuweisen (main_ColMgmt)", 
            variable=self.var_auto_col,
            style="Dark.TCheckbutton"
        )
        self.chk_auto_col.pack(side=tk.LEFT, padx=5, pady=2)
                
        # --- Bereich: Proxy-Einstellungen ---
        self.frame_proxy_settings = tk.LabelFrame(root, text=" Proxy-Videoeinstellungen (NVIDIA NVENC beschleunigt) ", 
                                                 font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_proxy_settings.pack(pady=10, padx=15, fill=tk.X)
        
        self.lbl_codec = tk.Label(self.frame_proxy_settings, text="Proxy Video-Codec:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_codec.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.codec_options = ["H.265 / HEVC (Kleinere Dateien, top GPU-Decoding)", "H.264 / AVC (Maximale Kompatibilität)"]
        self.combo_codec = ttk.Combobox(self.frame_proxy_settings, values=self.codec_options, state="readonly", width=45)
        self.combo_codec.current(0)
        self.combo_codec.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.X, expand=True)
        
        # Horizontales Frame für zwei Buttons nebeneinander
        self.frame_buttons = tk.Frame(root, bg=self.bg_color)
        self.frame_buttons.pack(pady=5)
        
        self.btn_sync = tk.Button(self.frame_buttons, text="SD-Karten synchronisieren, konvertieren & importieren", 
                                  command=self.start_sync_thread, font=("Helvetica", 11, "bold"),
                                  bg=self.btn_color, fg="white", activebackground="#CD3700", 
                                  padx=15, pady=5, cursor="hand2")
        self.btn_sync.pack(side=tk.LEFT, padx=5)
        
        self.btn_cleanup = tk.Button(self.frame_buttons, text="Timeline-Ausschuss bereinigen", 
                                     command=self.start_cleanup_thread, font=("Helvetica", 11, "bold"),
                                     bg="#4A4A4A", fg="white", activebackground="#6A6A6A", 
                                     padx=15, pady=5, cursor="hand2")
        self.btn_cleanup.pack(side=tk.LEFT, padx=5)
        
        # --- NEU: Bereich für Status-Anzeige und Fortschrittsbalken ---
        self.frame_progress = tk.Frame(root, bg=self.bg_color)
        self.frame_progress.pack(fill=tk.X, padx=15, pady=5)
        
        self.lbl_status = tk.Label(self.frame_progress, text="Status: Bereit", font=("Helvetica", 10, "bold"), bg=self.bg_color, fg="#A0A0A0")
        self.lbl_status.pack(anchor=tk.W, pady=2)
        
        self.progress_bar = ttk.Progressbar(self.frame_progress, orient="horizontal", mode="determinate", style="Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=2)
        
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=80, height=16, 
                                                 bg="#1A1A1A", fg="#00FF00", font=("Consolas", 9))
        self.log_area.pack(padx=15, pady=10, fill=tk.BOTH, expand=True)
        
        self.update_project_name()

    def log(self, message):
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)

    def update_progress(self, percent, status_text=None):
        """Erlaubt fahrplanmäßige, thread-sichere Aktualisierungen aus den Ingest-Worker-Threads."""
        self.root.after(0, lambda: self._update_progress_ui(percent, status_text))

    def _update_progress_ui(self, percent, status_text):
        if percent is not None:
            self.progress_bar['value'] = percent
        if status_text is not None:
            self.lbl_status.config(text=f"Status: {status_text}", fg="#FF4500" if percent < 100 else "#5CACEE")

    def detect_existing_format(self, project_name):
        base_target_dir = self.config.get("BASE_TARGET_DIR", "")
        project_dir = os.path.join(base_target_dir, project_name)
        footage_dir = os.path.join(project_dir, "Footage")
        if not os.path.exists(footage_dir):
            return None
            
        for cam_folder in os.listdir(footage_dir):
            cam_path = os.path.join(footage_dir, cam_folder)
            if os.path.isdir(cam_path):
                for item in os.listdir(cam_path):
                    item_path = os.path.join(cam_path, item)
                    if os.path.isfile(item_path) and item.lower().endswith(VALID_EXTENSIONS):
                        return "NONE"
                
                for sub_folder in os.listdir(cam_path):
                    if os.path.isdir(os.path.join(cam_path, sub_folder)):
                        if re.match(r'^Tag-\d+$', sub_folder):
                            return "COUNTER"
                        if re.match(r'^\d{6}$', sub_folder):
                            return "YYMMDD"
                        if sub_folder in WEEKDAYS_DE:
                            return "WEEKDAY"
        return None

    def update_project_name(self):
        try:
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if resolve:
                pm = resolve.GetProjectManager()
                proj = pm.GetCurrentProject()
                if proj:
                    p_name = proj.GetName()
                    self.lbl_project.config(text=f"Aktives Resolve-Projekt: {p_name}", fg="#5CACEE")
                    detected = self.detect_existing_format(p_name)
                    if detected:
                        self.format_permanently_locked = True
                        if detected == "YYMMDD": self.combo_format.current(0)
                        elif detected == "WEEKDAY": self.combo_format.current(1)
                        elif detected == "COUNTER": self.combo_format.current(2)
                        elif detected == "NONE": self.combo_format.current(3)
                        
                        self.combo_format.config(state=tk.DISABLED)
                        self.chk_pancakes.config(state=tk.DISABLED)
                        self.chk_auto_col.config(state=tk.DISABLED)
                        self.frame_options.config(text=" Strukturierung & Automatisierung (Gesperrt: Einstellungen aus bestehendem Ingest aktiv) ", fg="#FFCC00")
                    else:
                        self.format_permanently_locked = False
                        self.combo_format.config(state="readonly")
                        self.chk_pancakes.config(state=tk.NORMAL)
                        self.chk_auto_col.config(state=tk.NORMAL)
                    return
            self.lbl_project.config(text="Kein geöffnetes Projekt in Resolve gefunden!", fg="#FF3030")
        except Exception:
            self.lbl_project.config(text="Verbindung zu DaVinci Resolve nicht möglich.", fg="#FF3030")

    def start_sync_thread(self):
        self.btn_sync.config(state=tk.DISABLED)
        self.btn_cleanup.config(state=tk.DISABLED)
        self.combo_format.config(state=tk.DISABLED)
        self.chk_pancakes.config(state=tk.DISABLED)
        self.chk_auto_col.config(state=tk.DISABLED)
        self.combo_codec.config(state=tk.DISABLED)
        self.log_area.delete(1.0, tk.END)
        
        self.update_progress(0, "Analysiere Speichermedien...")
        self.progress_bar.config(mode="determinate")
        
        selected_display_name = self.combo_format.get()
        format_mode = self.formats[selected_display_name]
        use_h265 = "H.265" in self.combo_codec.get()
        create_pancakes = self.var_create_pancakes.get()
        
        camera_colors = self.config.get("camera_colors", {})
        camera_mappings = self.config.get("camera_mappings", [])
        base_drx_dir = self.config.get("BASE_DRX_DIR", "")
        base_target_dir = self.config.get("BASE_TARGET_DIR", "")
        base_proxy_dir = self.config.get("BASE_PROXY_DIR", "")

        threading.Thread(
            target=run_ingest_process, 
            args=(format_mode, use_h265, self.log, create_pancakes),
            kwargs={
                "camera_colors": camera_colors,
                "base_drx_dir": base_drx_dir,
                "camera_mappings": camera_mappings,
                "base_target_dir": base_target_dir,
                "base_proxy_dir": base_proxy_dir,
                "progress_callback": self.update_progress  # Übergabe des Callbacks an Ingest
            },
            daemon=True
        ).start()
        
        self.root.after(500, self.monitor_thread)

    def start_cleanup_thread(self):
        """Startet den Bereinigungsprozess in einem Hintergrundthread mit pulsierendem Balken."""
        self.btn_sync.config(state=tk.DISABLED)
        self.btn_cleanup.config(state=tk.DISABLED)
        self.combo_format.config(state=tk.DISABLED)
        self.chk_pancakes.config(state=tk.DISABLED)
        self.chk_auto_col.config(state=tk.DISABLED)
        self.combo_codec.config(state=tk.DISABLED)
        self.log_area.delete(1.0, tk.END)
        
        self.update_progress(0, "Bereinige Timeline-Ausschuss...")
        self.progress_bar.config(mode="indeterminate")
        self.progress_bar.start(10)
        
        threading.Thread(
            target=run_cleanup_process,
            args=(self.log,),
            daemon=True
        ).start()
        
        self.root.after(500, self.monitor_cleanup_thread)
            
    def monitor_thread(self):
        log_content = self.log_area.get("1.0", tk.END)
        if "[FERTIG]" in log_content or "[FEHLER]" in log_content or "UNERWARTETER FEHLER" in log_content:
            if "[FERTIG]" in log_content and self.var_auto_col.get():
                self.update_progress(95, "Farbmanagement via Metadaten...")
                self.log("\n[AUTOMATISIERUNG] Starte Farbmanagement via Metadaten an...")
                try:
                    automate_color_management_by_bin()
                    self.log("[AUTOMATISIERUNG] Farbräume erfolgreich zugewiesen!")
                    self.log("[HINWEIS] Bitte bis auf Weiteres das \"Input Gamma\" manuell zuweisen!")
                except Exception as col_err:
                    self.log(f"[AUTOMATISIERUNG FEHLER] Fehler bei Farbraumzuweisung: {col_err}")
                    
            self.unlock_gui_safely()
        else:
            self.root.after(500, self.monitor_thread)

    def monitor_cleanup_thread(self):
        """Überwacht den Status des Cleanup-Prozesses."""
        log_content = self.log_area.get("1.0", tk.END)
        if "[FERTIG]" in log_content or "[FEHLER]" in log_content or "UNERWARTETER FEHLER" in log_content:
            self.unlock_gui_safely()
        else:
            self.root.after(500, self.monitor_cleanup_thread)

    def unlock_gui_safely(self):
        try:
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate")
            log_content = self.log_area.get("1.0", tk.END)
            if "[FERTIG]" in log_content:
                self.update_progress(100, "Vorgang erfolgreich beendet!")
            else:
                self.update_progress(0, "Vorgang mit Fehlern abgebrochen.")
                
            self.btn_sync.config(state=tk.NORMAL)
            self.btn_cleanup.config(state=tk.NORMAL)
            self.combo_codec.config(state="readonly")
            if not self.format_permanently_locked:
                self.combo_format.config(state="readonly")
                self.chk_pancakes.config(state=tk.NORMAL)
                self.chk_auto_col.config(state=tk.NORMAL)
        except Exception:
            pass