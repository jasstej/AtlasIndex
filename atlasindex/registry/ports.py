import re
import socket
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project, PortReservation

logger = logging.getLogger(__name__)

# Regex patterns to detect port declarations in files
PORT_PATTERNS = [
    # JS: app.listen(3000) or .listen(PORT)
    r"\.listen\(\s*(\d{4,5})\b",
    # Python: uvicorn.run(..., port=8000) or app.run(port=5000)
    r"\bport\s*=\s*(\d{4,5})\b",
    # Docker Compose: "8080:80" or "- 3000:3000"
    r"['\"]?(\d{4,5}):\d+['\"]?",
    # Dockerfile: EXPOSE 8080
    r"\bEXPOSE\s+(\d{4,5})\b"
]

def is_port_in_use_on_system(port: int) -> bool:
    """Checks if a port is currently bound by any active process on the machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        try:
            # Try to bind to the port on localhost.
            # If it succeeds, the port is free.
            s.bind(("127.0.0.1", port))
            return False
        except socket.error:
            # Bind failed, meaning the port is occupied
            return True

def scan_project_ports(project: Project, db: Session) -> List[int]:
    """
    Scans project source files for hardcoded port assignments,
    registers them in the database, and returns them.
    """
    detected_ports = set()
    project_path = project.path

    # Simple scan of indexable text files in project
    for root, dirs, files in os.walk(project_path):
        # Skip standard large/binary directories
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "venv"}]
        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() in {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", "dockerfile"}:
                file_path = os.path.join(root, filename)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    for pattern in PORT_PATTERNS:
                        for match in re.finditer(pattern, content):
                            port = int(match.group(1))
                            if 1024 <= port <= 65535:
                                detected_ports.add(port)
                except Exception as e:
                    logger.debug(f"Failed to scan file {file_path} for ports: {e}")

    # Register detected ports
    for port in detected_ports:
        # Check if already registered
        existing = db.query(PortReservation).filter(PortReservation.port == port).first()
        if not existing:
            res = PortReservation(
                project_id=project.id,
                port=port,
                source="code",
                status="active"
            )
            db.add(res)
        else:
            # If registered under a different project, we log a conflict warning
            if existing.project_id != project.id:
                logger.warning(f"Port conflict detected! Port {port} is used by {project.name} but reserved by project ID {existing.project_id}")
    
    db.commit()
    return list(detected_ports)

def reserve_port(db: Session, project_name: str, requested_port: Optional[int] = None) -> List[int]:
    """
    Attempts to reserve a port for a project.
    - If requested_port is provided and free, it is reserved and returned.
    - If not free (or not provided), it finds and returns the next 3 available ports.
    """
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise ValueError(f"Project '{project_name}' not found. Please register the project first.")

    # Get all ports registered in DB
    registered_ports = {r.port for r in db.query(PortReservation).all()}

    def is_port_busy(p: int) -> bool:
        return (p in registered_ports) or is_port_in_use_on_system(p)

    if requested_port:
        if not is_port_busy(requested_port):
            # Reserve it
            reservation = PortReservation(
                project_id=project.id,
                port=requested_port,
                source="manual",
                status="reserved"
            )
            db.add(reservation)
            db.commit()
            logger.info(f"Reserved port {requested_port} for project {project_name}")
            return [requested_port]
        else:
            logger.warning(f"Requested port {requested_port} is busy. Finding alternatives...")
            start_search = requested_port + 1
    else:
        # Default starting series for auto-allocation
        start_search = 3000

    # Find next 3 available ports
    alternatives = []
    current_port = start_search
    while len(alternatives) < 3 and current_port <= 65535:
        # Avoid common reserved ranges if we are search-allocating blindly
        if not is_port_busy(current_port):
            alternatives.append(current_port)
        current_port += 1

    return alternatives
# Helper import of os for directory walks
import os
