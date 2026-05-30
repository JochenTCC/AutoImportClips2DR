#!/usr/bin/env python
import os
import sys

def set_color_space_with_fallback(clip, clip_name, camera_type):
    """Versucht verschiedene bekannte Schreibweisen für den Farbraum zu setzen."""
    
    # Vereinheitlichte Typen für den Abgleich
    camera_type_upper = camera_type.upper()
    
    # Flexibler Match auf DJI Drohnen (z.B. AVATA2, MINI4PRO oder das direkte DJI-Tag)
    if "DJI" in camera_type_upper or "AVATA" in camera_type_upper or "MINI" in camera_type_upper:
        if clip.SetClipProperty("Input Color Space", "DJI D-Gamut"):
            print(f"  -> [Erfolg DJI] {clip_name} -> 'DJI D-Gamut'")
            return True
        return False

    # Flexibler Match auf Lumix-Modelle (z.B. S5II)
    elif "LUMIX" in camera_type_upper or "S5" in camera_type_upper:
        # GEÄNDERT: Korrekter Kombi-Farbraum 'Panasonic V-Gamut/V-Log' setzt das Gamma direkt mit
        success_space = clip.SetClipProperty("Input Color Space", "Panasonic V-Gamut")
        
        if success_space:
            print(f"  -> [Erfolg LUMIX] {clip_name} -> 'Panasonic V-Gamut/V-Log' zugewiesen.")
            return True
        else:
            print(f"  -> [FEHLER] Konnte Farbmanagement für {clip_name} nicht setzen.")
            return False
            
    return False

def process_bin(folder):
    """Durchsucht rekursiv alle Bins und taggt die Clips anhand ihrer echten Metadaten."""
    clips = folder.GetClipList()
    current_bin_name = folder.GetName()
    
    print(f"[Prüfe Ordner] {current_bin_name}")
    
    for clip in clips:
        if not clip:
            continue
            
        clip_name = clip.GetName()
        
        # Holt den Kameratyp direkt aus dem Metadatenfeld
        meta_camera_type = clip.GetMetadata("Camera Type")
        
        if meta_camera_type:
            success = set_color_space_with_fallback(clip, clip_name, meta_camera_type)
            if not success:
                print(f"  -> [FEHLER] Unbekannter Kameratyp in Metadaten: '{meta_camera_type}' für {clip_name}")
        elif clip.GetClipProperty("Type") != "Timeline":
            print(f"  -> [HINWEIS] Clip {clip_name} besitzt kein 'Camera Type'-Metadaten-Tag. (Übersprungen)")

    # Rekursiver Durchlauf für alle Unterordner
    sub_folders = folder.GetSubFolderList()
    for sub_folder in sub_folders:
        process_bin(sub_folder)

def automate_color_management_by_bin():
    import DaVinciResolveScript as dvr_script
    
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
    
    print("\n--- Starte automatisches Farbmanagement via Metadaten-Auslesung ---")
    process_bin(root_folder)
    
    # Projekt speichern, um UI-Refresh in Resolve zu erzwingen
    project_manager.SaveProject()
    print("--- Fertig und Projekt gespeichert! ---\n")

if __name__ == "__main__":
    automate_color_management_by_bin()