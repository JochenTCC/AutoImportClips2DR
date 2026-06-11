#!/usr/bin/env python
import os
from datetime import datetime

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

    def _organize_and_tag_clips(self, clips, batch_name, target_bin):
        """Phase 4: Setzt Metadaten, steuert Clip-Farben und erstellt Pancake-Timelines."""
        self.log_callback(f"   -> [METADATEN & ORGANISATION] Tagge Clips und generiere Profile...")
        
        # Behoben: camera_type und log_callback werden jetzt korrekt übergeben
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
            if batch_name != "Flat-Import":
                day_pancake_bin = get_or_create_bin(self.media_pool, self.pancakes_bin, batch_name)
                timeline_name = f"PC_{batch_name}_{self.camera_type}"
                self._create_or_extend_pancake_timeline(timeline_name, clips, day_pancake_bin)
            else:
                timeline_name = f"PC_FLAT_{self.camera_type}"
                self._create_or_extend_pancake_timeline(timeline_name, clips, self.pancakes_bin)

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

    def _create_or_extend_pancake_timeline(self, timeline_name, clips_to_add, target_pancake_bin):
        """Private Hilfsfunktion zur Erstellung/Erweiterung strukturierter Pancake-Schnittspuren."""
        self.media_pool.SetCurrentFolder(target_pancake_bin)
        pancake_timeline = None
        
        for item in target_pancake_bin.GetClipList():
            if item.GetClipProperty("Type") == "Timeline" and item.GetName() == timeline_name:
                pancake_timeline = item
                break
                
        try: 
            clips_to_add.sort(key=lambda c: c.GetClipProperty("Start TC"))
        except Exception: 
            pass
        
        existing_clip_names = set()
        if pancake_timeline:
            try:
                raw_items = pancake_timeline.GetItemListInTrack("video", 1)
                for item in (raw_items if raw_items else []):
                    mp_item = item.GetMediaPoolItem()
                    if mp_item: 
                        existing_clip_names.add(mp_item.GetName())
            except Exception: 
                pass
            
        clips_to_append = [c for c in clips_to_add if c.GetName() not in existing_clip_names]
        if not clips_to_append: 
            return
            
        if not pancake_timeline:
            pancake_timeline = self.media_pool.CreateTimelineFromClips(timeline_name, [clips_to_append[0]])
            remaining = clips_to_append[1:]
        else:
            remaining = clips_to_append
            
        if pancake_timeline and remaining:
            self.current_project.SetCurrentTimeline(pancake_timeline)
            self.media_pool.AppendToTimeline(remaining)
            # NEU & Behoben: Wendet das DRX-Grading auf die Pancake-Timeline an
            apply_drx_grading_to_timeline(pancake_timeline, self.base_drx_dir, self.camera_type, self.camera_mappings, self.log_callback)


def ingest_media_source(*args, **kwargs):
    """
    Schnittstelle für den Ingest-Prozess.
    Instanziiert den zustandsbehafteten SourceIngestWorker und triggert die Pipeline.
    """
    worker = SourceIngestWorker(*args, **kwargs)
    return worker.execute_pipeline()