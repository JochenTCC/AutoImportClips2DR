#!/usr/bin/env python
import os
import subprocess
import re
import sys

def create_physical_directories(project_name, base_target_dir, base_proxy_dir):
    """
    Erstellt alle notwendigen Verzeichnisse auf der Festplatte 
    basierend auf den übergebenen Konfigurationspfaden.
    """
    project_dir = os.path.join(base_target_dir, project_name)
    project_proxy_dir = os.path.join(base_proxy_dir, project_name)
    
    # Haupt- und Footage-Ordner
    footage_dir = os.path.join(project_dir, "Footage")
    os.makedirs(footage_dir, exist_ok=True)
    
    # Zusätzliche Asset-Ordner auf gleicher Ebene
    os.makedirs(os.path.join(project_dir, "Music"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "Images"), exist_ok=True)
    
    return project_dir, footage_dir, project_proxy_dir

def copy_files_via_robocopy(source_dir, target_dir, file_name=None, progress_callback=None):
    """
    Führt Robocopy aus und parst die Carriage-Return-Zeilen (\r) live im Hintergrund, 
    um den exakten Kopiervortschritt an das GUI-Element weiterzuleiten.
    """
    if file_name:
        cmd = ["robocopy", source_dir, target_dir, file_name, "/XO", "/NJH", "/NJS", "/NC", "/NS"]
    else:
        cmd = ["robocopy", source_dir, target_dir, "/XO", "/NJH", "/NJS", "/NC", "/NS"]
        
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        # /NDL wird weggelassen, damit Robocopy die Fortschrittszeilen auswirft
        proc = subprocess.Popen(
            cmd, 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            encoding="cp850", # Verhindert Encoding-Crashes bei Umlauten im CMD-Buffer
            startupinfo=startupinfo
        )
        
        buffer = ""
        while True:
            char = proc.stdout.read(1)
            if not char and proc.poll() is not None:
                break
            
            if char in ('\r', '\n'):
                # Robocopy gibt Werte wie "  15.4%  " oder " 80%" aus
                match = re.search(r'(\d+)[\.,]?\d*%\s*', buffer)
                if match and progress_callback:
                    pct = int(match.group(1))
                    # Begrenzen auf 99% während des Transfers, Ingest setzt auf 100
                    display_pct = min(max(pct, 0), 99)
                    progress_callback(display_pct, f"Kopiere Mediendateien... ({display_pct}%)")
                buffer = ""
            else:
                buffer += char
                
        proc.wait()
    except Exception:
        # Robocopy Fallback bei API- oder Thread-Konflikten
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)