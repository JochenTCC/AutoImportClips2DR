#!/usr/bin/env python
import os
import subprocess
from .config import BASE_TARGET_DIR, BASE_PROXY_DIR

def create_physical_directories(project_name):
    """Erstellt alle notwendigen Verzeichnisse auf der Festplatte."""
    project_dir = os.path.join(BASE_TARGET_DIR, project_name)
    project_proxy_dir = os.path.join(BASE_PROXY_DIR, project_name)
    
    # Haupt- und Footage-Ordner
    footage_dir = os.path.join(project_dir, "Footage")
    os.makedirs(footage_dir, exist_ok=True)
    
    # Zusätzliche Asset-Ordner auf gleicher Ebene
    os.makedirs(os.path.join(project_dir, "Music"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "Images"), exist_ok=True)
    
    return project_dir, footage_dir, project_proxy_dir

def copy_files_via_robocopy(source_dir, target_dir, file_name=None):
    """Führt ein effizientes Kopieren via Windows Robocopy im Hintergrund aus."""
    if file_name:
        cmd = ["robocopy", source_dir, target_dir, file_name, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
    else:
        cmd = ["robocopy", source_dir, target_dir, "/XO", "/NJH", "/NJS", "/NDL", "/NC", "/NS"]
        
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)