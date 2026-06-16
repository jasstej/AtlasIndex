import os
import logging
from typing import List, Set, Dict, Any
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project

logger = logging.getLogger(__name__)

# Standard folders that should never be scanned to save CPU cycles and prevent loops
IGNORE_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    ".cache",
    ".pytest_cache",
    "bower_components",
    "out"
}

# Signatures to map filenames/extensions to technologies
SIGNATURES = {
    "package.json": "nodejs",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "composer.json": "php",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
}

EXTENSION_TO_TECH = {
    ".py": "python",
    ".js": "nodejs",
    ".jsx": "nodejs",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".php": "php",
    ".cs": "dotnet",
    ".sh": "shell",
    ".bash": "shell",
    ".html": "html",
    ".css": "css",
}

def detect_technologies_in_dir(path: str) -> Set[str]:
    """Inspects files in a directory to detect the technologies used."""
    techs = set()
    try:
        entries = os.listdir(path)
    except Exception as e:
        logger.warning(f"Failed to list directory {path}: {e}")
        return techs

    # Check for specific files and extensions
    for entry in entries:
        if entry in SIGNATURES:
            techs.add(SIGNATURES[entry])
        elif entry.endswith(".csproj") or entry.endswith(".sln"):
            techs.add("dotnet")
        elif entry == ".git":
            techs.add("git")
        
        _, ext = os.path.splitext(entry)
        if ext.lower() in EXTENSION_TO_TECH:
            techs.add(EXTENSION_TO_TECH[ext.lower()])

    # Check shebang for files without extension
    for entry in entries:
        full_entry_path = os.path.join(path, entry)
        if os.path.isfile(full_entry_path) and not entry.startswith(".") and "." not in entry:
            try:
                # Read the first line (up to 256 bytes) to check shebang
                with open(full_entry_path, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()
                    if first_line.startswith("#!"):
                        if "python" in first_line:
                            techs.add("python")
                        elif "bash" in first_line or "sh" in first_line:
                            techs.add("shell")
                        elif "node" in first_line:
                            techs.add("nodejs")
            except Exception:
                pass

    return techs

def discover_projects(root_path: str, db: Session) -> List[Project]:
    """
    Recursively scans the directory tree starting at root_path.
    Identifies project roots and updates the database registry.
    """
    root_path = os.path.abspath(root_path)
    logger.info(f"Starting project discovery scan at {root_path}")
    projects_found = []

    # BFS or DFS traversal
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        # Prune ignored directories in-place to avoid traversing them
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS
            and not d.startswith(".")
            and not (d == "pkg" and os.path.basename(dirpath) == "go")
        ]

        # Check if current directory is a project root
        techs = detect_technologies_in_dir(dirpath)
        is_direct_child = (os.path.dirname(dirpath) == root_path)
        
        # If no technology signatures are detected, but the directory is a direct child of the root scan path,
        # and it contains any non-ignored files or directories, treat it as a project with "generic" technology.
        if not techs and is_direct_child:
            try:
                entries = [e for e in os.listdir(dirpath) if e not in IGNORE_DIRS and not e.startswith(".")]
                if entries:
                    techs.add("generic")
            except Exception:
                pass

        if techs:
            project_name = os.path.basename(dirpath)
            # If the folder name is empty or dot, use parent folder name
            if not project_name or project_name == ".":
                project_name = os.path.basename(os.path.dirname(dirpath)) or "unknown-project"

            # Check if project already exists in the database
            existing_project = db.query(Project).filter(Project.path == dirpath).first()
            
            if existing_project:
                existing_project.name = project_name
                # Merge technologies lists
                existing_techs = set(existing_project.technologies or [])
                existing_project.technologies = list(existing_techs.union(techs))
                project_record = existing_project
                logger.info(f"Updated existing project: {project_name} at {dirpath} with techs: {project_record.technologies}")
            else:
                project_record = Project(
                    name=project_name,
                    path=dirpath,
                    description=f"Auto-discovered {', '.join(techs)} project",
                    technologies=list(techs),
                    metadata_json={}
                )
                db.add(project_record)
                logger.info(f"Discovered new project: {project_name} at {dirpath} with techs: {list(techs)}")

            db.commit()
            db.refresh(project_record)
            projects_found.append(project_record)

    return projects_found
