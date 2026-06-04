#!/usr/bin/env python
import os
import sys
import subprocess

def render_and_link_proxies(raw_queue, use_h264_or_h265, log_callback):
    """Verarbeitet die Proxy-Queue und führt das hardwarebeschleunigte FFmpeg-Rendering durch."""
    render_jobs = []
    for clip, source_path, proxy_dir in raw_queue:
        clip_name = os.path.basename(source_path)
        # Wir erzwingen hier .mov als Endung für die Proxies, da PCM-Audio in .mp4 
        # von Resolve oft nicht sauber eingelesen wird.
        base_name, _ = os.path.splitext(clip_name)
        expected_proxy_path = os.path.join(proxy_dir, f"{base_name}.mov")
        os.makedirs(proxy_dir, exist_ok=True)
        
        if os.path.exists(expected_proxy_path):
            log_callback(f"   [BEREITS VORHANDEN] Proxy existiert auf Festplatte: {clip_name}")
            try: 
                success = clip.LinkProxyMedia(expected_proxy_path)
                if success:
                    log_callback(f"       -> [OK] Proxy erfolgreich nachträglich verknüpft.")
                else:
                    log_callback(f"       -> [WARNUNG] Resolve lehnte die Verknüpfung ab (Metadaten-Mismatch?).")
            except Exception as link_err: 
                log_callback(f"       -> [API FEHLER] Verknüpfung fehlgeschlagen: {link_err}")
        else:
            render_jobs.append((clip, source_path, expected_proxy_path))
    
    if not render_jobs:
        log_callback("\n[HINWEIS] Keine neuen Videos zum Rendern in der Queue.")
        return
        
    total_jobs = len(render_jobs)
    log_callback(f"\n[SCHRITT 2/2] Starte Proxy-Generierung für {total_jobs} neue Proxies...")
    
    # Video Codec Einstellungen
    if use_h264_or_h265: # True für H.265
        video_codec_args = ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "28"]
    else:
        video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
    
    # Audio-Einstellungen für Multichannel-Audio (Lumix S5II Fix)
    # -map 0:v  -> Nimm die Videospur
    # -map 0:a? -> Nimm ALLE Audiospuren (das Fragezeichen verhindert Fehler, falls ein Clip mal gar kein Audio hat)
    # -c:a pcm_s16le -> Konvertiert das Audio in unkomprimiertes 16-Bit PCM (perfekt für DaVinci Resolve .mov)
    audio_args = ["-map", "0:v", "-map", "0:a?", "-c:a", "pcm_s16le"]
    
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    for idx, (clip, source_path, expected_proxy_path) in enumerate(render_jobs, start=1):
        clip_name = os.path.basename(source_path)
        codec_label = "H.265" if use_h264_or_h265 else "H.264"
        log_callback(f"   [{idx}/{total_jobs}] Rendere {codec_label}-Proxy (4-Ch Audio Fix): {clip_name} ...")
        
        filter_str = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-i", source_path
        ] + video_codec_args + [
            "-vf", filter_str
        ] + audio_args + [
            expected_proxy_path
        ]
        
        try:
            # HIER WAR DER FEHLER BEHOBEN: stderr=subprocess.PIPE korrigiert
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, startupinfo=startupinfo)
            if os.path.exists(expected_proxy_path):
                success = clip.LinkProxyMedia(expected_proxy_path)
                if success:
                    log_callback(f"       -> [OK] Proxy erfolgreich verknüpft.")
                else:
                    log_callback(f"       -> [WARNUNG] Render-Datei generiert, aber Resolve verweigert Verknüpfung.")
        except subprocess.CalledProcessError as e:
            log_callback(f"       -> [FEHLER] FFmpeg-Rendering fehlgeschlagen für {clip_name}")
            if e.stderr:
                error_lines = e.stderr.strip().split('\n')[-3:]
                for err_line in error_lines:
                    log_callback(f"          | {err_line}")
        except Exception as e:
            log_callback(f"       -> [API FEHLER] Verknüpfung fehlgeschlagen: {e}")