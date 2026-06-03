#!/usr/bin/env python
import os
from datetime import datetime

# BASE_TARGET_DIR und BASE_PROXY_DIR hier entfernt, da sie dynamisch übergeben werden
from .config import PROXY_ELIGIBLE_EXTENSIONS, WEEKDAYS_DE
from .utils import (
    get_connected_sd_cards, has_media_files, get_media_dates_from_card,
    extract_start_date_from_name, get_media_files_from_dir, get_media_files_flattened
)
from .drive_ops import create_physical_directories, copy_files_via_robocopy
from .resolve_media import (
    get_or_create_bin, create_resolve_bins, get_clip_color_by_label,
    tag_media_pool_items, apply_drx_grading_to_timeline
)
from .proxy_generator import render_and_link_proxies


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings):
    """Verarbeitet eine einzelne SD-Karte mit optionaler Timeline-Generierung."""
    log_callback(f"\n[GEFUNDEN] Verarbeite Karte '{label}'...")
    
    clip_color = get_clip_color_by_label(label, camera_colors)
    log_callback(f"   -> Zugewiesene Clip-Farbe für {label}: {clip_color}")
    
    # 1. Datums-Gruppen von der Karte einlesen
    date_groups = get_media_dates_from_card(source_drive)
    if not date_groups:
        log_callback(f"   -> Keine relevanten Mediendateien auf Karte '{label}' gefunden.")
        return
        
    for date_str, source_files in date_groups.items():
        # Physische Zielpfade für Footage und Proxies anhand des Modus ermitteln
        target_dir, proxy_dir = create_physical_directories(
            format_mode, project_start_date, date_str, label, footage_dir, project_proxy_dir
        )
        
        log_callback(f"   -> Synchronisiere {len(source_files)} Dateien nach: {os.path.basename(target_dir)}")
        
        # Dateien via Robocopy auf die Festplatte spiegeln
        copied_files = copy_files_via_robocopy(source_files, target_dir, log_callback)
        
        if not copied_files:
            # Falls nichts kopiert wurde, schauen wir nach bereits vorhandenen Dateien für den Import-Fallback
            copied_files = get_media_files_from_dir(target_dir)
            
        if copied_files:
            # Ordner-Bin im DaVinci Resolve Media Pool anlegen/holen
            cam_bin = get_or_create_bin(media_pool, footage_bin, label)
            
            # Speicherort für das Ingest-Format bestimmen (Datum/Wochentag Unterordner)
            if format_mode != "NONE":
                folder_name = os.path.basename(target_dir)
                target_bin = get_or_create_bin(media_pool, cam_bin, folder_name)
            else:
                target_bin = cam_bin
                
            # Medien in Resolve importieren
            log_callback(f"   -> Importiere {len(copied_files)} Medien in Resolve Bin: {target_bin.GetName()}...")
            imported_items = media_pool.ImportMediaFiles(copied_files)
            
            if imported_items:
                # Verschiebe Clips in das korrekte Unter-Bin
                media_pool.MoveClips(imported_items, target_bin)
                
                # Metadaten (Farbe, Keyword, Kamera-ID) setzen
                tag_media_pool_items(imported_items, label, clip_color)
                
                # DRX-Look anwenden und optionale Pancake-Timeline befüllen
                apply_drx_grading_to_timeline(
                    imported_items, label, format_mode, target_dir, current_project,
                    media_pool, pancakes_bin, create_pancakes, log_callback, base_drx_dir, camera_mappings
                )
                
                # Proxy-Queue für Schritt 2 füttern (nur Video-Dateien)
                for item in imported_items:
                    if item.GetClipProperty("Type") == "Video":
                        src_path = item.GetClipProperty("File Path")
                        if src_path and src_path.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                            raw_queue.append((item, src_path, proxy_dir))


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors, base_drx_dir, camera_mappings, base_target_dir, base_proxy_dir):
    """Hauptprozess für den Medien-Ingest und die Proxy-Generierung."""
    try:
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            log_callback("[FEHLER] DaVinci Resolve API nicht erreichbar.")
            return
            
        pm = resolve.GetProjectManager()
        current_project = pm.GetCurrentProject()
        if not current_project:
            log_callback("[FEHLER] Kein aktives Projekt in Resolve geöffnet.")
            return
            
        project_name = current_project.GetName()
        log_callback(f"=== STARTE INGEST-AUTOMATISIERUNG FÜR PROJEKT: {project_name} ===")
        
        # ---------------------------------------------------------------------
        # VALIDIERUNG DER ZIELPFADE (Umsortiert auf die übergebenen Argumente)
        # ---------------------------------------------------------------------
        target_root = base_target_dir
        proxy_root = base_proxy_dir
        
        # Wenn die Pfade leer sind, brechen wir sofort mit einer klaren Fehlermeldung ab
        if not target_root:
            log_callback("\n[FEHLER] Kein gültiger Medien-Zielpfad definiert!")
            log_callback("         Bitte überprüfe den Eintrag 'BASE_TARGET_DIR' in der config.json.")
            return
            
        if not proxy_root:
            log_callback("\n[FEHLER] Kein gültiger Proxy-Zielpfad definiert!")
            log_callback("         Bitte überprüfe den Eintrag 'BASE_PROXY_DIR' in der config.json.")
            return
        
        project_dir = os.path.join(target_root, project_name)
        footage_dir = os.path.join(project_dir, "Footage")
        project_proxy_dir = os.path.join(proxy_root, project_name)
        
        # Erstelle die physische Ordner-Grundstruktur auf den Festplatten
        os.makedirs(footage_dir, exist_ok=True)
        os.makedirs(project_proxy_dir, exist_ok=True)
        log_callback(f"[INFO] Projektverzeichnis validiert: {project_dir}")
        log_callback(f"[INFO] Proxyverzeichnis validiert: {project_proxy_dir}")
        
        # Startdatum aus Projektname extrahieren
        project_start_date = extract_start_date_from_name(project_name)
        if project_start_date:
            log_callback(f"   -> Erkanntes Projekt-Startdatum: {project_start_date.strftime('%Y-%m-%d')}")
        else:
            project_start_date = datetime.now()
            log_callback(f"   -> Kein Datum im Projektnamen gefunden. Nutze aktuelles Datum: {project_start_date.strftime('%Y-%m-%d')}")
            
        # Bins in Resolve initialisieren
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        footage_bin, pancakes_bin = create_resolve_bins(media_pool, root_folder)
        
        # ---------------------------------------------------------------------
        # SCHRITT 1: SD-Karten Ingest & Synchronisation
        # ---------------------------------------------------------------------
        raw_queue = []
        detected_sd_cards = get_connected_sd_cards()
        
        if not detected_sd_cards:
            log_callback("\n[HINWEIS] Keine SD-Karten angeschlossen. Überspringe Kopiervorgang.")
            log_callback("           Scanne stattdessen vorhandenes Footage im Projekt auf fehlende Proxies...")
            
            # Lokale Funktion, um das "Footage"-Bin rekursiv nach unvollständigen Proxies zu durchsuchen
            def ScanBinRecursively(folder):
                clips = folder.GetClipList()
                for clip in clips:
                    if clip.GetClipProperty("Type") == "Video":
                        src_path = clip.GetClipProperty("File Path")
                        if src_path and os.path.exists(src_path) and src_path.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                            # Überprüfen, ob DaVinci Resolve für diesen Clip bereits ein Proxy kennt
                            has_proxy = clip.GetClipProperty("Proxy")
                            if not has_proxy or has_proxy.lower() == "none" or has_proxy == "":
                                # Struktur im Proxy-Ordner spiegeln
                                rel_path = os.path.relpath(src_path, footage_dir)
                                clip_proxy_dir = os.path.dirname(os.path.join(project_proxy_dir, rel_path))
                                raw_queue.append((clip, src_path, clip_proxy_dir))
                
                sub_folders = folder.GetSubFolderList()
                for sub in sub_folders:
                    ScanBinRecursively(sub)
                    
            ScanBinRecursively(footage_bin)
        else:
            log_callback(f"\n[SCHRITT 1/2] Kopiere Dateien von {len(detected_sd_cards)} SD-Karten...")
            for label, source_drive in detected_sd_cards.items():
                if not has_media_files(source_drive):
                    continue
                
                process_single_sd_card(
                    label, source_drive, format_mode, project_start_date,
                    footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                    pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                    base_drx_dir, camera_mappings
                )
        
        # ---------------------------------------------------------------------
        # SCHRITT 2: Proxy-Generierung (FFmpeg)
        # ---------------------------------------------------------------------
        if raw_queue:
            render_and_link_proxies(raw_queue, use_h265, log_callback)
            log_callback("\n[FERTIG] Synchronisation, Metadaten-Tagging und Proxy-Verknüpfungen beendet!")
            
            # AUTOMATISCHER SEITENWECHSEL: Schaltet Resolve sauber auf die Edit-Page um
            try:
                if resolve.OpenPage("edit"):
                    log_callback("[GUI] Erfolgreich auf die Edit-Page gewechselt.")
                else:
                    log_callback("[GUI HINWEIS] Wechsel zur Edit-Page von Resolve blockiert.")
            except Exception as page_err:
                log_callback(f"[GUI WARNUNG] Seitenwechsel nicht möglich: {page_err}")
        else:
            log_callback("\n[FERTIG] Keine neuen oder unvollständigen Medien für die Proxy-Generierung gefunden.")
            
    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] Kritischer Abbruch im Hauptprozess: {e}")