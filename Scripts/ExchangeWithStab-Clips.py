import os
import DaVinciResolveScript as bmd

def replace_with_stabilized():
    # Verbindung zu Resolve herstellen
    resolve = bmd.scriptapp("Resolve")
    if not resolve:
        print("Fehler: Verbindung zu DaVinci Resolve fehlgeschlagen.")
        return
        
    project = resolve.GetProjectManager().GetCurrentProject()
    media_pool = project.GetMediaPool()
    selected_clips = media_pool.GetSelectedClips()
    
    if not selected_clips:
        print("!!! HINWEIS: Keine Clips im Media Pool ausgewählt.")
        return

    success_count = 0
    missing_paths = []
    processed_folder = ""

    print("--- Gyroflow Replace Start ---")

    for clip in selected_clips:
        old_path = clip.GetClipProperty("File Path")
        if not old_path:
            continue
            
        base, ext = os.path.splitext(old_path)
        processed_folder = os.path.dirname(old_path)
        
        # Prüfung auf vorhandenes Suffix
        if base.lower().endswith("_stab"):
            target_path = old_path
        else:
            target_path = f"{base}_stab{ext}"
        
        if os.path.exists(target_path):
            if clip.ReplaceClip(target_path):
                print(f"ERFOLG: {os.path.basename(target_path)} verknüpft.")
                success_count += 1
        else:
            missing_paths.append(os.path.basename(target_path))

    # Ergebnis-Zusammenfassung in der Konsole
    print("-" * 30)
    summary = f"ERGEBNIS: {success_count} Clips erfolgreich umgestellt."
    if missing_paths:
        summary += f"\nFEHLEND: {len(missing_paths)} Dateien (siehe Liste oben)."
    print(summary)
    print("--- Gyroflow Replace Ende ---")

    # OPTIONAL: Eine kleine Textdatei im Ordner erstellen als Bestätigung
    if processed_folder and os.path.exists(processed_folder):
        log_path = os.path.join(processed_folder, "_gyroflow_log.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(summary)

if __name__ == "__main__":
    replace_with_stabilized()