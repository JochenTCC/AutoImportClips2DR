import os
import subprocess
import string
import ctypes

#!/usr/bin/env python
import os
import sys

print("1. Skript erfolgreich gestartet...")

# API-Pfad für Windows bereitstellen
RESOLVE_SCRIPT_API = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
if os.path.exists(RESOLVE_SCRIPT_API) and RESOLVE_SCRIPT_API not in sys.path:
    sys.path.append(RESOLVE_SCRIPT_API)

print("2. Suchpfade für DaVinci-API wurden gesetzt...")

try:
    import DaVinciResolveScript as dvr_script
    print("3. DaVinciResolveScript-Modul erfolgreich geladen...")
except Exception as e:
    print(f"\n[FEHLER] Modul-Import fehlgeschlagen: {e}")
    sys.exit(1)

# ==============================================================================
# KONFIGURATION: Hauptverzeichnis auf deiner Festplatte anpassen!
# ==============================================================================
BASE_TARGET_DIR = r"D:\Benutzer\Jochen\Videos\01-Productions"  # <--- HIER DEINEN PFAD EINTRAGEN
# ==============================================================================

# Windows API Konstante für Wechselmedien (SD-Karten, USB-Sticks)
DRIVE_REMOVABLE = 2

def get_connected_sd_cards():
    """
    Scannt alle Windows-Laufwerke und gibt nur Wechselmedien (SD-Karten)
    mit ihrem Label und dem Laufwerksbuchstaben zurück.
    """
    sd_cards = {}
    kernel32 = ctypes.windll.kernel32
    volumeNameBuffer = ctypes.create_unicode_buffer(1024)
    
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            # Prüfen, ob es sich um ein Wechselmedium (z.B. SD-Karte) handelt
            drive_type = kernel32.GetDriveTypeW(drive)
            if drive_type == DRIVE_REMOVABLE:
                # SO MUSS ES SEIN:
                rc = kernel32.GetVolumeInformationW(
                    drive, volumeNameBuffer, 1024,
                    None, None, None, None, 0
                )
                # Wenn ein Label existiert, nutzen wir es, ansonsten nennen wir es "UNBENANNT_" + Buchstabe
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

def sync_footage():
    # 1. Verbindung zu DaVinci Resolve herstellen
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Fehler: DaVinci Resolve konnte nicht initialisiert werden. Studio-Version offen?")
        return
        
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    
    if not current_project:
        print("Fehler: Es ist kein Projekt in DaVinci Resolve geöffnet!")
        return
    
    # Projektname auslesen
    project_name = current_project.GetName()
    print(f"Aktives Resolve-Projekt: '{project_name}'")
    
    # 2. Windows-Pfade definieren
    project_dir = os.path.join(BASE_TARGET_DIR, project_name)
    footage_dir = os.path.join(project_dir, "Footage")
    
    # Erstelle die Windows-Ordner (falls noch nicht vorhanden)
    os.makedirs(footage_dir, exist_ok=True)
    
    # 3. Angeschlossene SD-Karten DYNAMISCH erkennen
    detected_sd_cards = get_connected_sd_cards()
    
    if not detected_sd_cards:
        print("\nKeine angeschlossenen SD-Karten (Wechselmedien) gefunden.")
        return
        
    # Resolve Media Pool vorbereiten
    media_pool = current_project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()
    
    # "Footage" Bin in Resolve holen oder erstellen
    footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
    
    print(f"\nEs wurden {len(detected_sd_cards)} Karte(n) erkannt. Starte Abgleich...")
    
    # 4. Über alle dynamisch gefundenen Karten iterieren
    for label, source_drive in detected_sd_cards.items():
        print(f"\n[VERARBEITE] Karte '{label}' auf Laufwerk {source_drive}")
        
        # Zielordner auf der Festplatte für diese Kamera/Karte
        cam_target_dir = os.path.join(footage_dir, label)
        os.makedirs(cam_target_dir, exist_ok=True)
        
        # --- ROBOCOPY STARTEN (Kopiert nur neue/geänderte Dateien) ---
        print(f"Synchronisiere Dateien nach: {cam_target_dir} ...")
        cmd = ["robocopy", source_drive, cam_target_dir, "/E", "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
        subprocess.run(cmd, shell=True)
        
        # --- RESOLVE BIN & IMPORT ---
        # Kamera-Bin in Resolve holen oder erstellen (wird nach dem SD-Karten-Label benannt)
        cam_bin = get_or_create_bin(media_pool, footage_bin, label)
        media_pool.SetCurrentFolder(cam_bin)
        
        # Clips in Resolve importieren (Duplikate werden von DR automatisch übersprungen)
        print(f"Importiere neue Clips in Resolve Bin 'Footage -> {label}'...")
        media_pool.ImportMedia(cam_target_dir)
        
    print("\n[FERTIG] Alle erkannten SD-Karten wurden erfolgreich synchronisiert!")

if __name__ == "__main__":
    sync_footage()