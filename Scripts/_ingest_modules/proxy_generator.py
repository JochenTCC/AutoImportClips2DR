#!/usr/bin/env python
import os
import sys
import subprocess
import time

def render_and_link_proxies_ffmpeg(raw_queue, use_h264_or_h265, log_callback, progress_callback=None):
    """Verarbeitet die Proxy-Queue und führt das hardwarebeschleunigte FFmpeg-Rendering durch."""
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
    
    if use_h264_or_h265: # True für H.265
        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
    else:
        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
    
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    # --- STOPPUHR START ---
    start_time = time.perf_counter()
    
    for idx, (clip, source_path, expected_proxy_path) in enumerate(render_jobs, start=1):
        clip_name = os.path.basename(source_path)
        codec_label = "H.265" if use_h264_or_h265 else "H.264"
        log_callback(f"   [{idx}/{total_jobs}] Rendere {codec_label}-Proxy: {clip_name} ...")
        
        if progress_callback:
            overall_pct = int((idx / total_jobs) * 100)
            progress_callback(min(overall_pct, 99), f"Rendere FFmpeg Proxies... ({idx}/{total_jobs})")
        
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

    # --- STOPPUHR ENDE & AUSWERTUNG ---
    end_time = time.perf_counter()
    duration = end_time - start_time
    avg_per_clip = duration / total_jobs if total_jobs > 0 else 0
    
    log_callback(f"\n⏱️  [BENCHMARK FFmpeg]")
    log_callback(f"    - Gesamte Renderzeit: {duration:.2f} Sekunden ({duration/60:.2f} Minuten)")
    log_callback(f"    - Durchschnitt pro Clip: {avg_per_clip:.2f} Sekunden")


def render_and_link_proxies_DR_Engine(raw_queue, use_h264_or_h265, log_callback, current_project=None, progress_callback=None):
    """
    Verarbeitet die Proxy-Queue nativ über die DaVinci Resolve Render-Engine.
    """
    if not current_project:
        try:
            import DaVinciResolveScript as dvr_script
            resolve = dvr_script.scriptapp("Resolve")
            if resolve:
                current_project = resolve.GetProjectManager().GetCurrentProject()
        except Exception:
            pass

    if not current_project:
        log_callback("[FEHLER] Resolve-Projektkontext konnte für die Proxy-Generierung nicht ermittelt werden.")
        return

    clips_to_render = []
    
    for clip, source_path, proxy_dir in raw_queue:
        clip_name = os.path.basename(source_path)
        proxy_property = clip.GetClipProperty("Proxy")
        
        if proxy_property != "None" and os.path.exists(proxy_property):
            log_callback(f"   [BEREITS VORHANDEN] Interner Proxy existiert für: {clip_name}")
        else:
            if proxy_property != "None" and not os.path.exists(proxy_property):
                log_callback(f"   [OFFLINE] Resolve-DB verweist auf Proxy, Datei fehlt aber auf Festplatte. Wird neu erstellt: {clip_name}")
            clips_to_render.append(clip)
            
    if not clips_to_render:
        log_callback("\n[HINWEIS] Keine neuen Videos für die interne Proxy-Generierung.")
        return
        
    total_jobs = len(clips_to_render)
    log_callback(f"\n[SCHRITT 2/2] Starte native DaVinci Resolve Proxy-Generierung für {total_jobs} Clips...")
    
    start_time = time.perf_counter()
    
    try:
        if progress_callback:
            progress_callback(50, "Generiere Resolve Proxies (Batch)...")
            
        success = current_project.GenerateProxyMedia(clips_to_render)
        
        if success:
            log_callback(f"       -> [OK] Alle {total_jobs} Proxies intern generiert und verknüpft.")
        else:
            log_callback("       -> [WARNUNG] Batch-Generierung von Resolve abgelehnt. Versuche Einzelverarbeitung...")
            for idx, clip in enumerate(clips_to_render, start=1):
                c_name = clip.GetName()
                log_callback(f"          [{idx}/{total_jobs}] Generiere Proxy für: {c_name} ...")
                if progress_callback:
                    overall_pct = int((idx / total_jobs) * 100)
                    progress_callback(min(overall_pct, 99), f"Generiere Resolve Proxy... ({idx}/{total_jobs})")
                if clip.GenerateProxyMedia():
                    log_callback(f"             -> [OK] Erstellt.")
                else:
                    log_callback(f"             -> [FEHLER] Resolve verweigerte Generierung für {c_name}")
                    
    except Exception as e:
        log_callback(f"       -> [API FEHLER] Fehler während der internen Proxy-Generierung: {e}")

    end_time = time.perf_counter()
    duration = end_time - start_time
    avg_per_clip = duration / total_jobs if total_jobs > 0 else 0
    
    log_callback(f"\n⏱️  [BENCHMARK Resolve Engine]")
    log_callback(f"    - Gesamte Renderzeit: {duration:.2f} Sekunden ({duration/60:.2f} Minuten)")
    log_callback(f"    - Durchschnitt pro Clip: {avg_per_clip:.2f} Sekunden")