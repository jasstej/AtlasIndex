import logging
import subprocess
import json
import os
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from atlasindex.storage.database import get_db, SessionLocal
from atlasindex.storage.models import Project, File, PortReservation, DomainConfig, Service, DockerContainer
from atlasindex.scanner.discovery import discover_projects
from atlasindex.indexer.core import index_project
from atlasindex.registry.ports import reserve_port, scan_project_ports
from atlasindex.registry.domains import scan_system_domains
from atlasindex.graph.relationships import build_relationship_graph, export_to_json, export_to_mermaid
from atlasindex.search.semantic import SemanticSearchEngine

logger = logging.getLogger(__name__)

router = APIRouter()
search_engine = SemanticSearchEngine()

# Request Pydantic Schemas
class ProjectRegister(BaseModel):
    path: str

class PortReserveRequest(BaseModel):
    project_name: str
    port: Optional[int] = None

# Background Task Helpers
def run_scan_and_index(project_path: str):
    db = SessionLocal()
    try:
        # 1. Discover projects in the path
        projects = discover_projects(project_path, db)
        for p in projects:
            # 2. Extract port definitions from code
            scan_project_ports(p, db)
            # 3. Index classes, functions, imports
            index_project(p, db)
            
        # 4. Rescan domains to map domain routing to projects
        # Pass the nginx config we have permission to read
        scan_system_domains(db, custom_configs=["/etc/nginx/sites-available/vulnforge-ip"])
        
        # 5. Build semantic index
        search_engine.build_index_from_db(db)
        logger.info("Background scanning and indexing completed successfully.")
    except Exception as e:
        logger.error(f"Error during background scan and index: {e}", exc_info=True)
    finally:
        db.close()


# --- PROJECTS ---

@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    return [{
        "id": p.id,
        "name": p.name,
        "path": p.path,
        "description": p.description,
        "technologies": p.technologies,
        "created_at": p.created_at,
        "updated_at": p.updated_at
    } for p in projects]

@router.post("/projects")
def register_project(payload: ProjectRegister, background_tasks: BackgroundTasks):
    path = os.path.abspath(payload.path)
    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="Target path does not exist on this machine.")

    background_tasks.add_task(run_scan_and_index, path)
    return {"message": "Project scan and indexing initiated in the background.", "path": path}

@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    files = db.query(File).filter(File.project_id == project.id).all()
    ports = db.query(PortReservation).filter(PortReservation.project_id == project.id).all()
    domains = db.query(DomainConfig).filter(DomainConfig.project_id == project.id).all()

    return {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "description": project.description,
        "technologies": project.technologies,
        "files_count": len(files),
        "ports": [{"port": p.port, "source": p.source, "status": p.status} for p in ports],
        "domains": [{"domain": d.domain, "proxy_type": d.proxy_type, "ssl": d.ssl_status} for d in domains],
        "created_at": project.created_at
    }

@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    
    db.delete(project)
    db.commit()
    return {"message": f"Project '{project.name}' successfully removed from registry."}


# --- PORTS REGISTRY ---

@router.get("/ports")
def list_ports(db: Session = Depends(get_db)):
    ports = db.query(PortReservation).all()
    results = []
    for p in ports:
        proj = db.query(Project).filter(Project.id == p.project_id).first()
        results.append({
            "port": p.port,
            "project_name": proj.name if proj else "Unknown",
            "source": p.source,
            "status": p.status,
            "reserved_at": p.reserved_at
        })
    # Sort by port number
    return sorted(results, key=lambda x: x["port"])

@router.post("/ports/reserve")
def allocate_port(payload: PortReserveRequest, db: Session = Depends(get_db)):
    try:
        ports = reserve_port(db, payload.project_name, payload.port)
        if len(ports) == 1 and ports[0] == payload.port:
            return {"status": "success", "message": f"Port {payload.port} successfully reserved.", "port": payload.port}
        else:
            return {
                "status": "conflict",
                "message": f"Requested port {payload.port} is busy or reserved.",
                "suggested_alternatives": ports
            }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- DOMAINS REGISTRY ---

@router.get("/domains")
def list_domains(db: Session = Depends(get_db)):
    domains = db.query(DomainConfig).all()
    results = []
    for d in domains:
        proj = db.query(Project).filter(Project.id == d.project_id).first()
        results.append({
            "domain": d.domain,
            "project_name": proj.name if proj else "Unknown",
            "proxy_type": d.proxy_type,
            "ssl_status": d.ssl_status,
            "config_path": d.config_path
        })
    return results


# --- SERVICE DISCOVERY ---

@router.get("/services")
def discover_services():
    """Queries system units (systemd, pm2, docker, supervisor) dynamically."""
    services = []

    # 1. systemd discovery
    try:
        res = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    services.append({
                        "name": parts[0].replace(".service", ""),
                        "type": "systemd",
                        "status": "running",
                        "description": " ".join(parts[4:]) if len(parts) > 4 else ""
                    })
    except Exception:
        pass

    # 2. PM2 discovery
    try:
        res = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            for proc in data:
                services.append({
                    "name": proc.get("name", "pm2-app"),
                    "type": "pm2",
                    "status": proc.get("pm2_env", {}).get("status", "unknown"),
                    "description": f"PM2 instance ID: {proc.get('pm_id')}"
                })
    except Exception:
        pass

    # 3. Docker Container discovery
    try:
        res = subprocess.run(
            ["docker", "ps", "--format", '{"id":"{{.ID}}", "name":"{{.Names}}", "status":"{{.Status}}", "ports":"{{.Ports}}", "image":"{{.Image}}"}'],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                if line:
                    c = json.loads(line)
                    services.append({
                        "name": c["name"],
                        "type": "docker",
                        "status": c["status"],
                        "description": f"Image: {c['image']} | Ports: {c['ports']}"
                    })
    except Exception:
        pass

    # 4. Supervisor discovery
    try:
        res = subprocess.run(["supervisorctl", "status"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    services.append({
                        "name": parts[0],
                        "type": "supervisor",
                        "status": parts[1].lower(),
                        "description": " ".join(parts[2:])
                    })
    except Exception:
        pass

    return services


# --- CODE SEARCH ---

@router.get("/search")
def code_search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    results = search_engine.search(q, db)
    return results

@router.post("/search/reindex")
def trigger_reindex(db: Session = Depends(get_db)):
    search_engine.build_index_from_db(db)
    return {"message": "Semantic search vector index rebuilt successfully."}


# --- RELATIONSHIP GRAPH ---

@router.get("/dependencies")
def get_dependencies_json(db: Session = Depends(get_db)):
    G = build_relationship_graph(db)
    return export_to_json(G)

@router.get("/graph")
def get_graph_mermaid(db: Session = Depends(get_db)):
    G = build_relationship_graph(db)
    mermaid_markup = export_to_mermaid(G)
    return {"mermaid": mermaid_markup}


# --- AI AGENT INTEGRATION LAYER ---

@router.get("/agent/project-context/{project_name}")
def get_project_context(project_name: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.name == project_name).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found.")

    files = db.query(File).filter(File.project_id == project.id).all()
    ports = db.query(PortReservation).filter(PortReservation.project_id == project.id).all()
    domains = db.query(DomainConfig).filter(DomainConfig.project_id == project.id).all()

    # Determine coding convention heuristics
    conventions = []
    if "python" in (project.technologies or []):
        conventions.append("PEP 8 Python styling, Pydantic data schemas, FastAPI route structures.")
    if "nodejs" in (project.technologies or []):
        conventions.append("ES6 JavaScript syntax, ESLint checks, package.json dependencies, Express handlers.")
    if "rust" in (project.technologies or []):
        conventions.append("Rust safe idioms, Cargo structures, snake_case functions.")

    # Service dependency linkages
    G = build_relationship_graph(db)
    outgoing_deps = []
    incoming_deps = []
    
    project_node = f"project:{project.name}"
    if G.has_node(project_node):
        for successor in G.successors(project_node):
            if successor.startswith("project:"):
                outgoing_deps.append(successor.replace("project:", ""))
        for predecessor in G.predecessors(project_node):
            if predecessor.startswith("project:"):
                incoming_deps.append(predecessor.replace("project:", ""))

    return {
        "project": project.name,
        "description": project.description,
        "path": project.path,
        "technologies": project.technologies,
        "architecture": {
            "ports_exposed": [p.port for p in ports],
            "domains_mapped": [d.domain for d in domains],
            "files_structure": [f.path for f in files[:25]],  # limit list size for readability
            "files_count": len(files)
        },
        "dependencies": {
            "depends_on_projects": outgoing_deps,
            "called_by_projects": incoming_deps
        },
        "coding_conventions": conventions
    }
