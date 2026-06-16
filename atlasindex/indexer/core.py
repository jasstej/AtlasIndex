import os
import hashlib
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project, File, Function, Class, Import, ApiEndpoint
from atlasindex.parsers.tree_sitter_parser import MasterParser

logger = logging.getLogger(__name__)

# List of file extensions we are interested in indexing
INDEXABLE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
    ".java", ".php", ".cs", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".c", ".sh", ".bash",
    ".md", ".txt", ".json", ".yml", ".yaml", ".ini", ".conf", ".config", ".xml", ".toml"
}

INDEXABLE_FILENAMES = {
    "caddyfile", "dockerfile", "makefile", "jenkinsfile"
}

# Directories to ignore during indexing
IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", "dist", "build", ".next", "target", ".cache",
    ".pytest_cache", "bower_components", "out"
}

def is_indexable_file(file_path: str) -> bool:
    """Checks if a file should be indexed by its extension, name, or shebang."""
    filename = os.path.basename(file_path)
    if filename.lower() in INDEXABLE_FILENAMES:
        return True
        
    _, ext = os.path.splitext(filename)
    if ext.lower() in INDEXABLE_EXTENSIONS:
        return True
        
    if not ext:  # No extension
        # Check if it is a script file with a shebang
        try:
            if os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()
                    if first_line.startswith("#!"):
                        for lang in ["python", "sh", "bash", "node", "perl", "ruby"]:
                            if lang in first_line:
                                return True
        except Exception:
            pass
            
    return False

def get_file_hash(file_path: str) -> str:
    """Calculates the SHA-256 hash of a file's content."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"Error hashing file {file_path}: {e}")
        return ""

def index_file(file_path: str, project_id: str, relative_path: str, db: Session, parser: MasterParser) -> None:
    """Parses a single file and inserts/updates its code constructs in the database."""
    try:
        # Check size and basic stats
        stat = os.stat(file_path)
        size = stat.st_size
        created_at = datetime.fromtimestamp(stat.st_ctime)
        modified_at = datetime.fromtimestamp(stat.st_mtime)

        # Read content safely
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Could not read file {file_path}: {e}")
            return

        file_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

        # Check if file already indexed and unchanged
        existing_file = db.query(File).filter(File.project_id == project_id, File.path == relative_path).first()
        if existing_file and existing_file.hash == file_hash:
            logger.debug(f"Skipping unchanged file: {relative_path}")
            return

        # Parse content
        parsed = parser.parse(content, file_path)

        # Clear old indices for this file if it exists
        if existing_file:
            db.delete(existing_file)
            db.commit()

        # Create new File record
        _, ext = os.path.splitext(file_path)
        lang = parser.get_language_from_ext(ext) or "unknown"
        
        file_record = File(
            project_id=project_id,
            path=relative_path,
            language=lang,
            size=size,
            hash=file_hash,
            created_at=created_at,
            modified_at=modified_at
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)

        # Add functions
        for func in parsed.functions:
            func_record = Function(
                file_id=file_record.id,
                name=func.name,
                parameters=func.parameters,
                line_number=func.line_number,
                docstring=func.docstring
            )
            db.add(func_record)

        # Add classes
        for cls in parsed.classes:
            cls_record = Class(
                file_id=file_record.id,
                name=cls.name,
                methods=cls.methods,
                inheritance=cls.inheritance,
                line_number=cls.line_number
            )
            db.add(cls_record)

        # Add imports
        for imp in parsed.imports:
            imp_record = Import(
                file_id=file_record.id,
                name=imp.name,
                module=imp.module,
                line_number=imp.line_number
            )
            db.add(imp_record)

        # Add API endpoints
        for ep in parsed.endpoints:
            ep_record = ApiEndpoint(
                project_id=project_id,
                file_id=file_record.id,
                method=ep.method,
                path=ep.path,
                line_number=ep.line_number
            )
            db.add(ep_record)

        db.commit()
        logger.info(f"Indexed file {relative_path} (extracted: {len(parsed.functions)} functions, {len(parsed.classes)} classes, {len(parsed.endpoints)} endpoints)")

    except Exception as e:
        logger.error(f"Failed to index file {file_path}: {e}", exc_info=True)
        db.rollback()

def index_project(project: Project, db: Session) -> None:
    """Scans and indexes all files inside the project directory."""
    logger.info(f"Indexing project: {project.name} at {project.path}")
    parser = MasterParser()
    project_path = project.path

    # Track currently existing files on disk to remove deleted ones from db later
    files_on_disk = set()

    for dirpath, dirnames, filenames in os.walk(project_path, topdown=True):
        # Prune ignored folders in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS
            and not d.startswith(".")
            and not (d == "pkg" and os.path.basename(dirpath) == "go")
        ]

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if is_indexable_file(full_path):
                rel_path = os.path.relpath(full_path, project_path)
                files_on_disk.add(rel_path)
                index_file(full_path, project.id, rel_path, db, parser)

    # Delete File records for files that are no longer on disk
    indexed_files = db.query(File).filter(File.project_id == project.id).all()
    for file_record in indexed_files:
        if file_record.path not in files_on_disk:
            logger.info(f"File {file_record.path} no longer exists. Removing from index.")
            db.delete(file_record)
    
    db.commit()
