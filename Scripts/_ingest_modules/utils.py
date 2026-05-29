#!/usr/bin/env python
import os
import string
import ctypes
import re
from datetime import datetime

# Relativer Import der Config innerhalb desselben Ordners
from .config import VALID_EXTENSIONS, DRIVE_REMOVABLE

def has_media_files(source_dir):
    """Prüft rekursiv, ob die SD-Karte relevante Mediendateien enthält."""
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS):
                return True
    return False

def get_media_files_from_dir(target_dir):
    """Listet alle Mediendateien im Zielordner auf (nur oberste Ebene, um Verschachtelung zu vermeiden)."""
    media_files = []
    if os.path.exists(target_dir):
        for file in os.listdir(target_dir):
            if file.lower().endswith(VALID_EXTENSIONS):
                media_files.append(os.path.join(target_dir, file))
    return media_files

def get_media_files_flattened(source_dir):
    """Sammelt alle Mediendateien einer Karte flach in einer Liste (ignoriert die Quellordner-Struktur)."""
    all_files = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.lower().endswith(VALID_EXTENSIONS):
                all_files.append(os.path.join(root, file))
    return all_files

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