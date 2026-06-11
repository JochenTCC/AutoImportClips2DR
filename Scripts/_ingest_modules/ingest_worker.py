#!/usr/bin/env python
import os
import time

from .utils import (
    get_connected_sd_cards, has_media_files, 
    extract_start_date_from_name, get_media_files_from_dir
)
from .drive_ops import create_physical_directories
from .resolve_media import (
    get_or_create_bin, create_resolve_bins, 
    get_all_filepaths_from_bin, find_all_clips_in_bin
)
from .proxy_generator import render_and_link_proxies_ffmpeg
from .source_processor import ingest_media_source

def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, config, progress_callback=None):
    """Haupt-Einstiegspunkt für den Ingest-Prozess (Orchestrator) mit Multi-Threading."""
    
    base_target_dir = config.get("BASE_TARGET_DIR", "")
    base_proxy_dir = config.get("BASE_PROXY_DIR", "")

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
        
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        footage_bin, pancakes_bin = create_resolve_bins(media_pool, root_folder)
        
        trash_bin = get_or_create_bin(media_pool, root_folder, "_Ausschuss")
        trash_filepaths = get_all_filepaths_from_bin(trash_bin)
        if trash_filepaths:
            log_callback(f"[INFO] {len(trash_filepaths)} Clips auf der Blacklist (_Ausschuss) erkannt.")
        
        detected_sd_cards = get_connected_sd_cards()
        if not detected_sd_cards:
            if os.path.exists(footage_dir):
                for item in os.listdir(footage_dir):
                    if os.path.isdir(os.path.join(footage_dir, item)) and item.lower() != "proxies":
                        detected_sd_cards[item] = None
                if not detected_sd_cards:
                    if get_media_files_from_dir(footage_dir):
                        detected_sd_cards["FOOTAGE_ROOT"] = None
        
        if not detected_sd_cards:
            log_callback("[FEHLER] Weder SD-Karten noch lokale Medien im Zielverzeichnis gefunden.")
            return
            
        # --- PIPELINE START ---
        global_start_time = time.perf_counter()
        raw_queue = []
        log_callback("[SCHRITT 1/2] Starte Ingest-Pipeline (Kopieren + Importieren)...")
        
        for label, source_drive in detected_sd_cards.items():
            if source_drive and not has_media_files(source_drive):
                continue
            
            ingest_media_source(
                label, source_drive, format_mode, project_start_date,
                footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                pancakes_bin, create_pancakes, log_callback, raw_queue, config,
                trash_filepaths=trash_filepaths, use_h265=use_h265
            )
        
        # --- PROXY GENERIERUNG (SEQUENTIELL) ---
        if raw_queue:
            render_and_link_proxies_ffmpeg(raw_queue, use_h265, log_callback)
        else:
            log_callback("\n[INFO] Keine neuen Mediendateien für Proxy-Generierung ausstehend.")
        
        # --- BENCHMARK AUSWERTUNG ---
        global_duration = time.perf_counter() - global_start_time
        log_callback(f"\n⏱  [BENCHMARK PIPELINE]")
        log_callback(f"    - Gesamte Laufzeit (Kopieren + Rendering + Linking): {global_duration:.2f} Sek ({global_duration/60:.2f} Min)")
        
        log_callback("\n[FERTIG] Synchronisation, Metadaten-Tagging und Proxy-Verknüpfungen beendet!")
        
        try:
            if resolve.OpenPage("edit"): log_callback("[GUI] Auf Edit-Page gewechselt.")
        except Exception: pass

    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")


def run_cleanup_process(log_callback):
    """Sucht nach ungenutzten Clips im Footage-Ordner und verschiebt sie in den _Ausschuss-Bin."""
    log_callback("\n[CLEANUP] Starte Bereinigung ungenutzter Clips...")
    try:
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve: return
        
        current_project = resolve.GetProjectManager().GetCurrentProject()
        if not current_project: return
        
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
        trash_bin = get_or_create_bin(media_pool, root_folder, "_Ausschuss")
        
        all_footage_clips = find_all_clips_in_bin(footage_bin)
        unused_clips = []
        
        for clip in all_footage_clips:
            usage = clip.GetClipProperty("Usage")
            if usage in ["", "0", 0, None]:
                unused_clips.append(clip)
                
        if not unused_clips:
            log_callback("[FERTIG] Keine ungenutzten Clips im Footage-Bin gefunden. Alles perfekt!")
            return
            
        if media_pool.MoveClips(unused_clips, trash_bin):
            log_callback(f"[FERTIG] {len(unused_clips)} Clip(s) nach '_Ausschuss' verschoben und blockiert!")
            
    except Exception as e:
        log_callback(f"\n[CLEANUP UNERWARTETER FEHLER] {e}")