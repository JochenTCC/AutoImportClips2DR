#!/usr/bin/env python
import os
import sys
    
# Importe aus dem Unterordner
from _ingest_modules.config import BASE_TARGET_DIR


def set_color_space_with_fallback(clip, clip_name, camera_type):
    """Versucht verschiedene bekannte Schreibweisen für den Farbraum zu setzen."""
    
    if camera_type == "DJI":
        if clip.SetClipProperty("Input Color Space", "DJI D-Gamut"):
            print(f"  -> [Erfolg DJI] {clip_name} -> '{"DJI D-Gamut"}'")
            return True
        return False

    elif camera_type == "LUMIX":
        # Ursprünglicher, sauberer Ansatz: Getrenntes Setzen von Color Space und Gamma
        # Reihenfolge: Erst Color Space, dann Gamma, um UI-Überschreibungen zu minimieren.
        
        success_space = clip.SetClipProperty("Input Color Space", "Panasonic V-Gamut")
        success_gamma = clip.SetClipProperty("Input Gamma", "Panasonic V-Log")
        
        if success_space and success_gamma:
            print(f"  -> [Erfolg LUMIX] {clip_name} -> Space und Gamma separat gesetzt.")
            return True
        elif success_space:
            print(f"  -> [Teilerfolg LUMIX] {clip_name} -> Nur Color Space gesetzt (Gamma blockiert).")
            return True
        else:
            print(f"  -> [FEHLER] Konnte Farbmanagement für {clip_name} nicht setzen.")
            return False

def process_bin(folder, parent_camera_type=None):
    """Durchsucht rekursiv alle Bins und taggt die Clips."""
    clips = folder.GetClipList()
    current_bin_name = folder.GetName()
    bin_lower = current_bin_name.lower()
    
    current_camera_type = parent_camera_type
    
    if "avata" in bin_lower or "mini4" in bin_lower:
        current_camera_type = "DJI"
    elif bin_lower.startswith("s5") or "lumix" in bin_lower:
        current_camera_type = "LUMIX"
        
    status_msg = f"[Prüfe Ordner] {current_bin_name}"
    if current_camera_type:
        status_msg += f" (Modus: {current_camera_type}{' geerbt' if current_camera_type == parent_camera_type else ''})"
    print(status_msg)
    
    for clip in clips:
        clip_name = clip.GetName()
        
        if current_camera_type in ["DJI", "LUMIX"]:
            success = set_color_space_with_fallback(clip, clip_name, current_camera_type)
            if not success:
                print(f"  -> [FEHLER] Konnte keinen passenden Farbraum-String für {clip_name} finden.")

    sub_folders = folder.GetSubFolderList()
    for sub_folder in sub_folders:
        process_bin(sub_folder, current_camera_type)

def automate_color_management_by_bin():
    
    import DaVinciResolveScript as dvr_script
    resolve = dvr_script.scriptapp("Resolve")

    if "resolve" in globals():
        resolve_app = globals()["resolve"]
    else:
        resolve_app = dvr_script.scriptapp("Resolve")
        
    if not resolve_app:
        print("[FEHLER] Verbindung zu DaVinci Resolve fehlgeschlagen.")
        return

    project_manager = resolve_app.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    
    if not current_project:
        print("[FEHLER] Kein aktives Projekt geöffnet.")
        return
        
    media_pool = current_project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()
    
    print("\n--- Starte automatisches Farbmanagement mit getrennten Zuweisungen ---")
    process_bin(root_folder)
    
    # Projekt保存, um UI-Refresh zu erzwingen
    project_manager.SaveProject()
    print("--- Fertig und Projekt gespeichert! ---\n")

if __name__ == "__main__":
    automate_color_management_by_bin()