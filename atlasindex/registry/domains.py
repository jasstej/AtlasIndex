import re
import os
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from atlasindex.storage.models import Project, DomainConfig, PortReservation

logger = logging.getLogger(__name__)

# Typical configuration search directories for reverse proxies
PROXY_DIRS = {
    "nginx": ["/etc/nginx/sites-enabled", "/etc/nginx/sites-available", "/etc/nginx/conf.d"],
    "apache": ["/etc/apache2/sites-enabled", "/etc/httpd/conf.d"],
    "caddy": ["/etc/caddy"]
}

def parse_nginx_config(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses an Nginx config file to extract server_name and proxy_pass settings.
    """
    results = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        logger.debug(f"Failed to read nginx config {file_path}: {e}")
        return results

    # Simple regex for server blocks (could have multiple in one file)
    # We find server_name and proxy_pass within server context
    # Split content by 'server {'
    servers = content.split("server {")
    for block in servers[1:]:
        # Find server names
        server_names = []
        sn_match = re.search(r"\bserver_name\s+([^;]+);", block)
        if sn_match:
            # Split by whitespace, ignore wildcards or empty values
            names = sn_match.group(1).split()
            server_names = [n for n in names if n not in {"_", ""}]

        # Find proxy_pass targets and check for SSL
        proxy_ports = set()
        proxy_matches = re.finditer(r"\bproxy_pass\s+https?://(?:127\.0\.0\.1|localhost):(\d+)", block)
        for pm in proxy_matches:
            proxy_ports.add(int(pm.group(1)))

        listen_ssl = "listen 443" in block or "ssl" in block

        if server_names:
            for name in server_names:
                results.append({
                    "domain": name,
                    "proxy_type": "nginx",
                    "ssl_status": listen_ssl,
                    "ports": list(proxy_ports),
                    "config_path": file_path
                })
    return results

def parse_caddy_config(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses a Caddyfile to extract host block headers and reverse_proxy targets.
    """
    results = []
    # Simplified parsing for Caddyfile:
    # Look for lines containing "reverse_proxy" and lines defining site addresses
    # e.g., site.com { \n reverse_proxy localhost:8000 \n }
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        logger.debug(f"Failed to read caddy config {file_path}: {e}")
        return results

    current_domain = None
    ssl_status = False
    proxy_ports = set()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Look for site block header e.g. vulnforge.example.com {
        if line.endswith("{"):
            parts = line.split()
            if len(parts) >= 2:
                current_domain = parts[0]
                ssl_status = current_domain.startswith("https://") or ".local" not in current_domain
                proxy_ports = set()

        elif "reverse_proxy" in line:
            # extract port
            port_match = re.search(r"(?:127\.0\.0\.1|localhost):(\d+)", line)
            if port_match:
                proxy_ports.add(int(port_match.group(1)))

        elif line == "}":
            if current_domain:
                results.append({
                    "domain": current_domain.replace("https://", "").replace("http://", ""),
                    "proxy_type": "caddy",
                    "ssl_status": ssl_status,
                    "ports": list(proxy_ports),
                    "config_path": file_path
                })
                current_domain = None
                proxy_ports = set()

    return results

def scan_system_domains(db: Session, custom_configs: List[str] = None) -> List[DomainConfig]:
    """
    Scans typical system directories and custom configuration files for reverse proxies.
    Maps found domains to projects based on target proxy ports and updates DB.
    """
    logger.info("Scanning reverse proxy configurations for domain mappings...")
    parsed_domains = []

    # 1. Scan custom config paths (e.g. specific nginx config we have permission to read)
    if custom_configs:
        for path in custom_configs:
            if os.path.exists(path):
                if "nginx" in path or "sites" in path or "conf" in path:
                    parsed_domains.extend(parse_nginx_config(path))
                elif "Caddyfile" in path:
                    parsed_domains.extend(parse_caddy_config(path))

    # 2. Scan system folders if read access is permitted
    for proxy_type, paths in PROXY_DIRS.items():
        for path in paths:
            if os.path.exists(path):
                try:
                    if os.path.isdir(path):
                        for entry in os.scandir(path):
                            if entry.is_file():
                                if proxy_type == "nginx":
                                    parsed_domains.extend(parse_nginx_config(entry.path))
                                elif proxy_type == "caddy" and entry.name == "Caddyfile":
                                    parsed_domains.extend(parse_caddy_config(entry.path))
                    elif os.path.is_file(path):
                        if proxy_type == "caddy":
                            parsed_domains.extend(parse_caddy_config(path))
                except Exception as e:
                    logger.debug(f"Could not scan path {path} for proxy configs: {e}")

    # 3. Save to database and map to projects
    # Deduplicate parsed_domains by domain name to prevent duplicate entries in the same session
    deduped_domains = {}
    for pd in parsed_domains:
        domain_name = pd["domain"]
        if domain_name not in deduped_domains:
            deduped_domains[domain_name] = pd
        else:
            deduped_domains[domain_name]["ports"] = list(set(deduped_domains[domain_name]["ports"]).union(pd["ports"]))
    parsed_domains = list(deduped_domains.values())

    # Map project ports to projects first to perform quick lookups
    all_projects = db.query(Project).all()
    project_port_map = {}
    for proj in all_projects:
        # Find all port reservations or active ports registered for this project
        ports = {res.port for res in proj.ports}
        for port in ports:
            project_port_map[port] = proj

    domain_records = []
    for pd in parsed_domains:
        # Match domain to project based on target proxy ports
        matched_project = None
        for port in pd["ports"]:
            if port in project_port_map:
                matched_project = project_port_map[port]
                break

        if not matched_project:
            # Fallback: if no project port matches, associate with a default/unknown project
            # or skip. For robust registry, we associate with project by looking at common names.
            # E.g. search if project name is in domain name
            for proj in all_projects:
                if proj.name.lower() in pd["domain"].lower():
                    matched_project = proj
                    break

        if matched_project:
            # Add or update
            existing = db.query(DomainConfig).filter(DomainConfig.domain == pd["domain"]).first()
            if existing:
                existing.project_id = matched_project.id
                existing.proxy_type = pd["proxy_type"]
                existing.ssl_status = pd["ssl_status"]
                existing.config_path = pd["config_path"]
                domain_records.append(existing)
            else:
                domain_rec = DomainConfig(
                    project_id=matched_project.id,
                    domain=pd["domain"],
                    proxy_type=pd["proxy_type"],
                    ssl_status=pd["ssl_status"],
                    config_path=pd["config_path"]
                )
                db.add(domain_rec)
                domain_records.append(domain_rec)
        else:
            logger.info(f"Could not map domain {pd['domain']} to any project (proxied ports: {pd['ports']})")

    db.commit()
    return domain_records
