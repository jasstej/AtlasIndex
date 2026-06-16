import os
import shutil
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from atlasindex.storage.database import Base
from atlasindex.storage.models import Project, PortReservation, DomainConfig
from atlasindex.registry.ports import reserve_port, scan_project_ports
from atlasindex.registry.domains import parse_nginx_config, scan_system_domains

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session()
    try:
        # Seed mock project
        proj = Project(id="test-proj-id", name="TestProject", path="/tmp/test-project")
        session.add(proj)
        session.commit()
        yield session
    finally:
        session.close()

def test_port_reservation(db_session):
    # Test reserving a free port
    ports = reserve_port(db_session, "TestProject", 5001)
    assert len(ports) == 1
    assert ports[0] == 5001

    # Check reservation saved in DB
    res = db_session.query(PortReservation).filter(PortReservation.port == 5001).first()
    assert res is not None
    assert res.project_id == "test-proj-id"

    # Seed an occupied port for a different project
    other_proj = Project(id="other-proj-id", name="OtherProject", path="/tmp/other")
    db_session.add(other_proj)
    db_session.commit()
    
    # Reserve port 5001 for other project - should conflict and return alternatives
    alts = reserve_port(db_session, "OtherProject", 5001)
    assert len(alts) == 3
    assert 5001 not in alts
    assert alts == [5002, 5003, 5004]

def test_parse_nginx_config():
    # Write mock nginx file
    temp_dir = tempfile.mkdtemp()
    nginx_conf = os.path.join(temp_dir, "nginx.conf")
    with open(nginx_conf, "w") as f:
        f.write("""
server {
    listen 80;
    server_name myapp.test www.myapp.test;
    location / {
        proxy_pass http://127.0.0.1:3000;
    }
}
""")
    try:
        results = parse_nginx_config(nginx_conf)
        assert len(results) == 2
        domains = {r["domain"] for r in results}
        assert "myapp.test" in domains
        assert "www.myapp.test" in domains
        assert results[0]["ports"] == [3000]
    finally:
        shutil.rmtree(temp_dir)
