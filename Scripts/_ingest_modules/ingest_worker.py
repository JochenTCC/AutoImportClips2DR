#!/usr/bin/env python
import os
import time
from datetime import datetime

from .config import PROXY_ELIGIBLE_EXTENSIONS, WEEKDAYS_DE
from .utils import (
    get_connected_sd_cards, has_media_files, get_media_dates_from_card,
    extract_start_date_from_name, get_media_files_from_dir, get_media_files_flattened
)
from .drive_ops import create_physical_directories, copy_files_via_robocopy
from .resolve_media import (
    get_or_create_bin, create_resolve_bins, get_clip_color_by_label,  # KORREKTUR: Komma hinzugefügt
    tag_media_pool_items, apply_drx_grading_to_timeline,
    get_all_filepaths_from_bin, find_all_clips_in_bin
)
# KORREKTUR: Importiert nun die existierende Funktion aus proxy_generator.py
from .proxy_generator import render_and_link_proxies_ffmpeg


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings, trash_filepaths=None, use_h265=False):
    """Verarbeitet eine SD-Karte oder ein lokales Verzeichnis mit Weitergabe an die Proxy-Queue."""
    if trash_filepaths is None:
        trash_filepaths = set()

    log_callback(f"\n[INFO] Verarbeite Medienquelle/Label '{label}'...")
    clip_color = get_clip_color_by_label(label, camera_colors)
    
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
        if matched: break
    if camera_type == "UNKNOWN":
        for key in camera_colors.keys():
            if key.upper() in label_upper:
                camera_type = key.upper()
                break
        else:
            camera_type = "REC709"
            
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
        date_groups = get_media_dates_from_card(source_drive if source_drive else cam_base_target_dir)
        sorted_days = sorted(list(date_groups.keys()))
        
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
            
            for file_path in date_groups[day_str]:
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                if os.path.abspath(source_folder) != os.path.abspath(day_target_dir):
                    copy_files_via_robocopy(source_folder, day_target_dir, file_name)
            
            day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
            pancake_timeline = None
            
            if create_pancakes:
                day_pancake_bin = get_or_create_bin(media_pool, pancakes_bin, sub_folder_name)
                media_pool.SetCurrentFolder(day_pancake_bin)
                timeline_name = f"PC_{sub_folder_name}_{camera_type}"
                for item in day_pancake_bin.GetClipList():
                    if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                        pancake_timeline = item
                        break
            
            media_pool.SetCurrentFolder(day_bin)
            existing_bin_filenames = {c.GetName() for c in day_bin.GetClipList() if c}
            clips_on_disk = get_media_files_from_dir(day_target_dir)
            
            clips_to_import = [
                path for path in clips_on_disk 
                if os.path.basename(path) not in existing_bin_filenames and os.path.abspath(path) not in trash_filepaths
            ]
            
            if not clips_to_import: continue
                
            new_clips = media_pool.ImportMedia(clips_to_import)
            if new_clips:
                clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                valid_clips_to_add = []
                
                for clip in clip_list:
                    if not clip: continue
                    try: clip.SetClipProperty("Clip Color", clip_color)
                    except Exception: pass
                    
                    clip_name = clip.GetName()
                    if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                        expected_proxy_path = os.path.join(day_proxy_dir, clip_name)
                        os.makedirs(day_proxy_dir, exist_ok=True)
                        
                        if os.path.exists(expected_proxy_path):
                            log_callback(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
                            try: clip.LinkProxyMedia(expected_proxy_path)
                            except Exception: pass
                        else:
                            # KORREKTUR: Befüllt die Queue passend für proxy_generator.py mit (clip, source_path, proxy_dir)
                            clip_path_on_disk = os.path.join(day_target_dir, clip_name)
                            raw_queue.append((clip, clip_path_on_disk, day_proxy_dir))
                    
                    valid_clips_to_add.append(clip)
                
                tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
                
                if create_pancakes and valid_clips_to_add:
                    try: valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                    except Exception: pass
                    
                    existing_clip_names = set()
                    if pancake_timeline is not None:
                        try:
                            raw_items = pancake_timeline.GetItemListInTrack("video", 1)
                            for item in (raw_items if raw_items else []):
                                mp_item = item.GetMediaPoolItem()
                                if mp_item: existing_clip_names.add(mp_item.GetName())
                        except Exception: pass
                    
                    clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                    if not clips_to_append: continue
                    
                    if not pancake_timeline:
                        media_pool.SetCurrentFolder(day_pancake_bin)
                        pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
                        remaining_clips = clips_to_append[1:]
                    else:
                        remaining_clips = clips_to_append
                    
                    if pancake_timeline is not None and remaining_clips:
                        current_project.SetCurrentTimeline(pancake_timeline)
                        media_pool.AppendToTimeline(remaining_clips)
                        apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
    else:
        # Flat-Mode
        if source_drive:
            for file_path in get_media_files_flattened(source_drive):
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                copy_files_via_robocopy(source_folder, cam_base_target_dir, file_name)
        
        media_pool.SetCurrentFolder(cam_bin)
        pancake_timeline = None
        timeline_name = f"PC_FLAT_{camera_type}"
        
        if create_pancakes:
            media_pool.SetCurrentFolder(pancakes_bin)
            for item in pancakes_bin.GetClipList():
                if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                    pancake_timeline = item
                    break
            
        media_pool.SetCurrentFolder(cam_bin)
        existing_bin_filenames = {c.GetName() for c in cam_bin.GetClipList() if c}
        clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
        
        clips_to_import = [
            path for path in clips_on_disk 
            if os.path.basename(path) not in existing_bin_filenames and os.path.abspath(path) not in trash_filepaths
        ]
        
        if not clips_to_import: return  
            
        new_clips = media_pool.ImportMedia(clips_to_import)
        if new_clips:
            clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
            valid_clips_to_add = []
            
            for clip in clip_list:
                if not clip: continue
                try: clip.SetClipProperty("Clip Color", clip_color)
                except Exception: pass
                    
                clip_name = clip.GetName()
                if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                    expected_proxy_path = os.path.join(cam_base_proxy_dir, clip_name)
                    os.makedirs(cam_base_proxy_dir, exist_ok=True)
                    
                    if os.path.exists(expected_proxy_path):
                        log_callback(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
                        try: clip.LinkProxyMedia(expected_proxy_path)
                        except Exception: pass
                    else:
                        # KORREKTUR: Befüllt die Queue passend für proxy_generator.py mit (clip, source_path, proxy_dir)
                        clip_path_on_disk = os.path.join(cam_base_target_dir, clip_name)
                        raw_queue.append((clip, clip_path_on_disk, cam_base_proxy_dir))
                    
                valid_clips_to_add.append(clip)
            
            tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
            
            if create_pancakes and valid_clips_to_add:
                try: valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                except Exception: pass
                    
                existing_clip_names = set()
                if pancake_timeline is not None:
                    try:
                        raw_items = pancake_timeline.GetItemListInTrack("video", 1)
                        for item in (raw_items if raw_items else []):
                            mp_item = item.GetMediaPoolItem()
                            if mp_item: existing_clip_names.add(mp_item.GetName())
                    except Exception: pass
                
                clips_to_append = [c for c in valid_clips_to_add if c.GetName() not in existing_clip_names]
                if not clips_to_append: return
                
                if not pancake_timeline:
                    media_pool.SetCurrentFolder(pancakes_bin)
                    pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
                    remaining_clips = clips_to_append[1:]
                else:
                    remaining_clips = clips_to_append
                
                if pancake_timeline is not None and remaining_clips:
                    current_project.SetCurrentTimeline(pancake_timeline)
                    media_pool.AppendToTimeline(remaining_clips)
                    apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)

def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, 
                       camera_colors=None, base_drx_dir="", camera_mappings=None, 
                       base_target_dir="", base_proxy_dir="", progress_callback=None):
    """Haupt-Einstiegspunkt für den Ingest-Prozess (Orchestrator) mit Multi-Threading."""
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
                    from .utils import get_media_files_from_dir
                    if get_media_files_from_dir(footage_dir):
                        detected_sd_cards["FOOTAGE_ROOT"] = None
        
        if not detected_sd_cards:
            log_callback("[FEHLER] Weder SD-Karten noch lokale Medien im Zielverzeichnis gefunden.")
            return
            
        # --- PIEPLINE START ---
        global_start_time = time.perf_counter()
        raw_queue = []
        log_callback("[SCHRITT 1/2] Starte Ingest-Pipeline (Kopieren + Importieren)...")
        
        for label, source_drive in detected_sd_cards.items():
            if source_drive and not has_media_files(source_drive):
                continue
            
            process_single_sd_card(
                label, source_drive, format_mode, project_start_date,
                footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                base_drx_dir, camera_mappings, trash_filepaths=trash_filepaths,
                use_h265=use_h265
            )
        
        # --- PROXY GENERIERUNG (SEQUENTIELL) ---
        if raw_queue:
            # KORREKTUR: Nutzt nun die in proxy_generator.py bereitgestellte Render-Funktion
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