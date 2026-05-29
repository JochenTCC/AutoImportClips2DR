#!/usr/bin/env python
import os
import subprocess
import string
import ctypes
import sys
import threading
import re
from datetime import datetime
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
BASE_PROXY_DIR = r"D:\Benutzer\Jochen\Videos\04-DR-Folders\ProxyMedia"
# ==============================================================================

VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3')
PROXY_ELIGIBLE_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw')
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
    """Listet alle Mediendateien im Zielordner auf."""
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
        self.root.title("Resolve Ingest Automation (Stable Queue Optimized)")
        self.root.geometry("750x660")
        self.root.minsize(650, 500)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        self.format_permanently_locked = False
        
        # 1. Projekt-Label
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        # 2. Frame für Ordnerstruktur
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
        
        # 3. Frame für Proxy-Einstellungen
        self.frame_proxy_settings = tk.LabelFrame(root, text=" Proxy-Videoeinstellungen (NVIDIA NVENC beschleunigt) ", 
                                                 font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_proxy_settings.pack(pady=10, padx=15, fill=tk.X)
        
        self.lbl_codec = tk.Label(self.frame_proxy_settings, text="Proxy Video-Codec:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_codec.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.codec_options = ["H.265 / HEVC (Kleinere Dateien, top GPU-Decoding)", "H.264 / AVC (Maximale Kompatibilität)"]
        self.combo_codec = ttk.Combobox(self.frame_proxy_settings, values=self.codec_options, state="readonly", width=45)
        self.combo_codec.current(0)
        self.combo_codec.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.X, expand=True)
        
        # 4. Button & Log-Fenster
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
        threading.Thread(target=self.run_sync, daemon=True).start()

    def unlock_gui_safely(self):
        try:
            self.btn_sync.config(state=tk.NORMAL)
            self.combo_codec.config(state="readonly")
            if not self.format_permanently_locked:
                self.combo_format.config(state="readonly")
        except Exception:
            pass

    def run_sync(self):
        try:
            selected_display_name = self.combo_format.get()
            format_mode = self.formats[selected_display_name]
            use_h265 = "H.265" in self.combo_codec.get()
            
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if not resolve:
                self.log("[FEHLER] DaVinci Resolve konnte nicht initialisiert werden.")
                return
                
            project_manager = resolve.GetProjectManager()
            current_project = project_manager.GetCurrentProject()
            if not current_project:
                self.log("[FEHLER] Es ist kein Projekt geöffnet!")
                return
            
            project_name = current_project.GetName()
            project_start_date = extract_start_date_from_name(project_name)
            
            project_dir = os.path.join(BASE_TARGET_DIR, project_name)
            project_proxy_dir = os.path.join(BASE_PROXY_DIR, project_name)
            os.makedirs(project_dir, exist_ok=True)
            footage_dir = os.path.join(project_dir, "Footage")
            
            detected_sd_cards = get_connected_sd_cards()
            if not detected_sd_cards:
                self.log("\n[HINWEIS] Keine SD-Karten gefunden.")
                return
                
            media_pool = current_project.GetMediaPool()
            root_folder = media_pool.GetRootFolder()
            cards_processed = 0
            
            # Speicher für die gesammelten Ingest-Aufgaben
            raw_queue = []
            
            # --- SCHRITT 1: DATEIEN KOPIEREN & IN RESOLVE IMPORTIEREN ---
            self.log("[SCHRITT 1/2] Kopiere Dateien von SD-Karten und importiere Medien...")
            
            for label, source_drive in detected_sd_cards.items():
                if not has_media_files(source_drive):
                    continue
                    
                cards_processed += 1
                self.log(f"\n[GEFUNDEN] Verarbeite Karte '{label}'...")
                
                cam_base_target_dir = os.path.join(footage_dir, label)
                cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
                
                footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
                cam_bin = get_or_create_bin(media_pool, footage_bin, label)
                
                date_groups = get_media_dates_from_card(source_drive)
                sorted_days = sorted(list(date_groups.keys()))
                
                if format_mode != "NONE":
                    for day_str in sorted_days:
                        day_obj = datetime.strptime(day_str, '%Y-%m-%d')
                        if format_mode == "YYMMDD": sub_folder_name = day_obj.strftime('%y%m%d')
                        elif format_mode == "WEEKDAY": sub_folder_name = WEEKDAYS_DE[day_obj.weekday()]
                        elif format_mode == "COUNTER":
                            delta_days = (day_obj - project_start_date).days if project_start_date else 0
                            sub_folder_name = f"Tag-{str(delta_days + 1).zfill(2)}"
                        
                        day_target_dir = os.path.join(cam_base_target_dir, sub_folder_name)
                        day_proxy_dir = os.path.join(cam_base_proxy_dir, sub_folder_name)
                        os.makedirs(day_target_dir, exist_ok=True)
                        
                        self.log(f"   -> Kopiere Clips nach: Footage/{label}/{sub_folder_name}")
                        for file_path in date_groups[day_str]:
                            file_name = os.path.basename(file_path)
                            cmd = ["robocopy", os.path.dirname(file_path), day_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        
                        day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
                        media_pool.SetCurrentFolder(day_bin)
                        
                        clips_on_disk = get_media_files_from_dir(day_target_dir)
                        if clips_on_disk:
                            new_clips = media_pool.ImportMedia(clips_on_disk)
                            if new_clips:
                                clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                                for clip in clip_list:
                                    if not clip: continue
                                    clip_name = clip.GetName()
                                    if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                        clip_path_on_disk = os.path.join(day_target_dir, clip_name)
                                        raw_queue.append((clip, clip_path_on_disk, day_proxy_dir))
                else:
                    self.log(f"   -> Kopiere Clips direkt nach: Footage/{label}")
                    cmd = ["robocopy", source_drive, cam_base_target_dir, "/E", "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    media_pool.SetCurrentFolder(cam_bin)
                    clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
                    if clips_on_disk:
                        new_clips = media_pool.ImportMedia(clips_on_disk)
                        if new_clips:
                            clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                            for clip in clip_list:
                                if not clip: continue
                                clip_name = clip.GetName()
                                if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                    clip_path_on_disk = os.path.join(cam_base_target_dir, clip_name)
                                    raw_queue.append((clip, clip_path_on_disk, cam_base_proxy_dir))
            
            # --- SCHRITT 2: SCHLEIFEN-BASIERTE QUEUE (PRO CLIP EIN UNSICHTBARER START) ---
            if raw_queue:
                # Filtere heraus, was wirklich neu berechnet werden muss
                render_jobs = []
                for clip, source_path, proxy_dir in raw_queue:
                    clip_name = os.path.basename(source_path)
                    expected_proxy_path = os.path.join(proxy_dir, clip_name)
                    os.makedirs(proxy_dir, exist_ok=True)
                    
                    if os.path.exists(expected_proxy_path):
                        self.log(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
                        try: clip.LinkProxyMedia(expected_proxy_path)
                        except Exception: pass
                    else:
                        render_jobs.append((clip, source_path, expected_proxy_path))
                
                if render_jobs:
                    total_jobs = len(render_jobs)
                    self.log(f"\n[SCHRITT 2/2] Starte Proxy-Generierung für {total_jobs} neue Proxies...")
                    
                    # Codec Parameter festlegen
                    if use_h265:
                        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
                    else:
                        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
                    
                    # Windows-spezifische Flags, um das Konsolenfenster unsichtbar zu halten
                    startupinfo = None
                    if sys.platform == "win32":
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = 0  # SW_HIDE (Fenster verstecken)
                    
                    # Wir gehen die Jobs nacheinander durch – absolut sicher vor Windows-Zeichenlimits
                    for idx, (clip, source_path, expected_proxy_path) in enumerate(render_jobs, start=1):
                        clip_name = os.path.basename(source_path)
                        codec_label = "H.265" if use_h265 else "H.264"
                        self.log(f"   [{idx}/{total_jobs}] Rendere {codec_label}-Proxy: {clip_name} ...")
                        
                        cmd = [
                            "ffmpeg", "-y",
                            "-hwaccel", "cuda",
                            "-i", source_path
                        ] + video_codec_args + [
                            "-vf", r"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                            "-c:a", "copy",
                            expected_proxy_path
                        ]
                        
                        try:
                            # Startet FFmpeg absolut unsichtbar im Hintergrund für diesen einen Clip
                            subprocess.run(
                                cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True,
                                startupinfo=startupinfo
                            )
                            
                            # Sofort nach erfolgreichem Render in Resolve verknüpfen
                            if os.path.exists(expected_proxy_path):
                                success = clip.LinkProxyMedia(expected_proxy_path)
                                if success:
                                    self.log(f"       -> [OK] Proxy erfolgreich verknüpft.")
                        except subprocess.CalledProcessError:
                            self.log(f"       -> [FEHLER] FFmpeg-Rendering fehlgeschlagen für {clip_name}")
                        except Exception as e:
                            self.log(f"       -> [API FEHLER] Verknüpfung fehlgeschlagen: {e}")
                            
                else:
                    self.log("\n[HINWEIS] Keine neuen Videos zum Rendern in der Queue.")
            
            self.log("\n[FERTIG] Synchronisation, optimiertes Batch-Rendering und Proxy-Verknüpfungen beendet!")
        except Exception as e:
            self.log(f"\n[UNERWARTETER FEHLER] {e}")
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(0, self.unlock_gui_safely)

if __name__ == "__main__":
    root = tk.Tk()
    app = ResolveIngestGUI(root)
    root.mainloop()#!/usr/bin/env python
import os
import subprocess
import string
import ctypes
import sys
import threading
import re
from datetime import datetime
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
BASE_PROXY_DIR = r"D:\Benutzer\Jochen\Videos\04-DR-Folders\ProxyMedia"
# ==============================================================================

VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3')
PROXY_ELIGIBLE_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw')
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
    """Listet alle Mediendateien im Zielordner auf."""
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
        self.root.title("Resolve Ingest Automation (Stable Queue Optimized)")
        self.root.geometry("750x660")
        self.root.minsize(650, 500)
        
        self.bg_color = "#242424"
        self.fg_color = "#E0E0E0"
        self.btn_color = "#FF4500"
        
        self.root.configure(bg=self.bg_color)
        self.format_permanently_locked = False
        
        # 1. Projekt-Label
        self.lbl_project = tk.Label(root, text="Suche aktives DaVinci Resolve Projekt...", 
                                    font=("Helvetica", 12, "bold"), bg=self.bg_color, fg=self.fg_color)
        self.lbl_project.pack(pady=10)
        
        # 2. Frame für Ordnerstruktur
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
        
        # 3. Frame für Proxy-Einstellungen
        self.frame_proxy_settings = tk.LabelFrame(root, text=" Proxy-Videoeinstellungen (NVIDIA NVENC beschleunigt) ", 
                                                 font=("Helvetica", 9, "bold"), bg=self.bg_color, fg="#5CACEE", bd=1)
        self.frame_proxy_settings.pack(pady=10, padx=15, fill=tk.X)
        
        self.lbl_codec = tk.Label(self.frame_proxy_settings, text="Proxy Video-Codec:", bg=self.bg_color, fg=self.fg_color)
        self.lbl_codec.pack(side=tk.LEFT, padx=10, pady=10)
        
        self.codec_options = ["H.265 / HEVC (Kleinere Dateien, top GPU-Decoding)", "H.264 / AVC (Maximale Kompatibilität)"]
        self.combo_codec = ttk.Combobox(self.frame_proxy_settings, values=self.codec_options, state="readonly", width=45)
        self.combo_codec.current(0)
        self.combo_codec.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.X, expand=True)
        
        # 4. Button & Log-Fenster
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
        threading.Thread(target=self.run_sync, daemon=True).start()

    def unlock_gui_safely(self):
        try:
            self.btn_sync.config(state=tk.NORMAL)
            self.combo_codec.config(state="readonly")
            if not self.format_permanently_locked:
                self.combo_format.config(state="readonly")
        except Exception:
            pass

    def run_sync(self):
        try:
            selected_display_name = self.combo_format.get()
            format_mode = self.formats[selected_display_name]
            use_h265 = "H.265" in self.combo_codec.get()
            
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if not resolve:
                self.log("[FEHLER] DaVinci Resolve konnte nicht initialisiert werden.")
                return
                
            project_manager = resolve.GetProjectManager()
            current_project = project_manager.GetCurrentProject()
            if not current_project:
                self.log("[FEHLER] Es ist kein Projekt geöffnet!")
                return
            
            project_name = current_project.GetName()
            project_start_date = extract_start_date_from_name(project_name)
            
            project_dir = os.path.join(BASE_TARGET_DIR, project_name)
            project_proxy_dir = os.path.join(BASE_PROXY_DIR, project_name)
            os.makedirs(project_dir, exist_ok=True)
            footage_dir = os.path.join(project_dir, "Footage")
            
            detected_sd_cards = get_connected_sd_cards()
            if not detected_sd_cards:
                self.log("\n[HINWEIS] Keine SD-Karten gefunden.")
                return
                
            media_pool = current_project.GetMediaPool()
            root_folder = media_pool.GetRootFolder()
            cards_processed = 0
            
            # Speicher für die gesammelten Ingest-Aufgaben
            raw_queue = []
            
            # --- SCHRITT 1: DATEIEN KOPIEREN & IN RESOLVE IMPORTIEREN ---
            self.log("[SCHRITT 1/2] Kopiere Dateien von SD-Karten und importiere Medien...")
            
            for label, source_drive in detected_sd_cards.items():
                if not has_media_files(source_drive):
                    continue
                    
                cards_processed += 1
                self.log(f"\n[GEFUNDEN] Verarbeite Karte '{label}'...")
                
                cam_base_target_dir = os.path.join(footage_dir, label)
                cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
                
                footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
                cam_bin = get_or_create_bin(media_pool, footage_bin, label)
                
                date_groups = get_media_dates_from_card(source_drive)
                sorted_days = sorted(list(date_groups.keys()))
                
                if format_mode != "NONE":
                    for day_str in sorted_days:
                        day_obj = datetime.strptime(day_str, '%Y-%m-%d')
                        if format_mode == "YYMMDD": sub_folder_name = day_obj.strftime('%y%m%d')
                        elif format_mode == "WEEKDAY": sub_folder_name = WEEKDAYS_DE[day_obj.weekday()]
                        elif format_mode == "COUNTER":
                            delta_days = (day_obj - project_start_date).days if project_start_date else 0
                            sub_folder_name = f"Tag-{str(delta_days + 1).zfill(2)}"
                        
                        day_target_dir = os.path.join(cam_base_target_dir, sub_folder_name)
                        day_proxy_dir = os.path.join(cam_base_proxy_dir, sub_folder_name)
                        os.makedirs(day_target_dir, exist_ok=True)
                        
                        self.log(f"   -> Kopiere Clips nach: Footage/{label}/{sub_folder_name}")
                        for file_path in date_groups[day_str]:
                            file_name = os.path.basename(file_path)
                            cmd = ["robocopy", os.path.dirname(file_path), day_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        
                        day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
                        media_pool.SetCurrentFolder(day_bin)
                        
                        clips_on_disk = get_media_files_from_dir(day_target_dir)
                        if clips_on_disk:
                            new_clips = media_pool.ImportMedia(clips_on_disk)
                            if new_clips:
                                clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                                for clip in clip_list:
                                    if not clip: continue
                                    clip_name = clip.GetName()
                                    if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                        clip_path_on_disk = os.path.join(day_target_dir, clip_name)
                                        raw_queue.append((clip, clip_path_on_disk, day_proxy_dir))
                else:
                    self.log(f"   -> Kopiere Clips direkt nach: Footage/{label}")
                    cmd = ["robocopy", source_drive, cam_base_target_dir, "/E", "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    media_pool.SetCurrentFolder(cam_bin)
                    clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
                    if clips_on_disk:
                        new_clips = media_pool.ImportMedia(clips_on_disk)
                        if new_clips:
                            clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                            for clip in clip_list:
                                if not clip: continue
                                clip_name = clip.GetName()
                                if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                    clip_path_on_disk = os.path.join(cam_base_target_dir, clip_name)
                                    raw_queue.append((clip, clip_path_on_disk, cam_base_proxy_dir))
            
            # --- SCHRITT 2: SCHLEIFEN-BASIERTE QUEUE (PRO CLIP EIN UNSICHTBARER START) ---
            if raw_queue:
                # Filtere heraus, was wirklich neu berechnet werden muss
                render_jobs = []
                for clip, source_path, proxy_dir in raw_queue:
                    clip_name = os.path.basename(source_path)
                    expected_proxy_path = os.path.join(proxy_dir, clip_name)
                    os.makedirs(proxy_dir, exist_ok=True)
                    
                    if os.path.exists(expected_proxy_path):
                        self.log(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
                        try: clip.LinkProxyMedia(expected_proxy_path)
                        except Exception: pass
                    else:
                        render_jobs.append((clip, source_path, expected_proxy_path))
                
                if render_jobs:
                    total_jobs = len(render_jobs)
                    self.log(f"\n[SCHRITT 2/2] Starte Proxy-Generierung für {total_jobs} neue Proxies...")
                    
                    # Codec Parameter festlegen
                    if use_h265:
                        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
                    else:
                        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
                    
                    # Windows-spezifische Flags, um das Konsolenfenster unsichtbar zu halten
                    startupinfo = None
                    if sys.platform == "win32":
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = 0  # SW_HIDE (Fenster verstecken)
                    
                    # Wir gehen die Jobs nacheinander durch – absolut sicher vor Windows-Zeichenlimits
                    for idx, (clip, source_path, expected_proxy_path) in enumerate(render_jobs, start=1):
                        clip_name = os.path.basename(source_path)
                        codec_label = "H.265" if use_h265 else "H.264"
                        self.log(f"   [{idx}/{total_jobs}] Rendere {codec_label}-Proxy: {clip_name} ...")
                        
                        cmd = [
                            "ffmpeg", "-y",
                            "-hwaccel", "cuda",
                            "-i", source_path
                        ] + video_codec_args + [
                            "-vf", r"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                            "-c:a", "copy",
                            expected_proxy_path
                        ]
                        
                        try:
                            # Startet FFmpeg absolut unsichtbar im Hintergrund für diesen einen Clip
                            subprocess.run(
                                cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True,
                                startupinfo=startupinfo
                            )
                            
                            # Sofort nach erfolgreichem Render in Resolve verknüpfen
                            if os.path.exists(expected_proxy_path):
                                success = clip.LinkProxyMedia(expected_proxy_path)
                                if success:
                                    self.log(f"       -> [OK] Proxy erfolgreich verknüpft.")
                        except subprocess.CalledProcessError:
                            self.log(f"       -> [FEHLER] FFmpeg-Rendering fehlgeschlagen für {clip_name}")
                        except Exception as e:
                            self.log(f"       -> [API FEHLER] Verknüpfung fehlgeschlagen: {e}")
                            
                else:
                    self.log("\n[HINWEIS] Keine neuen Videos zum Rendern in der Queue.")
            
            self.log("\n[FERTIG] Synchronisation, optimiertes Batch-Rendering und Proxy-Verknüpfungen beendet!")
        except Exception as e:
            self.log(f"\n[UNERWARTETER FEHLER] {e}")
        finally:
            if self.root and self.root.winfo_exists():
                self.root.after(0, self.unlock_gui_safely)

if __name__ == "__main__":
    root = tk.Tk()
    app = ResolveIngestGUI(root)
    root.mainloop()