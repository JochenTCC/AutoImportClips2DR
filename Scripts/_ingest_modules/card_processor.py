#!/usr/bin/env python
import os
from datetime import datetime

from .config import PROXY_ELIGIBLE_EXTENSIONS, WEEKDAYS_DE
from .utils import get_media_dates_from_card, get_media_files_from_dir, get_media_files_flattened
from .drive_ops import copy_files_via_robocopy
from .resolve_media import (
    get_or_create_bin, get_clip_color_by_label, tag_media_pool_items, apply_drx_grading_to_timeline
)

def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings):
    """Verarbeitet eine SD-Karte oder ein lokales Verzeichnis mit optionaler Timeline-Generierung."""
    log_callback(f"\n[INFO] Verarbeite Medienquelle/Label '{label}'...")
    
    clip_color = get_clip_color_by_label(label, camera_colors)
    log_callback(f"   -> Zugewiesene Resolve-Clipfarbe: {clip_color}")
    
    # Kamera-Typ ermitteln
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
            
    # Pfade und Bins vorbereiten
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
    
    # --- FALL A: Strukturierter Import (Datum / Wochentag / Counter) ---
    if format_mode != "NONE":
        date_groups = get_media_dates_from_card(source_drive if source_drive else cam_base_target_dir)
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
            
            # Dateien kopieren (falls von externer Quelle)
            if source_drive:
                for file_path in date_groups[day_str]:
                    file_name = os.path.basename(file_path)
                    source_folder = os.path.dirname(file_path)
                    if os.path.abspath(source_folder) != os.path.abspath(day_target_dir):
                        copy_files_via_robocopy(source_folder, day_target_dir, file_name)
            
            # In Resolve importieren und Pancakes bauen
            day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
            _import_and_build_pancake(
                media_pool, current_project, day_bin, pancakes_bin, day_target_dir, day_proxy_dir,
                sub_folder_name, camera_type, clip_color, group_keyword, create_pancakes, 
                f"PC_{sub_folder_name}_{camera_type}", raw_queue, base_drx_dir, camera_mappings, log_callback
            )

    # --- FALL B: Flacher Import (Alles in ein Verzeichnis) ---
    else:
        if source_drive:
            log_callback(f"   -> Kopiere Clips flach in Hauptordner...")
            for file_path in get_media_files_flattened(source_drive):
                file_name = os.path.basename(file_path)
                source_folder = os.path.dirname(file_path)
                copy_files_via_robocopy(source_folder, cam_base_target_dir, file_name)
        
        _import_and_build_pancake(
            media_pool, current_project, cam_bin, pancakes_bin, cam_base_target_dir, cam_base_proxy_dir,
            "Flat", camera_type, clip_color, group_keyword, create_pancakes,
            f"PC_FLAT_{camera_type}", raw_queue, base_drx_dir, camera_mappings, log_callback
        )


def _import_and_build_pancake(media_pool, current_project, target_bin, pancakes_bin, target_dir, proxy_dir,
                              log_label, camera_type, clip_color, group_keyword, create_pancakes,
                              timeline_name, raw_queue, base_drx_dir, camera_mappings, log_callback):
    """Interne Hilfsfunktion, um Code-Duplikate beim Import & Pancake-Schnitt zu vermeiden."""
    media_pool.SetCurrentFolder(target_bin)
    existing_filenames = {c.GetName() for c in target_bin.GetClipList() if c}
    
    clips_on_disk = get_media_files_from_dir(target_dir)
    clips_to_import = [p for p in clips_on_disk if os.path.basename(p) not in existing_filenames]
    
    if not clips_to_import:
        log_callback(f"   -> [INFO] Keine neuen Medien zum Importieren für {log_label} gefunden.")
        return
        
    new_clips = media_pool.ImportMedia(clips_to_import)
    if not new_clips:
        return
        
    clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
    valid_clips_to_add = []
    
    for clip in clip_list:
        if not clip: continue
        try: clip.SetClipProperty("Clip Color", clip_color)
        except Exception: pass
        
        if clip.GetName().lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
            raw_queue.append((clip, os.path.join(target_dir, clip.GetName()), proxy_dir))
        valid_clips_to_add.append(clip)
        
    tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
    
    if create_pancakes and valid_clips_to_add:
        _build_or_extend_pancake(media_pool, current_project, pancakes_bin, timeline_name, 
                                 valid_clips_to_add, camera_type, base_drx_dir, camera_mappings, log_callback)


def _build_or_extend_pancake(media_pool, current_project, pancakes_bin, timeline_name, 
                             clips_to_add, camera_type, base_drx_dir, camera_mappings, log_callback):
    """Erstellt oder erweitert eine spezifische Pancake-Timeline im angegebenen Bin."""
    media_pool.SetCurrentFolder(pancakes_bin)
    pancake_timeline = None
    
    for item in pancakes_bin.GetClipList():
        if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
            pancake_timeline = item
            break
            
    try: clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
    except Exception: pass
    
    existing_clip_names = set()
    if pancake_timeline:
        try:
            raw_items = pancake_timeline.GetItemListInTrack("video", 1)
            for item in (raw_items if raw_items else []):
                mp_item = item.GetMediaPoolItem()
                if mp_item: existing_clip_names.add(mp_item.GetName())
        except Exception: pass
        
    clips_to_append = [c for c in clips_to_add if c.GetName() not in existing_clip_names]
    if not clips_to_append:
        log_callback(f"   -> [STOP] Alle Clips bereits in Pancake '{timeline_name}' enthalten.")
        return
        
    if not pancake_timeline:
        log_callback(f"   -> Erstelle Kamera-Pancake: {timeline_name}")
        pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
        remaining = clips_to_append[1:]
    else:
        log_callback(f"   -> Pancake existiert bereits: {timeline_name} (wird erweitert)")
        remaining = clips_to_append
        
    if pancake_timeline and remaining:
        current_project.SetCurrentTimeline(pancake_timeline)
        media_pool.AppendToTimeline(remaining)
        apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)