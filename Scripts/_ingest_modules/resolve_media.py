#!/usr/bin/env python
import os

def get_or_create_bin(media_pool, parent_folder, name):
    """Sucht nach einem Bin. Wenn es existiert, wird es zurückgegeben, sonst erstellt."""
    sub_folders = parent_folder.GetSubFolderList()
    for folder in sub_folders:
        if folder.GetName() == name:
            return folder
    return media_pool.AddSubFolder(parent_folder, name)

def create_resolve_bins(media_pool, root_folder):
    """Erstellt die Basis-Bin-Struktur im DaVinci Resolve Media Pool."""
    footage_bin = get_or_create_bin(media_pool, root_folder, "Footage")
    get_or_create_bin(media_pool, root_folder, "Music")
    get_or_create_bin(media_pool, root_folder, "Images")
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
    """Weist importierten Media-Pool-Items direkt das Kamera-Metadaten-Tag zu."""
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

def apply_drx_grading_to_timeline(timeline, base_drx_dir, camera_type, camera_mappings, log_callback):
    """Sucht das passende DRX-File aus den Mappings und wendet es via NodeGraph auf alle Video-Timeline-Items auf Track 1 an."""
    if not base_drx_dir or not camera_mappings:
        return

    drx_file_name = None
    for mapping in camera_mappings:
        if mapping.get("camera_type") == camera_type or camera_type in mapping.get("search_keywords", []):
            drx_file_name = mapping.get("drx_profile")
            break
    
    # Wenn kein DRX-Profil hinterlegt ist (z. B. bei REC709), sauber abbrechen
    if not drx_file_name:
        return

    drx_path = os.path.join(base_drx_dir, drx_file_name)
    if not os.path.exists(drx_path):
        log_callback(f"       [WARNUNG] DRX-Datei nicht gefunden: {drx_path}")
        return

    try:
        items = timeline.GetItemListInTrack("video", 1)
        if not items:
            return

        success_count = 0
        for item in items:
            if not item:
                continue
                
            # Schauen, ob wir den modernen NodeGraph vom Timeline-Item bekommen (Resolve 19+)
            if hasattr(item, "GetNodeGraph") and item.GetNodeGraph is not None:
                graph = item.GetNodeGraph()
                if graph and hasattr(graph, "ApplyGradeFromDRX") and graph.ApplyGradeFromDRX is not None:
                    # Gradings werden jetzt auf dem graph-Objekt angewendet
                    if graph.ApplyGradeFromDRX(drx_path, 0):
                        success_count += 1
                        continue # Erfolgreich, weiter zum nächsten Clip

            # FALLBACK für ältere Resolve-Versionen, falls GetNodeGraph nicht existiert
            if hasattr(item, "ApplyGradeFromDRX") and item.ApplyGradeFromDRX is not None:
                if item.ApplyGradeFromDRX(drx_path, 0):
                    success_count += 1
            else:
                # Letzter Rettungsversuch über das MediaPoolItem
                mp_item = item.GetMediaPoolItem()
                if mp_item and hasattr(mp_item, "ApplyGradeFromDRX") and mp_item.ApplyGradeFromDRX is not None:
                    if mp_item.ApplyGradeFromDRX(drx_path, 0):
                        success_count += 1

        if success_count > 0:
            log_callback(f"       -> [OK] DRX-Grading '{drx_file_name}' via NodeGraph auf {success_count} Clips angewendet.")
            
    except Exception as e:
        log_callback(f"       [HINWEIS] Fehler beim Anwenden des DRX-Gradings: {e}")

