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
    get_or_create_bin, create_resolve_bins, get_clip_color_by_label,
    tag_media_pool_items, apply_drx_grading_to_timeline
)
from .proxy_generator import render_and_link_proxies


def process_single_sd_card(label, source_drive, format_mode, project_start_date, 
                           footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                           pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                           base_drx_dir, camera_mappings):
    """Verarbeitet eine einzelne SD-Karte synchron im Hauptthread."""
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
        if not date_groups:
            log_callback(f"   -> Keine relevanten Mediendateien auf Karte '{label}' gefunden.")
            return
            
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
            os.makedirs(day_proxy_dir, exist_ok=True)
            
            log_callback(f"   -> Kopiere Clips nach: Footage/{label}/{sub_folder_name}")
            for file_path in date_groups[day_str]:
                file_name = os.path.basename(file_path)
                copy_files_via_robocopy(os.path.dirname(file_path), day_target_dir, file_name)
            
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
            
            media_pool.SetCurrentFolder(day_bin)
            
            raw_clips = get_media_files_from_dir(day_target_dir)
            clips_on_disk = [
                os.path.normpath(p).replace("\\", "/") for p in raw_clips 
                if os.path.exists(p) and os.path.getsize(p) > 0 and not os.path.basename(p).startswith("._")
            ]
                        
            if clips_on_disk:
                # 1. Sicherstellen, dass das Dateisystem nach Robocopy Zeit hatte, die Dateien freizugeben
                time.sleep(0.5) 
                
                # 2. Testweise native Windows-Backslashes beibehalten (Resolve-API-Sicherheitsnetz)
                # Entferne testweise das .replace("\\", "/") falls Resolve den Import verweigert.
                
                log_callback(f"   -> Importiere {len(clips_on_disk)} Clips in Resolve...")
                
                # Sicherheitsprüfung: Existiert das Ziel-Bin wirklich noch im aktuellen Projektkontext?
                if day_bin:
                    media_pool.SetCurrentFolder(day_bin)
                else:
                    log_callback("   [FEHLER] Ziel-Bin (day_bin) konnte nicht verifiziert werden.")
                    return

                # 3. Import-Aufruf mit Fehlerbehandlung absichern
                try:
                    new_clips = media_pool.ImportMediaFiles(clips_on_disk)
                except Exception as api_err:
                    log_callback(f"   [API FEHLER] Kritischer Fehler beim Import-Aufruf: {api_err}")
                    new_clips = None
                
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
                            clip_path_on_disk = os.path.normpath(os.path.join(day_target_dir, clip_name)).replace("\\", "/")
                            raw_queue.append((clip, clip_path_on_disk, os.path.normpath(day_proxy_dir).replace("\\", "/")))
                        
                        valid_clips_to_add.append(clip)
                    
                    tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)
                    
                    if create_pancakes and pancake_timeline and valid_clips_to_add:
                        try:
                            valid_clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
                        except Exception as sort_err:
                            log_callback(f"       [HINWEIS] Sortierung nach TC fehlgeschlagen: {sort_err}")
                            
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
                            log_callback(f"   -> Füge {len(clips_to_append)} Clips der Timeline hinzu...")
                            media_pool.AppendToTimeline(clips_to_append)
                            apply_drx_grading_to_timeline(pancake_timeline, base_drx_dir, camera_type, camera_mappings, log_callback)
    else:
        log_callback(f"   -> Kopiere Clips flach nach: Footage/{label}")
        flattened_files = get_media_files_flattened(source_drive)
        
        for file_path in flattened_files:
            file_name = os.path.basename(file_path)
            copy_files_via_robocopy(os.path.dirname(file_path), cam_base_target_dir, file_name)
        
        media_pool.SetCurrentFolder(cam_bin)
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
            
        media_pool.SetCurrentFolder(cam_bin)
        
        raw_clips = get_media_files_from_dir(cam_base_target_dir)
        clips_on_disk = [
            os.path.normpath(p).replace("\\", "/") for p in raw_clips 
            if os.path.exists(p) and os.path.getsize(p) > 0 and not os.path.basename(p).startswith("._")
        ]
        
        if clips_on_disk:
            log_callback(f"   -> Importiere {len(clips_on_disk)} Clips (flach) in Resolve...")
            new_clips = media_pool.ImportMediaFiles(clips_on_disk)
                
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
                        clip_path_on_disk = os.path.normpath(os.path.join(cam_base_target_dir, clip_name)).replace("\\", "/")
                        raw_queue.append((clip, clip_path_on_disk, os.path.normpath(cam_base_proxy_dir).replace("\\", "/")))
                        
                    valid_clips_to_add.append(clip)
                
                tag_media_pool_items(valid_clips_to_add, group_keyword, log_callback)


def run_ingest_process(format_mode, use_h265, log_callback, create_pancakes, camera_colors=None, base_drx_dir="", camera_mappings=None, base_target_dir="", base_proxy_dir=""):
    """Haupt-Einstiegspunkt für den Ingest-Prozess (Läuft synchron im Hauptthread)."""
    if camera_colors is None: camera_colors = {}
    if camera_mappings is None: camera_mappings = []
       
    try:
        import DaVinciResolveScript as dvr_script
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            log_callback("[FEHLER] DaVinci Resolve API konnte nicht initialisiert werden.")
            return
            
        project_manager = resolve.GetProjectManager()
        current_project = project_manager.GetCurrentProject()
        if not current_project:
            log_callback("[FEHLER] Kein geöffnetes Projekt in Resolve gefunden!")
            return
        
        project_name = current_project.GetName()
        project_start_date = extract_start_date_from_name(project_name)
        if not project_start_date:
            project_start_date = datetime.now()
        
        if not base_target_dir or not base_proxy_dir:
            log_callback("[FEHLER] Ziel- oder Proxy-Pfade aus der GUI-Konfiguration sind leer!")
            return
            
        log_callback("[GUI] Schalte Resolve auf die Media-Page um...")
        try:
            resolve.OpenPage("media")
        except Exception as p_err:
            log_callback(f"[HINWEIS] Automatischer Wechsel zur Media-Page fehlgeschlagen: {p_err}")
            
        project_dir, footage_dir, project_proxy_dir = create_physical_directories(project_name, base_target_dir, base_proxy_dir)
        os.makedirs(project_proxy_dir, exist_ok=True)
        
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        footage_bin, pancakes_bin = create_resolve_bins(media_pool, root_folder)
        
        def ScanBinRecursively(folder):
            clips = folder.GetClipList()
            for clip in clips:
                if clip.GetClipProperty("Type") == "Video":
                    src_path = clip.GetClipProperty("File Path")
                    if src_path and os.path.exists(src_path) and src_path.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                        has_proxy = clip.GetClipProperty("Proxy")
                        if not has_proxy or has_proxy.lower() == "none" or has_proxy == "":
                            try:
                                rel_path = os.path.relpath(src_path, footage_dir)
                                clip_proxy_dir = os.path.dirname(os.path.join(project_proxy_dir, rel_path))
                            except ValueError:
                                clip_proxy_dir = os.path.join(project_proxy_dir, "External_Media")
                            
                            raw_queue.append((clip, os.path.normpath(src_path).replace("\\", "/"), os.path.normpath(clip_proxy_dir).replace("\\", "/")))
            
            sub_folders = folder.GetSubFolderList()
            for sub in sub_folders:
                ScanBinRecursively(sub)

        detected_sd_cards = get_connected_sd_cards()
        raw_queue = []
        
        if detected_sd_cards:
            log_callback("[SCHRITT 1/2] Starte Datei-Kopier- und Importvorgang...")
            for label, source_drive in detected_sd_cards.items():
                if not has_media_files(source_drive):
                    continue
                
                process_single_sd_card(
                    label, source_drive, format_mode, project_start_date,
                    footage_dir, project_proxy_dir, current_project, media_pool, footage_bin,
                    pancakes_bin, create_pancakes, log_callback, raw_queue, camera_colors,
                    base_drx_dir, camera_mappings
                )
        else:
            log_callback("\n[HINWEIS] Keine SD-Karten angeschlossen. Scanne Medienpool nach unvollständigen Proxies...")
            media_pool.SetCurrentFolder(footage_bin)
            ScanBinRecursively(footage_bin)
        
        if raw_queue:
            render_and_link_proxies(raw_queue, use_h265, log_callback)
            log_callback("\n[FERTIG] Synchronisation und Proxy-Verknüpfungen erfolgreich beendet!")
            
            try:
                resolve.OpenPage("edit")
            except Exception:
                pass
        else:
            log_callback("\n[FERTIG] Keine neuen Daten oder ausstehenden Proxies gefunden.")

    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")