#!/usr/bin/env python
import os
import subprocess
import string
import ctypes
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
# KONFIGURATION
# ==============================================================================
# Dein Hauptverzeichnis für die echten Projektdateien
BASE_TARGET_DIR = r"D:\Benutzer\Jochen\Videos\01-Productions"

# HIER den reinen Namen des Brückenordners definieren:
BRIDGE_FOLDER_NAME = "Resolve_Media_Storage"

# Das Skript baut den vollständigen Pfad automatisch zusammen (Pfad aus deinem alten Script angepasst):
RESOLVE_BRIDGE_DIR = os.path.join(r"D:\Benutzer\Jochen\Videos\04-DR-Folders", BRIDGE_FOLDER_NAME)
# ==============================================================================

# Erlaubte Dateiendungen für den Import
VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3')
DRIVE_REMOVABLE = 2

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
            drive_type = kernel32.GetDr#!/usr/bin/env python
import os
import subprocess
import string
import ctypes
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
# KONFIGURATION
# ==============================================================================
# Dein Hauptverzeichnis für die Projektdateien.
# WICHTIG: Füge folgenden Pfad einmalig manuell in DR unter 
# Preferences -> System -> Media Storage hinzu!
ALL_MEDIA_DIR = r"D:\Benutzer\Jochen\Videos"
# Das ist der Ordner für die aktuell zu bearbeitenden Projekte
BASE_TARGET_DIR = r"D:\Benutzer\Jochen\Videos\01-Productions"
# ==============================================================================

# Erlaubte Dateiendungen für den Import
VALID_EXTENSIONS = ('.mov', '.mp4', '.mxf', '.braw', '.wav', '.mp3', '.jpg', '.jpeg', '.png', '.arw', '.cr3')
DRIVE_REMOVABLE = 2

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
    
    # Projektname dynamisch auslesen
    project_name = current_project.GetName()
    print(f"Aktives Resolve-Projekt: '{project_name}'")
    
    # Projekt-Unterverzeichnis definieren (z.B. D:\Benutzer\Jochen\Videos\01-Productions\MeinProjektName)
    project_dir = os.path.join(BASE_TARGET_DIR, project_name)
    
    # Ordner auf der Festplatte anlegen, falls er noch nicht existiert
    if not os.path.exists(project_dir):
        print(f"\n[ERSTSTART] Erstelle Projektverzeichnis: {project_dir}")
        os.makedirs(project_dir, exist_ok=True)
    else:
        print(f"\n[WIEDERHOLTER START] Projektverzeichnis existiert bereits. Überspringe Struktur-Einrichtung.")

    # Pfad für das Footage festlegen
    footage_dir = os.path.join(project_dir, "Footage")
    
    # 2. Angeschlossene SD-Karten DYNAMISCH erkennen
    detected_sd_cards = get_connected_iveTypeW(drive)
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
    
    # Pfade definieren
    project_dir = os.path.join(BASE_TARGET_DIR, project_name)
    bridge_link_path = os.path.join(RESOLVE_BRIDGE_DIR, project_name)
    
    # NEU: Nur anlegen, wenn Verzeichnis auf der Platte ODER der Symlink im Brückenordner noch fehlen
    if not os.path.exists(project_dir) or not os.path.exists(bridge_link_path):
        print("\n[ERSTSTART] Projektverzeichnis oder Medien-Brücke fehlen. Richte Strukturen ein...")
        
        # Echten Windows-Ordner erstellen
        os.makedirs(project_dir, exist_ok=True)