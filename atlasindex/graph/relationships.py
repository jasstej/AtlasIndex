import os
import networkx as nx
import json
import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project, File, Import, PortReservation, DomainConfig

logger = logging.getLogger(__name__)

def build_relationship_graph(db: Session) -> nx.DiGraph:
    """
    Builds a directed graph of all projects, files, ports, and domains
    and their interconnecting dependencies.
    """
    G = nx.DiGraph()

    # 1. Fetch all elements from DB
    projects = db.query(Project).all()
    files = db.query(File).all()
    imports = db.query(Import).all()
    ports = db.query(PortReservation).all()
    domains = db.query(DomainConfig).all()

    # Map file IDs and project IDs for rapid lookups
    file_map = {f.id: f for f in files}
    project_map = {p.id: p for p in projects}

    # Helper: get project name by file_id
    def get_project_name_for_file(file_id: int) -> str:
        f = file_map.get(file_id)
        if f:
            p = project_map.get(f.project_id)
            if p:
                return p.name
        return "Unknown"

    # Add Project nodes
    for p in projects:
        G.add_node(
            f"project:{p.name}",
            type="project",
            label=p.name,
            technologies=p.technologies or [],
            path=p.path
        )

    # Add File nodes and link them to their project
    for f in files:
        proj_name = get_project_name_for_file(f.id)
        G.add_node(
            f"file:{f.path}",
            type="file",
            label=os.path.basename(f.path),
            language=f.language,
            size=f.size,
            project=proj_name
        )
        G.add_edge(f"project:{proj_name}", f"file:{f.path}", relation="contains")

    # 2. Add Code-level Import dependencies
    # Map import targets to files in the same project or general third-party libraries
    # Simple heuristic: if import matches file path (minus ext), add a file dependency.
    # Group file paths by project to check internal imports
    project_files = {}
    for f in files:
        if f.project_id not in project_files:
            project_files[f.project_id] = []
        project_files[f.project_id].append(f)

    for imp in imports:
        source_file = file_map.get(imp.file_id)
        if not source_file:
            continue

        # Look for target file in same project
        target_name = imp.name
        # Match target_name against relative paths of files in same project
        # e.g., if import is "utils" and file is "src/utils.py"
        matched_target = None
        for f in project_files.get(source_file.project_id, []):
            f_base, _ = os.path.splitext(os.path.basename(f.path))
            f_rel_no_ext, _ = os.path.splitext(f.path)
            
            # Simple checks: does import name match file name or module path?
            if target_name == f_base or target_name.replace(".", "/") == f_rel_no_ext:
                matched_target = f
                break

        if matched_target:
            G.add_edge(f"file:{source_file.path}", f"file:{matched_target.path}", relation="imports")
        else:
            # Third party package node
            pkg_node = f"package:{target_name}"
            if not G.has_node(pkg_node):
                G.add_node(pkg_node, type="package", label=target_name)
            G.add_edge(f"file:{source_file.path}", pkg_node, relation="depends_on")

    # 3. Add Port & Service connections
    # Check if a project references a port reserved by another project
    # We can scan the files of a project for any mention of another project's port
    project_ports = {}
    for p in ports:
        if p.project_id not in project_ports:
            project_ports[p.project_id] = []
        project_ports[p.project_id].append(p.port)

    # Scan project files for other projects' ports references
    for proj in projects:
        # Scan for ports of all other projects
        for other_proj_id, other_ports in project_ports.items():
            if other_proj_id == proj.id:
                continue
            other_proj = project_map.get(other_proj_id)
            if not other_proj:
                continue

            for file_record in proj.files:
                file_full_path = os.path.join(proj.path, file_record.path)
                try:
                    with open(file_full_path, "r", errors="ignore") as f:
                        content = f.read()
                    for port in other_ports:
                        # Matches HTTP request or host string referencing port
                        if re.search(rf"\b{port}\b", content):
                            G.add_edge(
                                f"project:{proj.name}",
                                f"project:{other_proj.name}",
                                relation="calls_api",
                                port=port
                            )
                except Exception:
                    pass

    # 4. Add Domain configuration mapping
    for dom in domains:
        proj = project_map.get(dom.project_id)
        if proj:
            dom_node = f"domain:{dom.domain}"
            G.add_node(
                dom_node,
                type="domain",
                label=dom.domain,
                proxy=dom.proxy_type,
                ssl=dom.ssl_status
            )
            G.add_edge(dom_node, f"project:{proj.name}", relation="routes_to")

    return G

def export_to_json(G: nx.DiGraph) -> Dict[str, Any]:
    """Serializes graph to a D3.js force-directed compatible node/link JSON structure."""
    nodes = []
    for node, attrs in G.nodes(data=True):
        nodes.append({
            "id": node,
            **attrs
        })

    links = []
    for source, target, attrs in G.edges(data=True):
        links.append({
            "source": source,
            "target": target,
            **attrs
        })

    return {"nodes": nodes, "links": links}

def export_to_mermaid(G: nx.DiGraph) -> str:
    """Generates Mermaid flowchart representation of project and service nodes."""
    lines = ["flowchart TD"]
    
    # We only include project, domain, and package nodes for clean service visualization
    # unless file details are explicitly asked. This prevents overloading the diagram.
    nodes_included = set()
    for node, attrs in G.nodes(data=True):
        if attrs.get("type") in {"project", "domain", "package"}:
            label = attrs.get("label", node)
            node_id = node.replace(":", "_").replace(".", "_").replace("-", "_")
            
            if attrs.get("type") == "project":
                lines.append(f'    {node_id}["📦 {label}"]')
            elif attrs.get("type") == "domain":
                lines.append(f'    {node_id}["🌐 {label} ({attrs.get("proxy")})"]')
            else:
                lines.append(f'    {node_id}["📚 {label}"]')
            nodes_included.add(node)

    for u, v, attrs in G.edges(data=True):
        if u in nodes_included and v in nodes_included:
            u_id = u.replace(":", "_").replace(".", "_").replace("-", "_")
            v_id = v.replace(":", "_").replace(".", "_").replace("-", "_")
            rel = attrs.get("relation", "")
            if "port" in attrs:
                rel += f' (port {attrs["port"]})'
            lines.append(f'    {u_id} -->|"{rel}"| {v_id}')

    return "\n".join(lines)

def export_to_graphml(G: nx.DiGraph) -> str:
    """Exports graph as GraphML XML string."""
    # Convert sets/lists to JSON strings as GraphML does not support complex attributes
    H = G.copy()
    for n, attrs in H.nodes(data=True):
        for k, v in attrs.items():
            if isinstance(v, (list, set, dict)):
                H.nodes[n][k] = json.dumps(v)
    for u, v, attrs in H.edges(data=True):
        for k, v in attrs.items():
            if isinstance(v, (list, set, dict)):
                H.edges[u, v][k] = json.dumps(v)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".graphml", delete=False) as tmp:
        tmp_name = tmp.name
    
    try:
        nx.write_graphml(H, tmp_name)
        with open(tmp_name, "r") as f:
            xml_content = f.read()
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
            
    return xml_content

def export_to_cypher(G: nx.DiGraph) -> str:
    """Generates Neo4j Cypher loading queries to create all nodes and edges."""
    queries = []
    
    # Create nodes
    for node, attrs in G.nodes(data=True):
        node_id = node.replace(":", "_").replace(".", "_").replace("-", "_")
        ntype = attrs.get("type", "entity").capitalize()
        name = attrs.get("label", node)
        
        # Build property dictionary
        props = {"id": node, "name": name}
        for k, v in attrs.items():
            if k not in {"type", "label"}:
                props[k] = v
                
        # Cypher syntax helper
        props_str = ", ".join([f"{k}: {json.dumps(v)}" for k, v in props.items()])
        queries.append(f"MERGE ({node_id}:{ntype} {{{props_str}}})")

    # Create relationships
    for u, v, attrs in G.edges(data=True):
        u_id = u.replace(":", "_").replace(".", "_").replace("-", "_")
        v_id = v.replace(":", "_").replace(".", "_").replace("-", "_")
        rel = attrs.get("relation", "DEPENDS_ON").upper()
        
        props = {k: v for k, v in attrs.items() if k != "relation"}
        props_str = ""
        if props:
            props_str = " {" + ", ".join([f"{k}: {json.dumps(v)}" for k, v in props.items()]) + "}"
            
        queries.append(f"MERGE ({u_id})-[r:{rel}{props_str}]->({v_id})")

    return "\n".join(queries)
