#!/usr/bin/env python
import os
import json
import re
import threading
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

def load_config():
    # Sucht die config.json im selben Verzeichnis wie das Skript
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}

# Laden der Konfiguration
config = load_config()

# Importe aus dem Unterordner
from _ingest_modules.config import BASE_TARGET_DIR, WEEKDAYS_DE, VALID_EXTENSIONS
from _ingest_modules.ingest_worker import run_ingest_process
from main_ColMgmt import automate_color_management_by_bin # Neu importiert für die Automatisierung

class ResolveIngestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Resolve Ingest Automation (Modular)")
        self.root.geometry("750x720")  # Höhe angepasst für beide Optionen
        self.root.minsize(650, 600)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        self.format_permanently_locked = False
        
        # Style für Checkboxen anpassen (dunkles Design)
        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure("Dark.TCheckbutton", background=self.bg_color, foreground=self.fg_color, focuscolor=self.bg_color)
        self.style.map("Dark.TCheckbutton", background=[('disabled', self.bg_color)], foreground=[('disabled', '#888888')])
        
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        # --- Bereich: Strukturierung & Automatisierung ---
        self.frame_options = tk.LabelFrame(root, text=" Strukturierung & Automatisierung ", 
                                           font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_options.pack(pady=5, padx=15, fill=tk.X)
        
        # Zeile 1: Format-Dropdown
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
        
        # Zeile 2: Option für Pancake-Timelines
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
        
        self.btn_sync = tk.Button(root, text="SD-Karten synchronisieren, konvertieren & importieren", 
                                  command=self.start_sync_thread, font=("Helvetica", 11, "bold"),
                                  bg=self.btn_color, fg="white", activebackground="#CD3700", 
                                  padx=15, pady=5, cursor="hand2")
        self.btn_sync.pack(pady=5)
        
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=80, height=18, 
                                                 bg="#1A1A1A", fg="#00FF00", font=("Consolas", 9))
        self.log_area.pack(padx=15, pady=15, fill=tk.BOTH, expand=True)
        
        self.update_project_name()

    def log(self, message):
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)

    def detect_existing_format(self, project_name):
        project_dir = os.path.join(BASE_TARGET_DIR, project_name)
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
                        
                        # Alle Strukturierungs- und Automatisierungsoptionen einfrieren
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
            self.combo_format.config(state=tk.DISABLED)
            self.chk_pancakes.config(state=tk.DISABLED)
            self.chk_auto_col.config(state=tk.DISABLED)
            self.combo_codec.config(state=tk.DISABLED)
            self.log_area.delete(1.0, tk.END)
            
            selected_display_name = self.combo_format.get()
            format_mode = self.formats[selected_display_name]
            use_h265 = "H.265" in self.combo_codec.get()
            create_pancakes = self.var_create_pancakes.get()
            
            # KORREKTUR: Daten aus der config für den Worker bereitstellen
            camera_colors = config.get("camera_colors", {})
            camera_mappings = config.get("camera_mappings", [])
            base_drx_dir = config.get("BASE_DRX_DIR", r"D:\Benutzer\Jochen\Videos")

            # KORREKTUR: Alle 7 Parameter im Tuple übergeben
            threading.Thread(
                target=run_ingest_process, 
                args=(format_mode, use_h265, self.log, create_pancakes, camera_colors, base_drx_dir, camera_mappings),  
                daemon=True
            ).start()
            
            self.root.after(500, self.monitor_thread)
            
    def monitor_thread(self):
        log_content = self.log_area.get("1.0", tk.END)
        if "[FERTIG]" in log_content or "[FEHLER]" in log_content or "UNERWARTETER FEHLER" in log_content:
            # Wenn Ingest beendet und Option aktiv ist, stoße das Farbmanagement an
            if "[FERTIG]" in log_content and self.var_auto_col.get():
                self.log("\n[AUTOMATISIERUNG] Starte Farbmanagement via Metadaten an...")
                try:
                    # Ausführung im Hauptthread für maximale Stabilität mit der Resolve API
                    automate_color_management_by_bin()
                    self.log("[AUTOMATISIERUNG] Farbräume erfolgreich zugewiesen!")
                    self.log("[HINWEIS] Bitte bis auf Weiteres das \"Input Gamma\" manuell zuweisen!")
                except Exception as col_err:
                    self.log(f"[AUTOMATISIERUNG FEHLER] Fehler bei Farbraumzuweisung: {col_err}")
                    
            self.unlock_gui_safely()
        else:
            self.root.after(500, self.monitor_thread)

    def unlock_gui_safely(self):
        try:
            self.btn_sync.config(state=tk.NORMAL)
            self.combo_codec.config(state="readonly")
            if not self.format_permanently_locked:
                self.combo_format.config(state="readonly")
                self.chk_pancakes.config(state=tk.NORMAL)
                self.chk_auto_col.config(state=tk.NORMAL)
        except Exception:
            pass
            
