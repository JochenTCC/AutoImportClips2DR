#!/usr/bin/env python
import os
import re
import threading
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

# Importe aus dem Unterordner
from _ingest_modules.config import BASE_TARGET_DIR, WEEKDAYS_DE, VALID_EXTENSIONS
from _ingest_modules.ingest_worker import run_ingest_process

class ResolveIngestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Resolve Ingest Automation (Modular)")
        self.root.geometry("750x660")
        self.root.minsize(650, 500)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        self.format_permanently_locked = False
        
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        self.frame_options = tk.LabelFrame(root, text=" Strukturierung der Tagesordner ", 
                                           font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_options.pack(pady=5, padx=15, fill=tk.X)
        
        self.lbl_format = tk.Label(self.frame_options, text="Format für Unterordner:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_format.pack(side=tk.LEFT, padx=10, pady=10)
        
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
        
        self.combo_format = ttk.Combobox(self.frame_options, values=self.format_keys, state="readonly", width=45)
        self.combo_format.current(0)
        self.combo_format.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.X, expand=True)
        
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
                        self.combo_format.config(state=tk.DISABLED)
                        self.frame_options.config(text=" Strukturierung (Gesperrt: Format aus bestehendem Ingest erkannt) ", fg="#FFCC00")
                    else:
                        self.format_permanently_locked = False
                        self.combo_format.config(state="readonly")
                    return
            self.lbl_project.config(text="Kein geöffnetes Projekt in Resolve gefunden!", fg="#FF3030")
        except Exception:
            self.lbl_project.config(text="Verbindung zu DaVinci Resolve nicht möglich.", fg="#FF3030")

    def start_sync_thread(self):
        self.btn_sync.config(state=tk.DISABLED)
        self.combo_format.config(state=tk.DISABLED)
        self.combo_codec.config(state=tk.DISABLED)
        self.log_area.delete(1.0, tk.END)
        
        selected_display_name = self.combo_format.get()
        format_mode = self.formats[selected_display_name]
        use_h265 = "H.265" in self.combo_codec.get()
        
        threading.Thread(
            target=run_ingest_process, 
            args=(format_mode, use_h265, self.log), 
            daemon=True
        ).start()
        
        self.root.after(500, self.monitor_thread)

    def monitor_thread(self):
        log_content = self.log_area.get("1.0", tk.END)
        if "[FERTIG]" in log_content or "[FEHLER]" in log_content or "UNERWARTETER FEHLER" in log_content:
            self.unlock_gui_safely()
        else:
            self.root.after(500, self.monitor_thread)

    def unlock_gui_safely(self):
        try:
            self.btn_sync.config(state=tk.NORMAL)
            self.combo_codec.config(state="readonly")
            if not self.format_permanently_locked:
                self.combo_format.config(state="readonly")
        except Exception:
            pass

