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
from .proxy_generator import render_and_link_proxies


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings):
    """Verarbeitet eine einzelne SD-Karte mit optionaler Timeline-Generierung."""
    log_callback(f"\n[GEFUNDEN] Verarbeite Karte '{label}'...")
    
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
            
    cam_base_target_dir = os.path.join(footage_dir, label)
    cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
    os.makedirs(cam_base_target_dir, exist_ok=True)
    
    cam_bin = get_or_create_bin(media_pool, footage_bin, label)
    group_keyword = f"{camera_type}"
    
    if format_mode != "NONE":
        date_groups = get_media_dates_from_card(source_drive)
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
            
            log_callback(f"   -> Kopiere Clips strukturiert nach Datum ({sub_folder_name}):")
            
            for file_path in date_groups[day_str]:
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                
                # Ermittlung der kompletten, absoluten Pfade vom Laufwerk weg
                abs_source = os.path.abspath(os.path.join(source_folder, file_name))
                abs_target = os.path.abspath(os.path.join(day_target_dir, file_name))
                
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
                
                if not pancake_timeline:
                    log_callback(f"   -> Erstelle Kamera-Pancake: {timeline_name}")
                    pancake_timeline = media_pool.CreateEmptyTimeline(timeline_name)
                else:
                    log_callback(f"   -> Pancake-Timeline existiert bereits: {timeline_name} (wird erweitert)")
            
            media_pool.SetCurrentFolder(day_bin)
            
            clips_on_disk = get_media_files_from_dir(day_target_dir)
            if clips_on_disk:
                new_clips = media_pool.ImportMedia(clips_on_disk)
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
                    
                    if create_pancakes and pancake_timeline and valid_clips_to_add:
                        try:
                            valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                        except Exception as sort_err:
                            log_callback(f"       [HINWEIS] Chronologische Sortierung nach TC fehlgeschlagen: {sort_err}")
                            
                        current_project.SetCurrentTimeline(pancake_timeline)
                        existing_timeline_items = pancake_timeline.GetItemListInTrack("video", 1)
                        existing_clip_names = set()
                        
                        if existing_timeline_items:
                            for item in existing_timeline_items:
                                mp_item = item.GetMediaPoolItem()
                                if mp_item:
                                    existing_clip_names.add(mp_item.GetName())
                        
                        clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                        
                        if clips_to_append:
                            log_callback(f"   -> Füge {len(clips_to_append)} neue(n) Clip(s) der Timeline hinzu...")
                            media_pool.AppendToTimeline(clips_to_append)
                            apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
                        else:
                            log_callback("   -> Keine neuen Clips zum Hinzufügen (bereits in Timeline vorhanden).")
    else:
        log_callback(f"   -> Kopiere Clips flach in Hauptordner:")
        flattened_files = get_media_files_flattened(source_drive)
        
        for file_path in flattened_files:
            file_name = os.path.basename(file_path)
            source_folder = os.path.dirname(file_path)
            
            # Ermittlung der kompletten, absoluten Pfade vom Laufwerk weg
            abs_source = os.path.abspath(os.path.join(source_folder, file_name))
            abs_target = os.path.abspath(os.path.join(cam_base_target_dir, file_name))
            
            log_callback(f"      [COPY] Von: {abs_source}")
            log_callback(f"             Nach: {abs_target}")
            
            copy_files_via_robocopy(source_folder, cam_base_target_dir, file_name)
        
        media_pool.SetCurrentFolder(cam_bin)
        clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
        pancake_timeline = None
        
        if create_pancakes:
            media_pool.SetCurrentFolder(pancakes_bin)
            timeline_name = f"PC_FLAT_{camera_type}"
            existing_items = pancakes_bin.GetClipList()
            for item in existing_items:
                if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                    pancake_timeline = item
                    break
            
            if not pancake_timeline:
                log_callback(f"   -> Erstelle Kamera-Pancake: {timeline_name}")
                pancake_timeline = media_pool.CreateEmptyTimeline(timeline_name)
            else:
                log_callback(f"   -> Pancake-Timeline existiert bereits: {timeline_name} (wird erweitert)")
            
        media_pool.SetCurrentFolder(cam_bin)
        
        if clips_on_disk:
            new_clips = media_pool.ImportMedia(clips_on_disk)
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
                
                if create_pancakes and pancake_timeline and valid_clips_to_add:
                    try:
                        valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                    except Exception as sort_err:
                        log_callback(f"       [HINWEIS] Chronologische Sortierung nach TC fehlgeschlagen: {sort_err}")
                        
                    current_project.SetCurrentTimeline(pancake_timeline)
                    existing_timeline_items = pancake_timeline.GetItemListInTrack("video", 1)
                    existing_clip_names = set()
                    
                    if existing_timeline_items:
                        for item in existing_timeline_items:
                            mp_item = item.GetMediaPoolItem()
                            if mp_item:
                                existing_clip_names.add(mp_item.GetName())
                    
                    clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                    
                    if clips_to_append:
                        log_callback(f"   -> Füge {len(clips_to_append)} neue(n) Clip(s) der Timeline hinzu...")
                        media_pool.AppendToTimeline(clips_to_append)
                        apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
                    else:
                        log_callback("   -> Keine neuen Clips zum Hinzufügen (bereits in Timeline vorhanden).")


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors=None, base_drx_dir="", camera_mappings=None, base_target_dir="", base_proxy_dir=""):
    """Haupt-Einstiegspunkt für den Ingest-Prozess (Orchestrator)."""
    if camera_colors is None: camera_colors = {}
    if camera_mappings is None: camera_mappings = []

    # In ingest_worker.py -> run_ingest_process am Anfang einfügen:
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
        
        detected_sd_cards = get_connected_sd_cards()
        if not detected_sd_cards:
            log_callback("\n[HINWEIS] Keine SD-Karten gefunden.")
            return
            
        raw_queue = []
        log_callback("[SCHRITT 1/2] Kopiere Dateien von SD-Karten und importiere Medien...")
        
        for label, source_drive in detected_sd_cards.items():
            if not has_media_files(source_drive):
                continue
            
            process_single_sd_card(
                label, source_drive, format_mode, project_start_date,
                footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                base_drx_dir, camera_mappings
            )
        
        if raw_queue:
            render_and_link_proxies(raw_queue, use_h265, log_callback)
        
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