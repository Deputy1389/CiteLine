import pytest
import time
from datetime import datetime, timedelta, timezone
from packages.db.database import get_session, init_db
from packages.db.models import Run, Matter, Firm
from apps.worker.runner import claim_run, STALE_THRESHOLD_MINUTES

@pytest.fixture(scope="session", autouse=True)
def init_database():
    init_db()

@pytest.fixture
def db_session():
    with get_session() as session:
        yield session

@pytest.fixture
def setup_data(db_session):
    # Create firm and matter
    firm = Firm(name="Test Firm")
    db_session.add(firm)
    db_session.flush()
    
    matter = Matter(firm_id=firm.id, title="Test Matter")
    db_session.add(matter)
    db_session.flush()
    
    db_session.commit()
    return matter.id

def test_atomic_claim(db_session, setup_data):
    matter_id = setup_data
    
    # Create 2 pending runs
    run1 = Run(matter_id=matter_id, status="pending", config_json="{}")
    run2 = Run(matter_id=matter_id, status="pending", config_json="{}")
    db_session.add(run1)
    db_session.add(run2)
    db_session.commit()
    
    # Claim first
    cid1 = claim_run()
    assert cid1 == run1.id
    
    # Verify status
    r1 = db_session.query(Run).get(run1.id)
    assert r1.status == "running"
    assert r1.worker_id is not None
    assert r1.claimed_at is not None
    
    # Claim second
    cid2 = claim_run()
    assert cid2 == run2.id
    
    # Claim third (should be None)
    cid3 = claim_run()
    assert cid3 is None

def test_stale_recovery(db_session, setup_data):
    matter_id = setup_data
    
    # Create a stale run
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES + 5)
    run_stale = Run(
        matter_id=matter_id, 
        status="running", 
        config_json="{}",
        worker_id="old_worker",
        heartbeat_at=stale_time
    )
    db_session.add(run_stale)
    db_session.commit()
    
    # Claim should pick it up
    cid = claim_run()
    assert cid == run_stale.id
    
    # Verify it updated worker_id and heartbeat
    r = db_session.query(Run).get(run_stale.id)
    assert r.worker_id != "old_worker"
    # Allow for naive/aware mismatch by normalizing
    r_hb = r.heartbeat_at.replace(tzinfo=timezone.utc) if r.heartbeat_at.tzinfo is None else r.heartbeat_at
    assert r_hb > stale_time
