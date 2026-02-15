import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from packages.db.database import get_session, init_db
from packages.db.models import Run, Matter, Firm, Artifact

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def init_database():
    init_db()

@pytest.fixture
def db_session():
    with get_session() as session:
        yield session

@pytest.fixture
def setup_run(db_session):
    firm = Firm(name="Test Firm API")
    db_session.add(firm)
    db_session.flush()
    matter = Matter(firm_id=firm.id, title="Test Matter API")
    db_session.add(matter)
    db_session.flush()
    run = Run(matter_id=matter.id, status="success")
    db_session.add(run)
    db_session.commit()
    return run.id

def test_invalid_artifact_type(setup_run):
    run_id = setup_run
    response = client.get(f"/runs/{run_id}/artifacts/exe")
    assert response.status_code == 400
    assert "Invalid artifact type" in response.json()["detail"]

def test_path_traversal(db_session, setup_run):
    run_id = setup_run
    
    # Insert malicious artifact record
    # Note: Using a path that definitely exists but is outside data dir
    # Windows: C:/Windows/System32/drivers/etc/hosts or just C:/Windows/win.ini
    # But we mocked the data dir to be "data" (relative) in the code usually?
    # The code uses env var DATA_DIR or "data".
    
    # Use a file we know exists but is outside data dir
    import os
    # C:\CiteLine\README.md is a good candidate
    malicious_path = os.path.abspath("README.md")
    
    artifact = Artifact(
        run_id=run_id,
        artifact_type="pdf", # Valid type
        storage_uri=malicious_path,
        sha256="fake",
        bytes=123
    )
    db_session.add(artifact)
    db_session.commit()
    
    response = client.get(f"/runs/{run_id}/artifacts/pdf")
    # Should get 404 because of path traversal check
    assert response.status_code == 404
