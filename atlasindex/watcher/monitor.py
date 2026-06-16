import os
import time
import logging
import threading
from typing import Dict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from sqlalchemy.orm import Session
from atlasindex.storage.database import SessionLocal
from atlasindex.storage.models import Project, File
from atlasindex.indexer.core import INDEXABLE_EXTENSIONS, IGNORE_DIRS, index_file, MasterParser, is_indexable_file

logger = logging.getLogger(__name__)

def is_ignored_path(rel_path: str) -> bool:
    parts = rel_path.split(os.sep)
    for part in parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return True
    if "go" in parts and "pkg" in parts:
        go_idx = parts.index("go")
        if go_idx < len(parts) - 1 and parts[go_idx + 1] == "pkg":
            return True
    return False

class FileChangeHandler(FileSystemEventHandler):
    """Handles file system events for a specific project."""
    def __init__(self, project_id: str, project_path: str):
        self.project_id = project_id
        self.project_path = os.path.abspath(project_path)
        self.parser = MasterParser()
        # Track last modified time to debounce events (avoid duplicate triggers)
        self.last_triggered = {}

    def on_modified(self, event):
        self._handle_change(event)

    def on_created(self, event):
        self._handle_change(event)

    def on_deleted(self, event):
        if event.is_directory:
            return
        
        file_path = os.path.abspath(event.src_path)
        rel_path = os.path.relpath(file_path, self.project_path)

        # Skip ignored paths
        if is_ignored_path(rel_path):
            return

        if is_indexable_file(file_path):
            logger.info(f"File deleted: {rel_path}. Removing from index...")
            db = SessionLocal()
            try:
                existing_file = db.query(File).filter(
                    File.project_id == self.project_id,
                    File.path == rel_path
                ).first()
                if existing_file:
                    db.delete(existing_file)
                    db.commit()
            except Exception as e:
                logger.error(f"Error handling file deletion in watcher: {e}")
            finally:
                db.close()

    def _handle_change(self, event):
        if event.is_directory:
            return

        file_path = os.path.abspath(event.src_path)
        rel_path = os.path.relpath(file_path, self.project_path)

        # Skip ignored paths
        if is_ignored_path(rel_path):
            return

        if is_indexable_file(file_path):
            now = time.time()
            # Debounce: skip if triggered in the last 1.5 seconds
            if now - self.last_triggered.get(file_path, 0) < 1.5:
                return
            self.last_triggered[file_path] = now

            logger.info(f"File changed: {rel_path}. Re-indexing...")
            # Run indexing in a thread-safe DB session
            db = SessionLocal()
            try:
                index_file(file_path, self.project_id, rel_path, db, self.parser)
            except Exception as e:
                logger.error(f"Error re-indexing file {rel_path} in watcher: {e}")
            finally:
                db.close()


class CodebaseWatcher:
    """Manages watchers across all projects registered in the database."""
    def __init__(self):
        self.observer = Observer()
        self.watch_keys: Dict[str, Any] = {}  # Maps project_id -> watchdog watch object
        self.is_running = False

    def start(self):
        """Starts the watchdog observer thread."""
        if self.is_running:
            return
        
        logger.info("Starting AtlasIndex codebase watcher...")
        self.observer.start()
        self.is_running = True
        self._sync_watches()

        # Run background sync to detect new projects registered via API
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()

    def stop(self):
        """Stops the watchdog observer thread."""
        if not self.is_running:
            return
        logger.info("Stopping codebase watcher...")
        self.observer.stop()
        self.observer.join()
        self.is_running = False

    def _sync_watches(self):
        """Syncs filesystem watchers with projects registered in the DB."""
        db = SessionLocal()
        try:
            projects = db.query(Project).all()
            db_project_ids = {p.id for p in projects}

            # 1. Remove watches for projects no longer in the DB
            for project_id in list(self.watch_keys.keys()):
                if project_id not in db_project_ids:
                    logger.info(f"Removing file watcher for deleted project: {project_id}")
                    watch = self.watch_keys.pop(project_id)
                    self.observer.unschedule(watch)

            # 2. Add watches for new projects
            for p in projects:
                if p.id not in self.watch_keys:
                    if os.path.exists(p.path):
                        logger.info(f"Scheduling file watcher for project: {p.name} at {p.path}")
                        handler = FileChangeHandler(p.id, p.path)
                        try:
                            watch = self.observer.schedule(handler, p.path, recursive=True)
                            self.watch_keys[p.id] = watch
                        except Exception as e:
                            logger.error(f"Failed to watch path {p.path}: {e}")
                    else:
                        logger.warning(f"Project path {p.path} does not exist, skipping watch.")
        except Exception as e:
            logger.error(f"Error syncing watches: {e}")
        finally:
            db.close()

    def _sync_loop(self):
        """Runs periodic sync to pick up new projects registered dynamically."""
        while self.is_running:
            time.sleep(10)  # Check DB for updates every 10 seconds
            self._sync_watches()
