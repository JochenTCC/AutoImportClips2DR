#!/usr/bin/env python
import os
from datetime import datetime
from collections import defaultdict

from .config import PROXY_ELIGIBLE_EXTENSIONS, WEEKDAYS_DE
from .utils import get_media_dates_from_card, get_media_files_from_dir, get_media_files_flattened
from .drive_ops import copy_files_via_robocopy
from .resolve_media import get_or_create_bin, tag_media_pool_items, get_clip_color_by_label, apply_drx_grading_to_timeline


class SourceIngestWorker:
    """
    Kapselt die Ingest-Pipeline für eine einzelne Medienquelle (SD-Karte oder lokaler Ordner).
    Aufgeteilt in 5 logische, sequentiell ausgeführte Workflow-Phasen zur besseren Wartbarkeit.
    """
    def __init__(self, label, source_drive, format_mode, project_start_date, 
                 footage_dir, project_proxy_dir, current_project, media_pool, footage_bin, 
                 pancakes_bin, create_pancakes, log_callback, raw_queue, config,
                 trash_filepaths=None, use_h265=False):
        
        # Alle übergebenen Parameter strikt an die Instanz binden
        self.label = label
        self.source_drive = source_drive
        self.format_mode = format_mode
        self.project_start_date = project_start_date
        self.footage_dir = footage_dir
        self.project_proxy_dir = project_proxy_dir
        self.current_project = current_project
        self.media_pool = media_pool
        self.footage_bin = footage_bin
        self.pancakes_bin = pancakes_bin
        self.create_pancakes = create_pancakes
        self.log_callback = log_callback
        self.raw_queue = raw_queue
        self.config = config
        self.trash_filepaths = set(trash_filepaths) if trash_filepaths else set()
        self.use_h265 = use_h265

        # Lokale Extraktion der Parameter aus der zentralen Config
        self.camera_colors = config.get("camera_colors", {})
        self.camera_mappings = config.get("camera_mappings", [])
        self.base_drx_dir = config.get("BASE_DRX_DIR", "")
        self.resolution_mappings = config.get("resolution_mappings", {})

        # Clip-Farbe über die Hilfsfunktion bestimmen
        self.clip_color = get_clip_color_by_label(label, self.camera_colors)

        # Kamera-Typ dynamisch ermitteln (wichtig für das Metadaten-Tagging)
        self.camera_type = "UNKNOWN"
        label_upper = label.upper()
        for key in self.camera_colors.keys():
            key_upper = key.upper()
            parts = key_upper.split('_')
            matched = False
            for part in parts:
                if len(part) > 2 and part in label_upper:
                    self.camera_type = part
                    matched = True
                    break
            if matched: break
        if self.camera_type == "UNKNOWN":
            for key in self.camera_colors.keys():
                if key.upper() in label_upper:
                    self.camera_type = key.upper()
                    break
            else:
                self.camera_type = "REC709"

        # Pfad- und Bin-Verschachtelung basierend auf dem Kamera-Label initialisieren
        if label in ["FOOTAGE_ROOT", "Footage"]:
            self.cam_base_target_dir = footage_dir
            self.cam_base_proxy_dir = project_proxy_dir
            self.bin_label = "Footage"
        else:
            self.cam_base_target_dir = os.path.join(footage_dir, label)
            self.cam_base_proxy_dir = os.path.join(project_proxy_dir, label)
            self.bin_label = label

    def execute_pipeline(self):
        """Haupt-Orchestrator der Worker-Klasse."""
        self.log_callback(f"\n[INFO] Starte Pipeline für Medienquelle: '{self.label}'")
        
        try:
            # PHASE 1: Discovery & Filterung (berücksichtigt lokale & externe Datumsstrukturen)
            batches = self._prepare_source_batches()
            if not batches:
                self.log_callback(f"   [HINWEIS] Keine relevanten Mediendateien für '{self.label}' gefunden.")
                return

            # Haupt-Bin für die Kamera im Media Pool erstellen (z.B. "A_CAM")
            cam_bin = get_or_create_bin(self.media_pool, self.footage_bin, self.bin_label)

            for sub_folder, source_files in batches.items():
                # Pfade sauber zusammensetzen (Unterordner nur anhängen, wenn vorhanden)
                sub_footage_dir = os.path.join(self.cam_base_target_dir, sub_folder) if sub_folder else self.cam_base_target_dir
                sub_proxy_dir = os.path.join(self.cam_base_proxy_dir, sub_folder) if sub_folder else self.cam_base_proxy_dir
                
                log_batch_name = sub_folder if sub_folder else "Flat-Import"
                self.log_callback(f"\n   --- Verarbeite Batch: {log_batch_name} ({len(source_files)} Dateien) ---")
                
                os.makedirs(sub_footage_dir, exist_ok=True)
                os.makedirs(sub_proxy_dir, exist_ok=True)

                # PHASE 2: Datentransfer (Physisches Kopieren nur von externen SD-Karten)
                if self.source_drive:
                    self._transfer_assets_to_storage(source_files, sub_footage_dir)
                    local_files = [os.path.join(sub_footage_dir, os.path.basename(f)) for f in source_files]
                else:
                    local_files = source_files

                # Filtern gegen die Ausschuss-Blacklist vor dem Resolve-Import
                target_bin = get_or_create_bin(self.media_pool, cam_bin, sub_folder) if sub_folder else cam_bin
                existing_bin_filenames = {c.GetName() for c in target_bin.GetClipList() if c}
                
                final_import_files = [
                    f for f in local_files 
                    if f not in self.trash_filepaths and os.path.basename(f) not in existing_bin_filenames
                ]
                
                if not final_import_files:
                    self.log_callback(f"   [INFO] Keine neuen Dateien in diesem Batch (entweder auf Blacklist oder bereits importiert).")
                    continue

                # PHASE 3: Resolve Ingest
                imported_clips = self._import_to_resolve_mediapool(final_import_files, target_bin)
                
                if not imported_clips:
                    self.log_callback(f"   [WARNUNG] Import fehlgeschlagen oder Clips bereits im Media Pool vorhanden.")
                    continue

                if not isinstance(imported_clips, list):
                    imported_clips = [imported_clips]

                # PHASE 4: Kuration & Metadaten (Tagging, Clip-Farben, Pancakes)
                self._organize_and_tag_clips(imported_clips, log_batch_name, target_bin)

                # PHASE 5: Pipeline-Registrierung für Proxies
                self._queue_eligible_proxies(imported_clips, sub_proxy_dir)

        except Exception as e:
            if hasattr(self, 'log_callback') and self.log_callback:
                self.log_callback(f"   [CRASH] Unerwarteter Fehler im SourceIngestWorker für '{self.label}': {e}")
            else:
                print(f"[CRASH] Unerwarteter Fehler und kein log_callback verfügbar: {e}")

    def _prepare_source_batches(self):
        """Phase 1: Analysiert die Quelle und gruppiert Dateien basierend auf dem Format-Modus."""
        batches = {}
        scan_dir = self.source_drive if self.source_drive else self.cam_base_target_dir

        if self.format_mode in ["NONE", "Permanent-Struktur"] or "Karten-Ordner" in self.format_mode:
            if self.source_drive:
                files = get_media_files_flattened(scan_dir)
            else:
                files = get_media_files_from_dir(scan_dir)
            
            if files:
                batches[""] = files
        else:
            date_groups = get_media_dates_from_card(scan_dir)
            for date_str, files in date_groups.items():
                if not files:
                    continue
                try:
                    day_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    if self.format_mode == "YYMMDD":
                        sub_folder_name = day_obj.strftime('%y%m%d')
                    elif self.format_mode == "WEEKDAY":
                        sub_folder_name = WEEKDAYS_DE[day_obj.weekday()]
                    elif self.format_mode == "COUNTER":
                        delta_days = (day_obj - self.project_start_date).days if self.project_start_date else 0
                        sub_folder_name = f"Tag-{str(delta_days + 1).zfill(2)}"
                    else:
                        sub_folder_name = date_str
                except Exception:
                    sub_folder_name = date_str
                    
                batches[sub_folder_name] = files
                
        return batches

    def _transfer_assets_to_storage(self, source_files, target_dir):
        """Phase 2: Führt den physischen Datentransfer via Robocopy aus."""
        self.log_callback(f"   -> [TRANSFER] Synchronisiere Daten auf Speichermedium...")
        if self.format_mode in ["Permanent-Struktur"] or "Karten-Ordner" in self.format_mode:
            copy_files_via_robocopy(self.source_drive, target_dir)
        else:
            for src_file in source_files:
                src_dir = os.path.dirname(src_file)
                f_name = os.path.basename(src_file)
                copy_files_via_robocopy(src_dir, target_dir, file_name=f_name)

    def _import_to_resolve_mediapool(self, file_paths, target_bin):
        """Phase 3: Schreibt die Assets in die DaVinci Resolve Datenbank."""
        self.media_pool.SetCurrentFolder(target_bin)
        self.log_callback(f"   -> [RESOLVE INGEST] Importiere {len(file_paths)} Dateien in Bin '{target_bin.GetName()}'...")
        return self.media_pool.ImportMedia(file_paths)

    def _get_resolution_mapping_data(self, clip):
        """Ermittelt die Auflösung des Clips und extrahiert den Template-Dateinamen sowie ein Suffix."""
        raw_res = ""
        try:
            raw_res = clip.GetClipProperty("Resolution")
        except Exception as e:
            self.log_callback(f"   [WARNUNG] Konnte 'Resolution' nicht auslesen: {e}")
        
        raw_res = str(raw_res).strip()
        
        # 1. Exakter Match in JSON-Konfiguration
        for mapping in self.resolution_mappings:
            if mapping.get("resolution") == raw_res:
                tpl = mapping.get("pancake_template", "")
                sfx = tpl.replace("PC-Template-", "").replace(".drt", "") if tpl else raw_res
                return tpl, sfx

        # 2. Fallback auf "UNKNOWN"
        for mapping in self.resolution_mappings:
            if mapping.get("resolution") == "UNKNOWN":
                tpl = mapping.get("pancake_template", "")
                sfx = tpl.replace("PC-Template-", "").replace(".drt", "") if tpl else "UNKNOWN"
                return tpl, sfx

        return "PC-Template-4K-OG.drt", "UNKNOWN"

    def _organize_and_tag_clips(self, clips, batch_name, target_bin):
        """Phase 4: Setzt Metadaten, steuert Clip-Farben und erstellt Pancake-Timelines auf Template-Basis."""
        self.log_callback(f"   -> [METADATEN & ORGANISATION] Tagge Clips und generiere Profile...")
        
        tag_media_pool_items(clips, self.camera_type, self.log_callback)
        
        for clip in clips:
            if not clip: continue
            try:
                clip.SetClipProperty("Clip Color", self.clip_color)
            except Exception:
                try:
                    clip.SetClipColor(self.clip_color)
                except Exception:
                    pass

        if self.create_pancakes and self.pancakes_bin:
            clips_by_template = defaultdict(list)
            for clip in clips:
                if not clip: continue
                tpl_name, suffix = self._get_resolution_mapping_data(clip)
                clips_by_template[(tpl_name, suffix)].append(clip)
            
            for (tpl_name, suffix), res_clips in clips_by_template.items():
                if batch_name != "Flat-Import":
                    day_pancake_bin = get_or_create_bin(self.media_pool, self.pancakes_bin, batch_name)
                    timeline_name = f"PC_{batch_name}_{self.camera_type}_{suffix}"
                    self._create_or_extend_pancake_timeline(timeline_name, tpl_name, res_clips, day_pancake_bin)
                else:
                    timeline_name = f"PC_FLAT_{self.camera_type}_{suffix}"
                    self._create_or_extend_pancake_timeline(timeline_name, tpl_name, res_clips, self.pancakes_bin)

    def _duplicate_template_timeline(self, template_name, target_bin, new_name):
        """Lädt eine physische .drt-Datei direkt aus dem DRX-Verzeichnis und benennt sie um."""
        if not self.base_drx_dir:
            self.log_callback(f"   [FEHLER] BASE_DRX_DIR ist in der Konfiguration leer oder fehlt.")
            return None

        # Da der Dateiname in der JSON bereits komplett mit Endung hinterlegt ist, hängen wir nichts an
        drt_path = os.path.join(self.base_drx_dir, template_name)
        
        if not os.path.exists(drt_path):
            self.log_callback(f"   [FEHLER] Physische Template-Datei existiert nicht: '{drt_path}'")
            return None
            
        try:
            self.media_pool.SetCurrentFolder(target_bin)
            imported_timeline = self.media_pool.ImportTimelineFromFile(drt_path)
            
            target_tl = imported_timeline if (imported_timeline and not isinstance(imported_timeline, bool)) else self.current_project.GetCurrentTimeline()
            
            if target_tl:
                if target_tl.SetName(new_name):
                    return target_tl
            
            # Fallback-Suche im Projekt, falls die API die Timeline nicht direkt zurückgibt
            possible_names = [template_name, os.path.splitext(template_name)[0]]
            for i in range(1, self.current_project.GetTimelineCount() + 1):
                tl = self.current_project.GetTimelineByIndex(i)
                if tl and tl.GetName() in possible_names:
                    tl.SetName(new_name)
                    return tl
                    
            return target_tl
            
        except Exception as e:
            self.log_callback(f"   [FEHLER] Ausnahme bei Import von physischem Template: {e}")
            return None

    def _create_or_extend_pancake_timeline(self, timeline_name, template_name, clips_to_add, target_pancake_bin):
        """Überprüft die Existenz der Pancake-Timeline, importiert das Template bei Bedarf und hängt Clips an."""
        self.media_pool.SetCurrentFolder(target_pancake_bin)
        pancake_timeline_item = None
        
        for item in target_pancake_bin.GetClipList():
            if item and item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                pancake_timeline_item = item
                break
                
        try:
            clips_to_add.sort(key=lambda c: os.path.getmtime(c.GetClipProperty("File Path")))
        except Exception as e:
            self.log_callback(f"   [HINWEIS] Sortierung nach Dateidatum fehlgeschlagen, weiche auf Start TC aus: {e}")
            try: 
                clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
            except Exception: 
                pass
        
        existing_clip_names = set()
        pancake_timeline_obj = None
        
        if pancake_timeline_item:
            # Holt das echte Timeline-Objekt aus dem Projekt, um die Clips der Spur auszulesen
            for i in range(1, self.current_project.GetTimelineCount() + 1):
                tl = self.current_project.GetTimelineByIndex(i)
                if tl and tl.GetName() == timeline_name:
                    pancake_timeline_obj = tl
                    break
            if pancake_timeline_obj:
                try:
                    raw_items = pancake_timeline_obj.GetItemListInTrack("video", 1)
                    for item in (raw_items if raw_items else []):
                        mp_item = item.GetMediaPoolItem()
                        if mp_item: 
                            existing_clip_names.add(mp_item.GetName())
                except Exception: 
                    pass
            
        clips_to_append = [c for c in clips_to_add if c.GetName() not in existing_clip_names]
        if not clips_to_append: 
            return
            
        if not pancake_timeline_item:
            self.log_callback(f"   -> Importiere externes Template '{template_name}' von Festplatte...")
            pancake_timeline_obj = self._duplicate_template_timeline(template_name, target_pancake_bin, timeline_name)
            
            if not pancake_timeline_obj:
                self.log_callback(f"   [WARNUNG] DRT-Import fehlgeschlagen. Erzeuge leere Standard-Timeline.")
                pancake_timeline_obj = self.media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
                clips_to_append = clips_to_append[1:]
        
        if pancake_timeline_obj and clips_to_append:
            try:
                self.current_project.SetCurrentTimeline(pancake_timeline_obj)
                self.media_pool.AppendToTimeline(clips_to_append)
                apply_drx_grading_to_timeline(pancake_timeline_obj, self.base_drx_dir, self.camera_type, self.camera_mappings, self.log_callback)
            except Exception as e:
                self.log_callback(f"   [FEHLER] Clips konnten nicht an Timeline angehängt werden: {e}")

    def _queue_eligible_proxies(self, clips, sub_proxy_dir):
        """Phase 5: Filtert clips auf Video-Container und schiebt sie in das globale Render-Array."""
        queued_count = 0
        for clip in clips:
            if not clip: continue
            try:
                path = clip.GetClipProperty("File Path")
                if path and path.lower().endswith(PROXY_ELIGIBLE_EXTENSIONS):
                    expected_proxy_path = os.path.join(sub_proxy_dir, os.path.basename(path))
                    if os.path.exists(expected_proxy_path):
                        self.log_callback(f"   [BEREITS VORHANDEN] Proxy existiert: {os.path.basename(path)}")
                        try: clip.LinkProxyMedia(expected_proxy_path)
                        except Exception: pass
                    else:
                        self.raw_queue.append((clip, path, sub_proxy_dir))
                        queued_count += 1
            except Exception:
                pass
                
        if queued_count > 0:
            self.log_callback(f"   -> [QUEUE] {queued_count} Clip(s) für FFmpeg-Proxy-Pipeline registriert.")


def ingest_media_source(*args, **kwargs):
    """
    Schnittstelle für den Ingest-Prozess.
    Instanziiert den zustandsbehafteten SourceIngestWorker und triggert die Pipeline.
    """
    worker = SourceIngestWorker(*args, **kwargs)
    return worker.execute_pipeline()