from datetime import datetime
import uuid
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from atlasindex.storage.database import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), unique=False, nullable=False, index=True)
    path = Column(String(1024), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    technologies = Column(JSON, nullable=True)  # List of strings e.g. ["python", "fastapi"]
    metadata_json = Column(JSON, nullable=True)  # Free-form additional metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    files = relationship("File", back_populates="project", cascade="all, delete-orphan")
    endpoints = relationship("ApiEndpoint", back_populates="project", cascade="all, delete-orphan")
    ports = relationship("PortReservation", back_populates="project", cascade="all, delete-orphan")
    domains = relationship("DomainConfig", back_populates="project", cascade="all, delete-orphan")
    docker_containers = relationship("DockerContainer", back_populates="project", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="project", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(1024), nullable=False, index=True)  # Relative to project path
    language = Column(String(50), nullable=False)
    size = Column(Integer, nullable=False)
    hash = Column(String(64), nullable=False)  # SHA-256 hash
    created_at = Column(DateTime, nullable=True)
    modified_at = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="files")
    functions = relationship("Function", back_populates="file", cascade="all, delete-orphan")
    classes = relationship("Class", back_populates="file", cascade="all, delete-orphan")
    imports = relationship("Import", back_populates="file", cascade="all, delete-orphan")
    endpoints = relationship("ApiEndpoint", back_populates="file", cascade="all, delete-orphan")


class Function(Base):
    __tablename__ = "functions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    parameters = Column(JSON, nullable=True)  # List of dictionaries: [{"name": "x", "type": "int"}]
    line_number = Column(Integer, nullable=False)
    docstring = Column(Text, nullable=True)

    # Relationships
    file = relationship("File", back_populates="functions")


class Class(Base):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    methods = Column(JSON, nullable=True)  # List of strings
    inheritance = Column(JSON, nullable=True)  # List of base class names
    line_number = Column(Integer, nullable=False)

    # Relationships
    file = relationship("File", back_populates="classes")


class Import(Base):
    __tablename__ = "imports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)  # Target of import e.g., 'requests'
    module = Column(String(255), nullable=True)  # Containing module e.g. 'requests.models'
    line_number = Column(Integer, nullable=False)

    # Relationships
    file = relationship("File", back_populates="imports")


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    method = Column(String(10), nullable=False)  # GET, POST, PUT, DELETE, etc.
    path = Column(String(1024), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)

    # Relationships
    project = relationship("Project", back_populates="endpoints")
    file = relationship("File", back_populates="endpoints")


class PortReservation(Base):
    __tablename__ = "port_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    port = Column(Integer, unique=True, nullable=False, index=True)
    source = Column(String(50), nullable=False)  # 'code', 'docker', 'manual'
    status = Column(String(50), nullable=False, default="reserved")  # 'active', 'reserved', 'historical'
    reserved_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="ports")


class DomainConfig(Base):
    __tablename__ = "domain_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    proxy_type = Column(String(50), nullable=False)  # 'nginx', 'apache', 'traefik', 'caddy'
    ssl_status = Column(Boolean, default=False)
    config_path = Column(String(1024), nullable=True)

    # Relationships
    project = relationship("Project", back_populates="domains")


class DockerContainer(Base):
    __tablename__ = "docker_containers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    container_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    image = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    exposed_ports = Column(JSON, nullable=True)  # List of mappings e.g. [{"host": 8080, "container": 80}]
    networks = Column(JSON, nullable=True)
    volumes = Column(JSON, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="docker_containers")


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # 'systemd', 'cron', 'pm2', 'supervisor'
    status = Column(String(50), nullable=False)
    command = Column(Text, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="services")
