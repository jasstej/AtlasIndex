import os
import shutil
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from atlasindex.storage.database import Base
from atlasindex.scanner.discovery import discover_projects, detect_technologies_in_dir
from atlasindex.storage.models import Project

@pytest.fixture
def db_session():
    # Setup in-memory SQLite for testing
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def mock_codebase():
    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    
    # Create Python project
    py_dir = os.path.join(temp_dir, "py-app")
    os.makedirs(py_dir)
    with open(os.path.join(py_dir, "requirements.txt"), "w") as f:
        f.write("fastapi\n")
    
    # Create Node.js project inside a subfolder
    node_dir = os.path.join(temp_dir, "node-web")
    os.makedirs(node_dir)
    with open(os.path.join(node_dir, "package.json"), "w") as f:
        f.write('{"name": "test"}')

    # Create ignored folder (e.g. .git, venv)
    venv_dir = os.path.join(py_dir, "venv")
    os.makedirs(venv_dir)
    with open(os.path.join(venv_dir, "requirements.txt"), "w") as f:
        f.write("should-be-ignored\n")

    yield temp_dir
    
    # Cleanup
    shutil.rmtree(temp_dir)

def test_detect_technologies(mock_codebase):
    py_dir = os.path.join(mock_codebase, "py-app")
    node_dir = os.path.join(mock_codebase, "node-web")
    
    assert detect_technologies_in_dir(py_dir) == {"python"}
    assert detect_technologies_in_dir(node_dir) == {"nodejs"}

def test_discover_projects(mock_codebase, db_session):
    projects = discover_projects(mock_codebase, db_session)
    
    assert len(projects) == 2
    names = {p.name for p in projects}
    assert "py-app" in names
    assert "node-web" in names

    # Assert database state
    db_projects = db_session.query(Project).all()
    assert len(db_projects) == 2
    assert {p.name for p in db_projects} == {"py-app", "node-web"}

    # venv should be ignored
    venv_project = db_session.query(Project).filter(Project.name == "venv").first()
    assert venv_project is None

def test_extension_and_shebang_detection(mock_codebase, db_session):
    # Create an extensionless python script in a folder
    no_ext_dir = os.path.join(mock_codebase, "script-app")
    os.makedirs(no_ext_dir)
    script_path = os.path.join(no_ext_dir, "myrun")
    with open(script_path, "w") as f:
        f.write("#!/usr/bin/env python3\nprint('hello')\n")
        
    # Create a vanilla frontend folder with html/js
    frontend_dir = os.path.join(mock_codebase, "vanilla-web")
    os.makedirs(frontend_dir)
    with open(os.path.join(frontend_dir, "app.js"), "w") as f:
        f.write("console.log('hi');\n")
    with open(os.path.join(frontend_dir, "index.html"), "w") as f:
        f.write("<html></html>\n")

    # Create a documentation-only folder (should fallback to generic since it is a direct child)
    docs_dir = os.path.join(mock_codebase, "docs-folder")
    os.makedirs(docs_dir)
    with open(os.path.join(docs_dir, "README.md"), "w") as f:
        f.write("# Docs\n")

    # Verify technology detection
    assert "python" in detect_technologies_in_dir(no_ext_dir)
    assert "nodejs" in detect_technologies_in_dir(frontend_dir)
    assert "html" in detect_technologies_in_dir(frontend_dir)
    assert detect_technologies_in_dir(docs_dir) == set()  # No signature

    # Verify project discovery includes all of them
    projects = discover_projects(mock_codebase, db_session)
    names = {p.name for p in projects}
    assert "script-app" in names
    assert "vanilla-web" in names
    assert "docs-folder" in names

    from atlasindex.indexer.core import is_indexable_file
    assert is_indexable_file(script_path) is True
    assert is_indexable_file(os.path.join(docs_dir, "README.md")) is True
