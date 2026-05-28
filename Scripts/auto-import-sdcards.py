#!/usr/bin/env python
import os
import subprocess
import string
import ctypes
import sys
import threading
import re
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

# API-Pfad für Windows bereitstellen
RESOLVE_SCRIPT_API = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
if os.path.exists(RESOLVE_SCRIPT_API) and RESOLVE_SCRIPT_API not in sys.path:
    sys.path.append(RESOLVE_SCRIPT_API)

# ==============================================================================
# KONFIGURATION
# ==============================================================================
ALL_MEDIA_DIR = r"D:\Benutzer\Jochen\Videos"
BASE_TARGET_DIR = r"D:\Benutzer\Jochen\Videos\01-Productions"
# ==============================================================================

VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3')
DRIVE_REMOVABLE = 2

WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

def has_media_files(source_dir):
    """Prüft rekursiv, ob die SD-Karte relevante Mediendateien enthält."""
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS):
                return True
    return False

def get_media_files_from_dir(target_dir):
    """Listet alle Mediendateien im Zielordner auf, um sie Resolve als Liste zu übergeben."""
    media_files = []
    for root, _, files in os.walk(target_dir):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS):
                media_files.append(os.path.join(root, file))
    return media_files

def get_connected_sd_cards():
    """Scannt alle Windows-Laufwerke nach Wechselmedien."""
    sd_cards = {}
    kernel32 = ctypes.windll.kernel32
    volumeNameBuffer = ctypes.create_unicode_buffer(1024)
    
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drive_type = kernel32.GetDriveTypeW(drive)
            if drive_type == DRIVE_REMOVABLE:
                rc = kernel32.GetVolumeInformationW(
                    drive, volumeNameBuffer, 1024,
                    None, None, None, None, 0
                )
                if rc and volumeNameBuffer.value.strip():
                    label = volumeNameBuffer.value.strip()
                else:
                    label = f"UNKNOWN_DRIVE_{letter}"
                
                sd_cards[label] = drive
    return sd_cards

def get_or_create_bin(media_pool, parent_folder, name):
    """Sucht nach einem Bin. Wenn es existiert, wird es zurückgegeben, sonst erstellt."""
    sub_folders = parent_folder.GetSubFolderList()
    for folder in sub_folders:
        if folder.GetName() == name:
            return folder
    return media_pool.AddSubFolder(parent_folder, name)

def get_media_dates_from_card(source_dir):
    """Scannt die Karte und gruppiert gefundene Dateien nach ihrem Aufnahmetag (YYYY-MM-DD)."""
    date_groups = {}
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS):
                full_path = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(full_path)
                    date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
                    if date_str not in date_groups:
                        date_groups[date_str] = []
                    date_groups[date_str].append(full_path)
                except Exception:
                    continue
    return date_groups

def extract_start_date_from_name(project_name):
    """Extrahiert das Startdatum (Format: YYYYMMDD) aus dem Projektnamen."""
    match = re.search(r'(20\d{6})', project_name)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d')
        except ValueError:
            return None
    return None


class ResolveIngestGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Resolve Ingest Automation")
        self.root.geometry("720x600")
        self.root.minsize(600, 450)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        
        # Lock Status Variable
        self.format_permanently_locked = False
        
        # Header / Projekt-Info
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        # Rahmen für Optionen
        self.frame_options = tk.LabelFrame(root, text=" Strukturierung der Tagesordner (Kameraübergreifend synchronisiert) ", 
                                           font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_options.pack(pady=10, padx=15, fill=tk.X)
        
        self.lbl_format = tk.Label(self.frame_options, text="Format für Unterordner:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_format.pack(side=tk.LEFT, padx=10, pady=10)
        
        # Formate Definition
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
        
        # Start-Button
        self.btn_sync = tk.Button(root, text="SD-Karten synchronisieren & importieren", 
                                  command=self.start_sync_thread, font=("Helvetica", 11, "bold"),
                                  bg=self.btn_color, fg="white", activebackground="#CD3700", 
                                  padx=15, pady=5, cursor="hand2")
        self.btn_sync.pack(pady=5)
        
        # Log-Ausgabefenster
        self.log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=80, height=18, 
                                                 bg="#1A1A1A", fg="#00FF00", font=("Consolas", 9))
        self.log_area.pack(padx=15, pady=15, fill=tk.BOTH, expand=True)
        
        self.update_project_name()

    def log(self, message):
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)

    def detect_existing_format(self, project_name):
        """Prüft die Festplatte auf bereits bestehende Ingest-Strukturen dieses Projekts."""
        project_dir = os.path.join(BASE_TARGET_DIR, project_name)
        footage_dir = os.path.join(project_dir, "Footage")
        
        if not os.path.exists(footage_dir):
            return None
            
        for cam_folder in os.listdir(footage_dir):
            cam_path = os.path.join(footage_dir, cam_folder)
            if os.path.isdir(cam_path):
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
                        if detected == "YYMMDD":
                            self.combo_format.current(0)
                        elif detected == "WEEKDAY":
                            self.combo_format.current(1)
                        elif detected == "COUNTER":
                            self.combo_format.current(2)
                        
                        self.combo_format.config(state=tk.DISABLED)
                        self.frame_options.config(text=" Strukturierung der Tagesordner (Gesperrt: Format aus bestehendem Ingest erkannt) ", fg="#FFCC00")
                    else:
                        self.format_permanently_locked = False
                        self.combo_format.config(state="readonly")
                        self.frame_options.config(text=" Strukturierung der Tagesordner (Kameraübergreifend synchronisiert) ", fg="#5CACEE")
                    return
            self.lbl_project.config(text="Kein geöffnetes Projekt in Resolve gefunden!", fg="#FF3030")
        except Exception as e:
            self.lbl_project.config(text=f"Verbindung zu DaVinci Resolve nicht möglich.", fg="#FF3030")

    def start_sync_thread(self):
        self.btn_sync.config(state=tk.DISABLED)
        self.combo_format.config(state=tk.DISABLED)
        self.log_area.delete(1.0, tk.END)
        
        threading.Thread(target=self.run_sync, daemon=True).start()

    def run_sync(self):
        try:
            selected_display_name = self.combo_format.get()
            format_mode = self.formats[selected_display_name]
            
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if not resolve:
                self.log("[FEHLER] DaVinci Resolve konnte nicht initialisiert werden. Studio-Version offen?")
                return
                
            project_manager = resolve.GetProjectManager()
            current_project = project_manager.GetCurrentProject()
            
            if not current_project:
                self.log("[FEHLER] Es ist kein Projekt in DaVinci Resolve geöffnet!")
                return
            
            project_name = current_project.GetName()
            
            project_start_date = extract_start_date_from_name(project_name)
            
            if format_mode == "COUNTER" and not project_start_date:
                self.log("[ABBRUCH] Für die Option 'Durchgezählte Tage' muss ein valides Datum im Format YYYYMMDD im Projektnamen enthalten sein!")
                return
            elif project_start_date:
                self.log(f"Erkanntes Projekt-Startdatum (Tag 1): {project_start_date.strftime('%Y-%m-%d')}")
            else:
                self.log("[INFO] Kein Datum im Projektnamen gefunden. Kalender-Modi nutzen das Datei-Änderungsdatum.")

            project_dir = os.path.join(BASE_TARGET_DIR, project_name)
            
            if not os.path.exists(project_dir):
                self.log(f"[ERSTSTART] Erstelle Projektverzeichnis: {project_dir}")
                os.makedirs(project_dir, exist_ok=True)
            else:
                self.log(f"[WIEDERHOLTER START] Projektverzeichnis existiert bereits.")

            footage_dir = os.path.join(project_dir, "Footage")
            detected_sd_cards = get_connected_sd_cards()
            
            if not detected_sd_cards:
                self.log("\n[HINWEIS] Keine angeschlossenen SD-Karten gefunden.")
                return
                
            media_pool = current_project.GetMediaPool()
            root_folder = media_pool.GetRootFolder()
            
            self.log(f"\nEs wurden {len(detected_sd_cards)} Karte(n) erkannt. Starte Ingest (Modus: {format_mode})...")
            cards_processed = 0
            
            for label, source_drive in detected_sd_cards.items():
                if not has_media_files(source_drive):
                    self.log(f"\n[ÜBERSPRUNGEN] Karte '{label}' ({source_drive}) enthält keine Medien.")
                    continue
                    
                cards_processed += 1
                self.log(f"\n[VERARBEITE] Karte '{label}' auf Laufwerk {source_drive}")
                
                os.makedirs(footage_dir, exist_ok=True)
                cam_base_target_dir = os.path.join(footage_dir, label)
                os.makedirs(cam_base_target_dir, exist_ok=True)
                
                footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
                cam_bin = get_or_create_bin(media_pool, footage_bin, label)
                
                date_groups = get_media_dates_from_card(source_drive)
                sorted_days = sorted(list(date_groups.keys()))
                
                if format_mode != "NONE":
                    self.log(f"-> Ordne Clips von {len(sorted_days)} Tag(en) Unterordnern zu.")
                    
                    for day_str in sorted_days:
                        day_obj = datetime.strptime(day_str, '%Y-%m-%d')
                        
                        if format_mode == "YYMMDD":
                            sub_folder_name = day_obj.strftime('%y%m%d')
                        elif format_mode == "WEEKDAY":
                            sub_folder_name = WEEKDAYS_DE[day_obj.weekday()]
                        elif format_mode == "COUNTER":
                            delta_days = (day_obj - project_start_date).days
                            projekttag_nummer = delta_days + 1
                            
                            if projekttag_nummer < 1:
                                sub_folder_name = f"Tag-VorStart_{day_obj.strftime('%y%m%d')}"
                            else:
                                sub_folder_name = f"Tag-{str(projekttag_nummer).zfill(2)}"
                        
                        day_target_dir = os.path.join(cam_base_target_dir, sub_folder_name)
                        os.makedirs(day_target_dir, exist_ok=True)
                        
                        self.log(f"   -> Übertrage Clips vom Kalendertag '{day_str}' nach Ziel: {sub_folder_name} ...")
                        
                        for file_path in date_groups[day_str]:
                            file_name = os.path.basename(file_path)
                            cmd = ["robocopy", os.path.dirname(file_path), day_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        
                        day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
                        media_pool.SetCurrentFolder(day_bin)
                        
                        clips_to_import = get_media_files_from_dir(day_target_dir)
                        if clips_to_import:
                            self.log(f"   -> Importiere {len(clips_to_import)} Clips in Bin: {label} -> {sub_folder_name}")
                            media_pool.ImportMedia(clips_to_import)
                else:
                    self.log(f"-> Synchronisiere alle Dateien direkt nach: {cam_base_target_dir} ...")
                    cmd = ["robocopy", source_drive, cam_base_target_dir, "/E", "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, text=True, bufsize=1)
                    for line in process.stdout:
                        if line.strip():
                            self.log(f"  > {line.strip()}")
                    process.wait()
                    
                    media_pool.SetCurrentFolder(cam_bin)
                    clips_to_import = get_media_files_from_dir(cam_base_target_dir)
                    
                    if clips_to_import:
                        self.log(f"Importiere {len(clips_to_import)} Clips in Resolve Bin 'Footage -> {label}'...")
                        media_pool.ImportMedia(clips_to_import)
                    else:
                        self.log("Keine neuen Clips zum Importieren gefunden.")
                        
            if cards_processed == 0:
                self.log("\n[FERTIG] Keine der Karten enthielt relevante Mediendateien.")
            else:
                self.log("\n[FERTIG] Synchronisation und Import erfolgreich beendet!")
                
        except Exception as e:
            self.log(f"\n[UNERWARTETER FEHLER] {e}")
        finally:
            self.root.after(0, lambda: self.btn_sync.config(state=tk.NORMAL))
            if not self.format_permanently_locked:
                self.root.after(0, lambda: self.combo_format.config(state="readonly"))


if __name__ == "__main__":
    root = tk.Tk()
    app = ResolveIngestGUI(root)
    root.mainloop()