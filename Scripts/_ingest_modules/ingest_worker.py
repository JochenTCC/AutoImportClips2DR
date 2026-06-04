#!/usr/bin/env python
import os
from datetime import datetime

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
from .proxy_generator import render_and_link_proxies_ffmpeg, render_and_link_proxies_DR_Engine


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings):
    """Verarbeitet eine SD-Karte oder ein lokales Verzeichnis mit optionaler Timeline-Generierung."""
    log_callback(f"\n[INFO] Verarbeite Medienquelle/Label '{label}'...")
    
    clip_color = get_clip_color_by_label(label, camera_colors)
    log_callback(f"   -> Zugewiesene Resolve-Clipfarbe: {clip_color}")
    
    camera_type = "UNKNOWN"
    label_upper = label.upper()
    for key in camera_colors.keys():
        key_upper = key.upper()
        parts = key_upper.split('_')
        matched = False
        for part in parts:
            if len(part) > 2 and part in label_upper:
                camera_type = part
                matched = True
                break
        if matched:
            break
    if camera_type == "UNKNOWN":
        for key in camera_colors.keys():
            if key.upper() in label_upper:
                camera_type = key.upper()
                break
        else:
            camera_type = "REC709"
            
    # Falls Medien direkt flach im Root lagen, passen wir die Basispfade an
    if label == "FOOTAGE_ROOT":
        cam_base_target_dir = footage_dir
        cam_base_proxy_dir = project_proxy_dir
        bin_label = "Footage"
    else:
        cam_base_target_dir = os.path.join(footage_dir, label)
        cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
        bin_label = label
        
    os.makedirs(cam_base_target_dir, exist_ok=True)
    
    cam_bin = get_or_create_bin(media_pool, footage_bin, bin_label)
    group_keyword = f"{camera_type}"
    
    if format_mode != "NONE":
        # Lokaler Modus: Wenn kein source_drive existiert, lesen wir die Daten direkt aus dem Zielordner
        if source_drive:
            date_groups = get_media_dates_from_card(source_drive)
        else:
            date_groups = get_media_dates_from_card(cam_base_target_dir)
            
        sorted_days = sorted(list(date_groups.keys()))
        
        for day_str in sorted_days:
            day_obj = datetime.strptime(day_str, '%Y-%m-%d')
            if format_mode == "YYMMDD": 
                sub_folder_name = day_obj.strftime('%y%m%d')
            elif format_mode == "WEEKDAY": 
                sub_folder_name = WEEKDAYS_DE[day_obj.weekday()]
            elif format_mode == "COUNTER":
                delta_days = (day_obj - project_start_date).days if project_start_date else 0
                sub_folder_name = f"Tag-{str(delta_days + 1).zfill(2)}"
            
            day_target_dir = os.path.join(cam_base_target_dir, sub_folder_name)
            day_proxy_dir = os.path.join(cam_base_proxy_dir, sub_folder_name)
            os.makedirs(day_target_dir, exist_ok=True)
            
            log_callback(f"   -> Überprüfe Clips für Datum ({sub_folder_name}):")
            
            for file_path in date_groups[day_str]:
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                
                abs_source = os.path.abspath(os.path.join(source_folder, file_name))
                abs_target = os.path.abspath(os.path.join(day_target_dir, file_name))
                
                # Robocopy nur ausführen, wenn Quelle und Ziel wirklich unterschiedlich sind
                if abs_source != abs_target:
                    log_callback(f"      [COPY] Von: {abs_source}")
                    log_callback(f"             Nach: {abs_target}")
                    copy_files_via_robocopy(source_folder, day_target_dir, file_name)
            
            day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
            pancake_timeline = None
            
            if create_pancakes:
                day_pancake_bin = get_or_create_bin(media_pool, pancakes_bin, sub_folder_name)
                media_pool.SetCurrentFolder(day_pancake_bin)
                timeline_name = f"PC_{sub_folder_name}_{camera_type}"
                
                existing_items = day_pancake_bin.GetClipList()
                for item in existing_items:
                    if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                        pancake_timeline = item
                        break
            
            media_pool.SetCurrentFolder(day_bin)
            
            # --- DOPPELTEN IMPORT IM BIN VERHINDERN ---
            existing_bin_clips = day_bin.GetClipList()
            existing_bin_filenames = {c.GetName() for c in existing_bin_clips if c}
            
            clips_on_disk = get_media_files_from_dir(day_target_dir)
            clips_to_import = [path for path in clips_on_disk if os.path.basename(path) not in existing_bin_filenames]
            
            if not clips_to_import:
                log_callback(f"   -> [INFO] Keine neuen Medien zum Importieren für {sub_folder_name} gefunden.")
                continue
                
            new_clips = media_pool.ImportMedia(clips_to_import)
            if new_clips:
                clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                valid_clips_to_add = []
                
                for clip in clip_list:
                    if not clip: continue
                    try:
                        clip.SetClipProperty("Clip Color", clip_color)
                    except Exception as color_err:
                        log_callback(f"       [HINWEIS] Farbe konnte nicht zugewiesen werden: {color_err}")
                    
                    clip_name = clip.GetName()
                    if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                        clip_path_on_disk = os.path.join(day_target_dir, clip_name)
                        raw_queue.append((clip, clip_path_on_disk, day_proxy_dir))
                    
                    valid_clips_to_add.append(clip)
                
                tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
                
                if create_pancakes and valid_clips_to_add:
                    try:
                        valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                    except Exception as sort_err:
                        log_callback(f"       [HINWEIS] Chronologische Sortierung nach TC fehlgeschlagen: {sort_err}")
                    
                    existing_clip_names = set()
                    if pancake_timeline is not None:
                        try:
                            raw_items = pancake_timeline.GetItemListInTrack("video", 1)
                            existing_timeline_items = raw_items if raw_items is not None else []
                            for item in existing_timeline_items:
                                mp_item = item.GetMediaPoolItem()
                                if mp_item:
                                    existing_clip_names.add(mp_item.GetName())
                        except Exception as api_crash_err:
                            log_callback(f"       [API HINWEIS] Track-Inhalt konnte nicht gelesen werden.")
                    
                    clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                    
                    if not clips_to_append:
                        log_callback(f"   -> [STOP] Alle importierten Clips bereits in Pancake '{timeline_name}' enthalten.")
                        continue
                    
                    if not pancake_timeline:
                        media_pool.SetCurrentFolder(day_pancake_bin)
                        first_clip = clips_to_append[0]
                        log_callback(f"   -> Erstelle Kamera-Pancake aus Erstclip: {timeline_name}")
                        pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [first_clip])
                        remaining_clips = clips_to_append[1:]
                    else:
                        log_callback(f"   -> Pancake-Timeline existiert bereits: {timeline_name} (wird erweitert)")
                        remaining_clips = clips_to_append
                    
                    if pancake_timeline is not None and remaining_clips:
                        current_project.SetCurrentTimeline(pancake_timeline)
                        log_callback(f"   -> Füge {len(remaining_clips)} weitere(n) Clip(s) der Timeline hinzu...")
                        media_pool.AppendToTimeline(remaining_clips)
                        apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
                    elif pancake_timeline is None:
                        log_callback(f"       [FEHLER] DaVinci Resolve verweigerte das Erstellen der Timeline '{timeline_name}'.")
    else:
        # Flat-Mode (format_mode == "NONE")
        if source_drive:
            log_callback(f"   -> Kopiere Clips flach in Hauptordner:")
            flattened_files = get_media_files_flattened(source_drive)
            
            for file_path in flattened_files:
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                
                abs_source = os.path.abspath(os.path.join(source_folder, file_name))
                abs_target = os.path.abspath(os.path.join(cam_base_target_dir, file_name))
                
                log_callback(f"      [COPY] Von: {abs_source}")
                log_callback(f"             Nach: {abs_target}")
                
                copy_files_via_robocopy(source_folder, cam_base_target_dir, file_name)
        else:
            log_callback(f"   -> Lokale Medien vorhanden. Überspringe Kopiervorgang.")
        
        media_pool.SetCurrentFolder(cam_bin)
        pancake_timeline = None
        timeline_name = f"PC_FLAT_{camera_type}"
        
        if create_pancakes:
            media_pool.SetCurrentFolder(pancakes_bin)
            existing_items = pancakes_bin.GetClipList()
            for item in existing_items:
                if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                    pancake_timeline = item
                    break
            
        media_pool.SetCurrentFolder(cam_bin)
        
        # --- DOPPELTEN IMPORT IM FLAT-BIN VERHINDERN ---
        existing_bin_clips = cam_bin.GetClipList()
        existing_bin_filenames = {c.GetName() for c in existing_bin_clips if c}
        
        clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
        clips_to_import = [path for path in clips_on_disk if os.path.basename(path) not in existing_bin_filenames]
        
        if not clips_to_import:
            log_callback(f"   -> [INFO] Keine neuen Medien zum Importieren für flachen Ordner gefunden.")
            return  
            
        new_clips = media_pool.ImportMedia(clips_to_import)
        if new_clips:
            clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
            valid_clips_to_add = []
            
            for clip in clip_list:
                if not clip: continue
                try:
                    clip.SetClipProperty("Clip Color", clip_color)
                except Exception as color_err:
                    log_callback(f"       [HINWEIS] Farbe konnte nicht zugewiesen werden: {color_err}")
                    
                clip_name = clip.GetName()
                if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                    clip_path_on_disk = os.path.join(cam_base_target_dir, clip_name)
                    raw_queue.append((clip, clip_path_on_disk, cam_base_proxy_dir))
                    
                valid_clips_to_add.append(clip)
            
            tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
            
            if create_pancakes and valid_clips_to_add:
                try:
                    valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                except Exception as sort_err:
                    log_callback(f"       [HINWEIS] Chronologische Sortierung nach TC fehlgeschlagen: {sort_err}")
                    
                existing_clip_names = set()
                if pancake_timeline is not None:
                    try:
                        raw_items = pancake_timeline.GetItemListInTrack("video", 1)
                        existing_timeline_items = raw_items if raw_items is not None else []
                        for item in existing_timeline_items:
                            mp_item = item.GetMediaPoolItem()
                            if mp_item:
                                            existing_clip_names.add(mp_item.GetName())
                    except Exception as api_crash_err:
                        log_callback(f"       [API HINWEIS] Track-Inhalt konnte nicht gelesen werden.")
                
                clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                
                if not clips_to_append:
                    log_callback(f"   -> [STOP] Alle Clips bereits in Pancake '{timeline_name}' enthalten.")
                    return
                
                if not pancake_timeline:
                    media_pool.SetCurrentFolder(pancakes_bin)
                    first_clip = clips_to_append[0]
                    log_callback(f"   -> Erstelle Kamera-Pancake aus Erstclip: {timeline_name}")
                    pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [first_clip])
                    remaining_clips = clips_to_append[1:]
                else:
                    log_callback(f"   -> Pancake-Timeline existiert bereits: {timeline_name} (wird erweitert)")
                    remaining_clips = clips_to_append
                
                if pancake_timeline is not None and remaining_clips:
                    current_project.SetCurrentTimeline(pancake_timeline)
                    log_callback(f"   -> Füge {len(remaining_clips)} weitere(n) Clip(s) der Timeline hinzu...")
                    media_pool.AppendToTimeline(remaining_clips)
                    apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
                elif pancake_timeline is None:
                    log_callback(f"       [FEHLER] DaVinci Resolve verweigerte das Erstellen der Timeline '{timeline_name}'.")


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors=None, base_drx_dir="", camera_mappings=None, base_target_dir="", base_proxy_dir=""):
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
        
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        
        footage_bin, pancakes_bin = create_resolve_bins(media_pool, root_folder)
        
        # Versuche SD-Karten zu erkennen
        detected_sd_cards = get_connected_sd_cards()
        
        # --- FALLBACK: LOKALER MODUS (WENN KEINE SD-KARTEN ERKANNT WURDEN) ---
        if not detected_sd_cards:
            log_callback("\n[HINWEIS] Keine SD-Karten gefunden. Suche nach lokalen Medien im Projektverzeichnis...")
            if os.path.exists(footage_dir):
                # 1. Scanne nach Unterordnern (z. B. Kamera-Labels wie CAM_A, GH6, DJI_AVATA)
                for item in os.listdir(footage_dir):
                    if os.path.isdir(os.path.join(footage_dir, item)) and item.lower() != "proxies":
                        detected_sd_cards[item] = None  # None signalisiert: Bereits lokal auf HDD
                
                # 2. Falls keine Unterordner existieren, aber Clips direkt flach im Footage-Ordner liegen
                if not detected_sd_cards:
                    from .utils import get_media_files_from_dir
                    if get_media_files_from_dir(footage_dir):
                        detected_sd_cards["FOOTAGE_ROOT"] = None
        
        if not detected_sd_cards:
            log_callback("[FEHLER] Weder SD-Karten noch lokale Medien im Zielverzeichnis gefunden.")
            return
            
        raw_queue = []
        log_callback("[SCHRITT 1/2] Analysiere Medienquellen und importiere in DaVinci Resolve...")
        
        for label, source_drive in detected_sd_cards.items():
            # Nur bei echten SD-Karten vorab prüfen, ob Medien existieren
            if source_drive and not has_media_files(source_drive):
                continue
            
            process_single_sd_card(
                label, source_drive, format_mode, project_start_date,
                footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                base_drx_dir, camera_mappings
            )
        
        if raw_queue:
            render_and_link_proxies_ffmpeg(raw_queue, use_h265, log_callback)
            # render_and_link_proxies_DR_Engine(raw_queue, use_h265, log_callback, current_project)
        
            log_callback("\n[FERTIG] Synchronisation, Metadaten-Tagging und Proxy-Verknüpfungen beendet!")
            
            try:
                if resolve.OpenPage("edit"):
                    log_callback("[GUI] Erfolgreich auf die Edit-Page gewechselt.")
                else:
                    log_callback("[GUI HINWEIS] Wechsel zur Edit-Page von Resolve blockiert.")
            except Exception as page_err:
                log_callback(f"[GUI WARNUNG] Seitenwechsel konnte nicht ausgeführt werden: {page_err}")

    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")