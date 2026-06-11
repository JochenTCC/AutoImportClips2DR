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
                           pancakes_bin, create_pancakes, log_callback, raw_queue, config,
                           trash_filepaths=None, use_h265=False):
    """Verarbeitet eine SD-Karte oder ein lokales Verzeichnis mit Weitergabe an die Proxy-Queue."""
    if trash_filepaths is None:
        trash_filepaths = set()

    # Lokale Extraktion der benötigten Parameter aus der zentralen Config
    camera_colors = config.get("camera_colors", {})
    camera_mappings = config.get("camera_mappings", [])
    base_drx_dir = config.get("BASE_DRX_DIR", "")

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


def _import_and_build_pancake(media_pool, current_project, target_bin, pancakes_bin, target_dir, proxy_dir,
                              log_label, camera_type, clip_color, group_keyword, create_pancakes,
                              timeline_name, raw_queue, base_drx_dir, camera_mappings, log_callback,
                              proxy_task_queue, use_h265):
    """Interne Hilfsfunktion, um Medien zu importieren und an den Hintergrund-Thread zu übergeben."""
    media_pool.SetCurrentFolder(target_bin)
    existing_filenames = {c.GetName() for c in target_bin.GetClipList() if c}
    
    clips_on_disk = get_media_files_from_dir(target_dir)
    clips_to_import = [p for p in clips_on_disk if os.path.basename(p) not in existing_filenames]
    
    if not clips_to_import: return
        
    new_clips = media_pool.ImportMedia(clips_to_import)
    if not new_clips: return
        
    clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
    valid_clips_to_add = []
    codec_label = "H.265" if use_h265 else "H.264"
    
    for clip in clip_list:
        if not clip: continue
        try: clip.SetClipProperty("Clip Color", clip_color)
        except Exception: pass
        
        clip_name = clip.GetName()
        if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
            expected_proxy_path = os.path.join(proxy_dir, clip_name)
            os.makedirs(proxy_dir, exist_ok=True)
            
            if os.path.exists(expected_proxy_path):
                log_callback(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
                try: clip.LinkProxyMedia(expected_proxy_path)
                except Exception: pass
            else:
                raw_queue.append((clip, expected_proxy_path))
                if proxy_task_queue is not None:
                    clip_path_on_disk = os.path.join(target_dir, clip_name)
                    proxy_task_queue.put((clip_path_on_disk, expected_proxy_path, codec_label))
                    
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
    if not clips_to_append: return
        
    if not pancake_timeline:
        pancake_timeline = media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
        remaining = clips_to_append[1:]
    else:
        remaining = clips_to_append
        
    if pancake_timeline and remaining:
        current_project.SetCurrentTimeline(pancake_timeline)
        media_pool.AppendToTimeline(remaining)
        apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)