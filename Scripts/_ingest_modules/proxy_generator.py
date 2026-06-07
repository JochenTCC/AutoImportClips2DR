#!/usr/bin/env python
import os
import sys
import subprocess
import time
import threading
import queue

def ffmpeg_proxy_worker(task_queue, video_codec_args, startupinfo, log_callback):
    """
    Worker-Thread, der kontinuierlich Rendering-Tasks aus der Queue abarbeitet,
    während der Haupt-Thread weiter kopiert und in Resolve importiert.
    """
    while True:
        task = task_queue.get()
        if task is None:  # Sentinel-Signal zum Beenden des Threads
            task_queue.task_done()
            break
        
        source_path, expected_proxy_path, codec_label = task
        clip_name = os.path.basename(source_path)
        
        log_callback(f"   [BACKGROUND PROXY] Starte FFmpeg-Rendering ({codec_label}): {clip_name} ...")
        
        filter_str = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-i", source_path,
            "-map", "0:v",
            "-map", "0:a"
        ] + video_codec_args + [
            "-vf", filter_str,
            "-c:a", "aac",
            expected_proxy_path
        ]
        
        try:
            # Render-Vorgang ausführen
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, startupinfo=startupinfo)
            log_callback(f"   [BACKGROUND PROXY] -> [OK] Rendering abgeschlossen: {clip_name}")
        except subprocess.CalledProcessError as e:
            log_callback(f"   [BACKGROUND PROXY] -> [FEHLER] FFmpeg-Rendering fehlgeschlagen für {clip_name}")
            if e.stderr:
                error_lines = e.stderr.strip().split('\n')[-3:]
                for err_line in error_lines:
                    log_callback(f"          | {err_line}")
        except Exception as e:
            log_callback(f"   [BACKGROUND PROXY] -> [FEHLER] Unerwarteter Systemfehler: {e}")

        task_queue.task_done()


def init_background_proxy_engine(use_h264_or_h265, log_callback):
    """Initialisiert die Queue und startet den parallelen FFmpeg-Background-Thread."""
    task_queue = queue.Queue()
    
    if use_h264_or_h265:  # True für H.265
        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
        codec_label = "H.265"
    else:
        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
        codec_label = "H.264"
        
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        
    worker_thread = threading.Thread(
        target=ffmpeg_proxy_worker, 
        args=(task_queue, video_codec_args, startupinfo, log_callback),
        daemon=True
    )
    worker_thread.start()
    
    log_callback(f"[PROXY ENGINE] Parallel-Pipeline für {codec_label} (NVENC CUDA) erfolgreich initialisiert.")
    return task_queue, worker_thread


def link_finished_proxies(raw_queue, log_callback):
    """Verknüpft alle generierten Proxies sicher auf dem Haupt-Thread mit der Resolve-Datenbank."""
    log_callback("\n[SCHRITT 2/2] Verknüpfung der fertiggestellten Proxies mit Resolve Media Pool...")
    linked_count = 0
    
    for clip, expected_proxy_path in raw_queue:
        if os.path.exists(expected_proxy_path):
            try:
                success = clip.LinkProxyMedia(expected_proxy_path)
                if success:
                    linked_count += 1
            except Exception as e:
                log_callback(f"       [API FEHLER] Verbindung fehlgeschlagen für {os.path.basename(expected_proxy_path)}: {e}")
        else:
            log_callback(f"       [WARNUNG] Proxy-Datei physisch nicht auffindbar: {os.path.basename(expected_proxy_path)}")
            
    log_callback(f"[INFO] {linked_count} von {len(raw_queue)} Proxies erfolgreich in Resolve verknüpft.")


def render_and_link_proxies_DR_Engine(raw_queue, use_h264_or_h265, log_callback, current_project=None):
    """
    Nativer Fallback für Resolve Render-Engine. 
    HINWEIS: Läuft sequentiell, da die Resolve-API bei interner Generierung blockiert.
    """
    if not current_project:
        try:
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if resolve:
                current_project = resolve.GetProjectManager().GetCurrentProject()
        except Exception: pass

    if not current_project:
        log_callback("[FEHLER] Resolve-Projektkontext konnte nicht ermittelt werden.")
        return

    clips_to_render = []
    for clip, expected_proxy_path in raw_queue:
        proxy_property = clip.GetClipProperty("Proxy")
        if proxy_property != "None" and os.path.exists(proxy_property):
            log_callback(f"   [BEREITS VORHANDEN] Interner Proxy existiert für: {clip.GetName()}")
        else:
            clips_to_render.append(clip)
            
    if not clips_to_render:
        log_callback("\n[HINWEIS] Keine neuen Videos für die interne Proxy-Generierung.")
        return
        
    total_jobs = len(clips_to_render)
    log_callback(f"\n[SCHRITT 2/2] Starte native DaVinci Resolve Proxy-Generierung für {total_jobs} Clips...")
    
    start_time = time.perf_counter()
    try:
        success = current_project.GenerateProxyMedia(clips_to_render)
        if success:
            log_callback(f"       -> [OK] Alle {total_jobs} Proxies intern generiert und verknüpft.")
        else:
            for idx, clip in enumerate(clips_to_render, start=1):
                if clip.GenerateProxyMedia():
                    log_callback(f"             -> [{idx}/{total_jobs}] [OK] Erstellt: {clip.GetName()}")
                else:
                    log_callback(f"             -> [{idx}/{total_jobs}] [FEHLER] Abgelehnt für {clip.GetName()}")
    except Exception as e:
        log_callback(f"       -> [API FEHLER] Fehler während der internen Proxy-Generierung: {e}")

    end_time = time.perf_counter()
    duration = end_time - start_time
    log_callback(f"\n⏱️  [BENCHMARK Resolve Engine] Gesamte Renderzeit: {duration:.2f} Sekunden")