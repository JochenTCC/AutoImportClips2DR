#!/usr/bin/env python
import os
from datetime import datetime

from .utils import (
    get_connected_sd_cards, has_media_files, extract_start_date_from_name
)
from .drive_ops import create_physical_directories
from .resolve_media import create_resolve_bins
from .proxy_generator import render_and_link_proxies_ffmpeg
from .card_processor import process_single_sd_card  # Das ausgelagerte Detail-Modul


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors=None, 
                       base_drx_dir="", camera_mappings=None, base_target_dir="", base_proxy_dir="", backup_project=True):
    """Haupt-Einstiegspunkt für den Ingest-Prozess (Orchestrator)."""
    if camera_colors is None: camera_colors = {}
    if camera_mappings is None: camera_mappings = []

    if not base_target_dir or not base_proxy_dir:
        log_callback("[FEHLER] Kritischer Programmfehler: Ziel- oder Proxy-Basispfad ist leer!")
        return
       
    try:
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            log_callback("[FEHLER] DaVinci Resolve konnte nicht initialisiert werden.")
            return
            
        project_manager = resolve.GetProjectManager()
        current_project = project_manager.GetCurrentProject()
        if not current_project:
            log_callback("[FEHLER] Es ist kein Projekt geöffnet!")
            return
        
        project_name = current_project.GetName()
        project_start_date = extract_start_date_from_name(project_name)
        
        project_dir, footage_dir, project_proxy_dir = create_physical_directories(project_name, base_target_dir, base_proxy_dir)
        
        # --- AUTOMATISCHES PROJEKT-BACKUP (.drp) ---
        if backup_project:
            try:
                log_callback("\n[BACKUP] Erstelle präventive Projekt-Sicherung...")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = os.path.join(project_dir, "Backups")
                os.makedirs(backup_dir, exist_ok=True)
                backup_path = os.path.abspath(os.path.join(backup_dir, f"{project_name}_Backup_{timestamp}.drp"))
                
                if project_manager.ExportProject(project_name, backup_path):
                    log_callback(f"   -> [ERFOLG] DRP-Projektdatei gesichert unter:\n      {backup_path}")
                else:
                    log_callback("   -> [WARNUNG] ExportProject der Resolve API schlug fehl.")
            except Exception as backup_err:
                log_callback(f"   -> [WARNUNG] Backup-Prozess abgebrochen: {backup_err}")
        
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        footage_bin, pancakes_bin = create_resolve_bins(media_pool, root_folder)
        
        # Quellen ermitteln
        detected_sd_cards = get_connected_sd_cards()
        if not detected_sd_cards and os.path.exists(footage_dir):
            log_callback("\n[HINWEIS] Keine SD-Karten gefunden. Suche nach lokalen Medien im Projektverzeichnis...")
            for item in os.listdir(footage_dir):
                if os.path.isdir(os.path.join(footage_dir, item)) and item.lower() != "proxies":
                    detected_sd_cards[item] = None
            if not detected_sd_cards:
                from .utils import get_media_files_from_dir
                if get_media_files_from_dir(footage_dir):
                    detected_sd_cards["FOOTAGE_ROOT"] = None
        
        if not detected_sd_cards:
            log_callback("[FEHLER] Weder SD-Karten noch lokale Medien im Zielverzeichnis gefunden.")
            return
            
        raw_queue = []
        log_callback("\n[SCHRITT 1/2] Analysiere Medienquellen und importiere in DaVinci Resolve...")
        
        # Schleife über alle erkannten Quellen delegiert an das neue card_processor-Modul
        for label, source_drive in detected_sd_cards.items():
            if source_drive and not has_media_files(source_drive):
                continue
            
            process_single_sd_card(
                label, source_drive, format_mode, project_start_date,
                footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                base_drx_dir, camera_mappings
            )
        
        # --- SCHRITT 2: Proxy-Generierung ---
        if raw_queue:
            render_and_link_proxies_ffmpeg(raw_queue, use_h265, log_callback)
            log_callback("\n[FERTIG] Synchronisation, Metadaten-Tagging und Proxy-Verknüpfungen beendet!")
            
            try:
                if resolve.OpenPage("edit"):
                    log_callback("[GUI] Erfolgreich auf die Edit-Page gewechselt.")
                else:
                    log_callback("[GUI HINWEIS] Wechsel zur Edit-Page von Resolve blockiert.")
            except Exception as page_err:
                log_callback(f"[GUI WARNUNG] Seitenwechsel konnte nicht ausgeführt werden: {page_err}")
        else:
            log_callback("\n[FERTIG] Ingest abgeschlossen. Keine neuen Mediendateien verarbeitet.")

    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")