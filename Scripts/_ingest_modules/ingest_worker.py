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

def run_ingest_process(format_mode, use_h265, log_callback):
    """Führt den gesamten Kopiervorgang und das Rendering flach oder strukturiert aus."""
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
        
        project_dir = os.path.join(BASE_TARGET_DIR, project_name)
        project_proxy_dir = os.path.join(BASE_PROXY_DIR, project_name)
        os.makedirs(project_dir, exist_ok=True)
        footage_dir = os.path.join(project_dir, "Footage")
        
        detected_sd_cards = get_connected_sd_cards()
        if not detected_sd_cards:
            log_callback("\n[HINWEIS] Keine SD-Karten gefunden.")
            return
            
        media_pool = current_project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        
        raw_queue = []
        log_callback("[SCHRITT 1/2] Kopiere Dateien von SD-Karten und importiere Medien...")
        
        for label, source_drive in detected_sd_cards.items():
            if not has_media_files(source_drive):
                continue
                
            log_callback(f"\n[GEFUNDEN] Verarbeite Karte '{label}'...")
            
            cam_base_target_dir = os.path.join(footage_dir, label)
            cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
            os.makedirs(cam_base_target_dir, exist_ok=True)
            
            footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
            cam_bin = get_or_create_bin(media_pool, footage_bin, label)
            
            if format_mode != "NONE":
                date_groups = get_media_dates_from_card(source_drive)
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
                    
                    log_callback(f"   -> Kopiere Clips nach: Footage/{label}/{sub_folder_name}")
                    for file_path in date_groups[day_str]:
                        file_name = os.path.basename(file_path)
                        cmd = ["robocopy", os.path.dirname(file_path), day_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    day_bin = get_or_create_bin(media_pool, cam_bin, sub_folder_name)
                    media_pool.SetCurrentFolder(day_bin)
                    
                    clips_on_disk = get_media_files_from_dir(day_target_dir)
                    if clips_on_disk:
                        new_clips = media_pool.ImportMedia(clips_on_disk)
                        if new_clips:
                            clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                            for clip in clip_list:
                                if not clip: continue
                                clip_name = clip.GetName()
                                if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                    clip_path_on_disk = os.path.join(day_target_dir, clip_name)
                                    raw_queue.append((clip, clip_path_on_disk, day_proxy_dir))
            else:
                log_callback(f"   -> Kopiere Clips flach nach: Footage/{label}")
                flattened_files = get_media_files_flattened(source_drive)
                
                for file_path in flattened_files:
                    file_name = os.path.basename(file_path)
                    cmd = ["robocopy", os.path.dirname(file_path), cam_base_target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
                    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                media_pool.SetCurrentFolder(cam_bin)
                clips_on_disk = get_media_files_from_dir(cam_base_target_dir)
                if clips_on_disk:
                    new_clips = media_pool.ImportMedia(clips_on_disk)
                    if new_clips:
                        clip_list = new_clips if isinstance(new_clips, list) else [new_clips]
                        for clip in clip_list:
                            if not clip: continue
                            clip_name = clip.GetName()
                            if clip_name.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                                clip_path_on_disk = os.path.join(cam_base_target_dir, clip_name)
                                raw_queue.append((clip, clip_path_on_disk, cam_base_proxy_dir))
        
        # --- SCHRITT 2: RENDERING ---
        if raw_queue:
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
            
            if render_jobs:
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
                        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, startupinfo=startupinfo)
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
            else:
                log_callback("\n[HINWEIS] Keine neuen Videos zum Rendern in der Queue.")
        
        log_callback("\n[FERTIG] Synchronisation, optimiertes Batch-Rendering und Proxy-Verknüpfungen beendet!")
    except Exception as e:
        log_callback(f"\n[UNERWARTETER FEHLER] {e}")