#!/usr/bin/env python
import os
import subprocess
import sys
from datetime import datetime

# Relative Importe innerhalb des Modulordners
from .config import BASE_TARGET_DIR, BASE_PROXY_DIR, PROXY_ELIGIBLE_EXTENSIONS, WEEKDAYS_DE
from .utils import (
    get_connected_sd_cards, has_media_files, get_media_dates_from_card,
    extract_start_date_from_name, get_media_files_from_dir, get_media_files_flattened
)


def get_or_create_bin(media_pool, parent_folder, name):
    """Sucht nach einem Bin. Wenn es existiert, wird es zurückgegeben, sonst erstellt."""
    sub_folders = parent_folder.GetSubFolderList()
    for folder in sub_folders:
        if folder.GetName() == name:
            return folder
    return media_pool.AddSubFolder(parent_folder, name)


def create_physical_directories(project_name):
    """Erstellt alle notwendigen Verzeichnisse auf der Festplatte."""
    project_dir = os.path.join(BASE_TARGET_DIR, project_name)
    project_proxy_dir = os.path.join(BASE_PROXY_DIR, project_name)
    
    # Haupt- und Footage-Ordner
    footage_dir = os.path.join(project_dir, "Footage")
    os.makedirs(footage_dir, exist_ok=True)
    
    # Zusätzliche Asset-Ordner auf gleicher Ebene
    os.makedirs(os.path.join(project_dir, "Music"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "Images"), exist_ok=True)
    
    return project_dir, footage_dir, project_proxy_dir


def create_resolve_bins(media_pool, root_folder):
    """Erstellt die Basis-Bin-Struktur im DaVinci Resolve Media Pool."""
    footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
    music_bin = get_or_create_bin(media_pool, root_folder, "Music")
    images_bin = get_or_create_bin(media_pool, root_folder, "Images")
    pancakes_bin = get_or_create_bin(media_pool, root_folder, "Pancakes")
    timelines_bin = get_or_create_bin(media_pool, root_folder, "Timelines")
    
    # Unter-Bins innerhalb von "Timelines" anlegen
    get_or_create_bin(media_pool, timelines_bin, "Landscape")
    get_or_create_bin(media_pool, timelines_bin, "Portrait")
    
    return footage_bin, pancakes_bin


def get_clip_color_by_label(label, camera_colors):
    """Ermittelt die DaVinci Resolve Clip-Farbe dynamisch aus der config.json."""
    label_upper = label.upper()
    
    for key, color in camera_colors.items():
        key_upper = key.upper()
        parts = key_upper.split('_')
        for part in parts:
            if len(part) > 2 and part in label_upper: 
                return color.lower()
                
    for key, color in camera_colors.items():
        if key.upper() in label_upper:
            return color.lower()
            
    return "marine"


def tag_media_pool_items(clips, group_keyword, log_callback):
    """
    Weist importierten Media-Pool-Items direkt das Kamera-Metadaten-Tag zu.
    Garantiert die Funktion der Smart Filter, auch wenn keine Pancake-Timelines genutzt werden.
    """
    try:
        updated_count = 0
        for clip in clips:
            if clip:
                success = clip.SetMetadata("Camera Type", group_keyword)
                if success:
                    updated_count += 1
        if updated_count > 0:
            log_callback(f"       [OK] {updated_count} Clip(s) mit Metadaten-Tag '{group_keyword}' versehen.")
    except Exception as e:
        log_callback(f"       [HINWEIS] Fehler bei der Metadaten-Direktzuweisung: {e}")


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors):
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
            camera_type = label
            
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
            
            log_callback(f"   -> Kopiere Clips nach: Footage/{label}/{sub_folder_name}")
            for file_path in date_groups[day_str]:
                file_name = os.path.basename(file_path)
                cmd = ["robocopy", os.path.dirname(file_path), day_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
            pancake_timeline = None
            
            # TIMELINE-LOGIK: Nur ausführen, wenn in der GUI ausgewählt
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
                    
                    # Metadaten-Tagging direkt im Media-Pool durchführen
                    tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
                    
                    # Clips zur Timeline hinzufügen, falls aktiviert
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
                        else:
                            log_callback("   -> Keine neuen Clips zum Hinzufügen (bereits in Timeline vorhanden).")
    else:
        # Im flachen Modus (format_mode == "NONE")
        log_callback(f"   -> Kopiere Clips flach nach: Footage/{label}")
        flattened_files = get_media_files_flattened(source_drive)
        
        for file_path in flattened_files:
            file_name = os.path.basename(file_path)
            cmd = ["robocopy", os.path.dirname(file_path), cam_base_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
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
                    else:
                        log_callback("   -> Keine neuen Clips zum Hinzufügen (bereits in Timeline vorhanden).")


def render_and_link_proxies(raw_queue, use_h265, log_callback):
    """Verarbeitet die Proxy-Queue und führt das FFmpeg-Rendering durch."""
    render_jobs = []
    for clip, source_path, proxy_dir in raw_queue:
        clip_name = os.path.basename(source_path)
        expected_proxy_path = os.path.join(proxy_dir, clip_name)
        os.makedirs(proxy_dir, exist_ok=True)
        
        if os.path.exists(expected_proxy_path):
            log_callback(f"   [BEREITS VORHANDEN] Proxy existiert: {clip_name}")
            try: clip.LinkProxyMedia(expected_proxy_path)
            except Exception: pass
        else:
            render_jobs.append((clip, source_path, expected_proxy_path))
    
    if not render_jobs:
        log_callback("\n[HINWEIS] Keine neuen Videos zum Rendern in der Queue.")
        return
        
    total_jobs = len(render_jobs)
    log_callback(f"\n[SCHRITT 2/2] Starte Proxy-Generierung für {total_jobs} neue Proxies...")
    
    if use_h265:
        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
    else:
        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
    
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    for idx, (clip, source_path, expected_proxy_path) in enumerate(render_jobs, start=1):
        clip_name = os.path.basename(source_path)
        codec_label = "H.265" if use_h265 else "H.264"
        log_callback(f"   [{idx}/{total_jobs}] Rendere {codec_label}-Proxy: {clip_name} ...")
        
        filter_str = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-i", source_path
        ] + video_codec_args + [
            "-vf", filter_str,
            "-c:a", "copy",
            expected_proxy_path
        ]
        
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, startupinfo=startupinfo)
            if os.path.exists(expected_proxy_path):
                success = clip.LinkProxyMedia(expected_proxy_path)
                if success:
                    log_callback(f"       -> [OK] Proxy erfolgreich verknüpft.")
        except subprocess.CalledProcessError as e:
            log_callback(f"       -> [FEHLER] FFmpeg-Rendering fehlgeschlagen für {clip_name}")
            if e.stderr:
                error_lines = e.stderr.strip().split('\n')[-3:]
                for err_line in error_lines:
                    log_callback(f"          | {err_line}")
        except Exception as e:
            log_callback(f"       -> [API FEHLER] Verknüpfung fehlgeschlagen: {e}")


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors=None):
    """Haupt-Einstiegspunkt für den Ingest-Prozess."""
    if camera_colors is None:
        camera_colors = {}
        
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
        
        project_dir, footage_dir, project_proxy_dir = create_physical_directories(project_name)
        
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
                pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors
            )
        
        if raw_queue:
            render_and_link_proxies(raw_queue, use_h265, log_callback)
        
        log_callback("\n[FERTIG] Synchronisation, Metadaten-Tagging und Proxy-Verknüpfungen beendet!")
    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")