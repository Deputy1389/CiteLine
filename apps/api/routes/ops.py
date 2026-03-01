"""
API route: Operations & Cockpit
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from packages.db.database import get_db
from packages.db.models import OpsEvent, Incident, SalesEvent, Run, Firm, SystemConfig
from packages.shared.utils.ops_utils import generate_fingerprint, calculate_impact_score

router = APIRouter(tags=["ops"])

class CreateOpsEventRequest(BaseModel):
    source: str
    stage: str
    severity: str
    message: str
    firm_id: Optional[str] = None
    matter_id: Optional[str] = None
    run_id: Optional[str] = None
    payload: Optional[dict] = None
    error_details: Optional[dict] = None

class CreateSalesEventRequest(BaseModel):
    lead_id: Optional[str] = None
    firm_name: Optional[str] = None
    domain: Optional[str] = None
    email: Optional[str] = None
    stage: str # scraped | demo_run | email_sent | trial_started | converted_to_paid
    status: str # success | failure
    run_id: Optional[str] = None
    error_details: Optional[dict] = None

@router.post("/ops/events")
async def create_ops_event(req: CreateOpsEventRequest, db: Session = Depends(get_db)):
    fingerprint = generate_fingerprint(req.message, req.stage)
    
    # 1. Create the raw event
    event = OpsEvent(
        source=req.source,
        stage=req.stage,
        severity=req.severity,
        fingerprint=fingerprint,
        message=req.message,
        firm_id=req.firm_id,
        matter_id=req.matter_id,
        run_id=req.run_id,
        payload_json=req.payload,
        error_json=req.error_details
    )
    db.add(event)
    
    # 2. Update or create the incident
    incident = db.query(Incident).filter(Incident.fingerprint == fingerprint).first()
    if not incident:
        incident = Incident(
            fingerprint=fingerprint,
            severity=req.severity,
            status="OPEN",
            occurrence_count_24h=1
        )
        db.add(incident)
        db.flush()
    else:
        incident.occurrence_count_24h += 1
        incident.last_seen_at = datetime.now(timezone.utc)
        if incident.status == "FIXED":
            incident.status = "OPEN" # Re-open if it was fixed
    
    # 3. Recalculate impact score
    firm_status = "unknown"
    if req.firm_id:
        firm = db.query(Firm).filter(Firm.id == req.firm_id).first()
        if firm:
            firm_status = firm.status
            
    incident.impact_score = calculate_impact_score(
        frequency=incident.occurrence_count_24h,
        firm_status=firm_status
    )
    
    db.commit()
    return {"status": "ok", "fingerprint": fingerprint, "incident_id": incident.id}

@router.get("/admin/cockpit/summary")
async def get_cockpit_summary(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    
    # Runs summary
    total_runs = db.query(Run).filter(Run.created_at >= last_24h).count()
    success_runs = db.query(Run).filter(Run.created_at >= last_24h, Run.status == "success").count()
    failed_runs = db.query(Run).filter(Run.created_at >= last_24h, Run.status.in_(["failed", "partial"])).count()
    
    export_success_rate = 0.0
    if (success_runs + failed_runs) > 0:
        export_success_rate = (success_runs / (success_runs + failed_runs)) * 100
        
    # Incidents summary
    open_incidents_count = db.query(Incident).filter(Incident.status == "OPEN").count()
    top_incidents = db.query(Incident).filter(Incident.status == "OPEN").order_by(desc(Incident.impact_score)).limit(5).all()
    
    # Sales summary
    active_trials = db.query(Firm).filter(Firm.status == "trial").count()
    paid_firms = db.query(Firm).filter(Firm.status == "paid").count()
    
    return {
        "timestamp": now.isoformat(),
        "product_health": {
            "total_runs_24h": total_runs,
            "export_success_rate": round(export_success_rate, 1),
            "open_incidents": open_incidents_count
        },
        "top_incidents": [
            {
                "id": inc.id,
                "fingerprint": inc.fingerprint,
                "impact_score": inc.impact_score,
                "count_24h": inc.occurrence_count_24h,
                "last_seen": inc.last_seen_at.isoformat()
            } for inc in top_incidents
        ],
        "sales": {
            "active_trials": active_trials,
            "paid_firms": paid_firms
        }
    }

@router.post("/admin/ops/control")
async def update_system_config(key: str, value: Any, db: Session = Depends(get_db)):
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not config:
        config = SystemConfig(key=key, value_json=value)
        db.add(config)
    else:
        config.value_json = value
        config.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    return {"status": "ok", "key": key, "value": value}

@router.get("/admin/cockpit/snapshot")
async def get_cockpit_snapshot(db: Session = Depends(get_db)):
    summary = await get_cockpit_summary(db)
    
    # Generate JSON snapshot
    snapshot_json = {
        "ts": summary["timestamp"],
        "metrics": summary["product_health"],
        "top_incidents": summary["top_incidents"],
        "sales": summary["sales"]
    }
    
    # Write to files for CLI agents
    import json
    import os
    
    root_dir = os.getcwd()
    with open(os.path.join(root_dir, "OPS_SNAPSHOT.json"), "w", encoding="utf-8") as f:
        json.dump(snapshot_json, f, indent=2)
        
    # Generate Markdown snapshot
    md = [
        "# 🧭 Linecite Ops Snapshot",
        f"Generated: {summary['timestamp']}",
        "",
        "## 📊 Product Health",
        f"- **Export Success Rate**: {summary['product_health']['export_success_rate']}%",
        f"- **Runs (24h)**: {summary['product_health']['total_runs_24h']}",
        f"- **Open Incidents**: {summary['product_health']['open_incidents']}",
        "",
        "## 🟥 Top Open Incidents",
    ]
    
    if not summary["top_incidents"]:
        md.append("✅ No open incidents.")
    else:
        for inc in summary["top_incidents"]:
            md.append(f"- **{inc['fingerprint']}** (Impact: {inc['impact_score']}) - {inc['count_24h']} occurrences")
            
    md.extend([
        "",
        "## 💰 Sales Funnel",
        f"- **Active Trials**: {summary['sales']['active_trials']}",
        f"- **Paid Firms**: {summary['sales']['paid_firms']}",
        "",
        "## 🎯 Recommended Action",
    ])
    
    # Basic decision logic
    if summary["product_health"]["export_success_rate"] < 90:
        md.append("🚨 **CRITICAL**: Product stability below threshold. Halt scaling. Fix top incidents.")
    elif summary["product_health"]["open_incidents"] > 0:
        md.append("⚠️ **WARN**: Open incidents detected. Fix before next major outbound burst.")
    else:
        md.append("✅ **STABLE**: System healthy. Safe to scale outbound.")
        
    with open(os.path.join(root_dir, "OPS_SNAPSHOT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
        
    return {"status": "ok", "snapshot": snapshot_json}

@router.get("/admin/cockpit/war-mode")
async def get_war_mode(db: Session = Depends(get_db)):
    """
    Live stream of the last 50 bad events for the 'Red Room' feed.
    """
    events = db.query(OpsEvent).filter(
        OpsEvent.severity.in_(["error", "critical"])
    ).order_by(desc(OpsEvent.ts)).limit(50).all()
    
    return {
        "events": [
            {
                "id": ev.id,
                "ts": ev.ts.isoformat(),
                "source": ev.source,
                "stage": ev.stage,
                "fingerprint": ev.fingerprint,
                "message": ev.message,
                "firm_id": ev.firm_id,
                "run_id": ev.run_id,
                "error_json": ev.error_json
            } for ev in events
        ]
    }

async def _check_kill_switch(db: Session):
    """
    Automated safety check: if demo success rate < threshold, pause outbound.
    """
    threshold_cfg = db.query(SystemConfig).filter(SystemConfig.key == "demo_success_threshold").first()
    threshold = float(threshold_cfg.value_json) if threshold_cfg else 90.0
    
    now = datetime.now(timezone.utc)
    last_2h = now - timedelta(hours=2)
    
    # Check demo success rate in last 2 hours
    total_demos = db.query(Run).filter(Run.created_at >= last_2h).count()
    if total_demos < 5: # Not enough sample
        return
        
    success_demos = db.query(Run).filter(Run.created_at >= last_2h, Run.status == "success").count()
    rate = (success_demos / total_demos) * 100
    
    if rate < threshold:
        # Auto-pause outbound
        pause_cfg = db.query(SystemConfig).filter(SystemConfig.key == "outbound_paused").first()
        if not pause_cfg:
            pause_cfg = SystemConfig(key="outbound_paused", value_json=True)
            db.add(pause_cfg)
        else:
            pause_cfg.value_json = True
            
        # Log the auto-pause event
        event = OpsEvent(
            source="system",
            stage="kill_switch",
            severity="critical",
            fingerprint="AUTO_KILL_SWITCH_TRIGGERED",
            message=f"Demo success rate {round(rate, 1)}% below threshold {threshold}%. Outbound paused."
        )
        db.add(event)
        db.commit()

@router.post("/sales/events")
async def create_sales_event(req: CreateSalesEventRequest, db: Session = Depends(get_db)):
    event = SalesEvent(
        lead_id=req.lead_id,
        firm_name=req.firm_name,
        domain=req.domain,
        email=req.email,
        stage=req.stage,
        status=req.status,
        run_id=req.run_id,
        error_json=req.error_details
    )
    db.add(event)
    db.commit()
    return {"status": "ok", "id": event.id}

@router.get("/admin/cockpit/sales-funnel")
async def get_sales_funnel(db: Session = Depends(get_db)):
    """
    Summary of the n8n sales funnel conversion.
    """
    stages = ["scraped", "demo_run", "email_sent", "trial_started", "converted_to_paid"]
    funnel = {}
    
    for stage in stages:
        success_count = db.query(SalesEvent).filter(SalesEvent.stage == stage, SalesEvent.status == "success").count()
        failure_count = db.query(SalesEvent).filter(SalesEvent.stage == stage, SalesEvent.status == "failure").count()
        funnel[stage] = {
            "success": success_count,
            "failure": failure_count
        }
        
    return {
        "funnel": funnel,
        "friction_map": [
            {
                "stage": stage,
                "failure_rate": round(funnel[stage]["failure"] / (funnel[stage]["success"] + funnel[stage]["failure"]) * 100, 1) if (funnel[stage]["success"] + funnel[stage]["failure"]) > 0 else 0.0
            } for stage in stages
        ]
    }

@router.get("/admin/cockpit/intelligence")
async def get_platform_intelligence(db: Session = Depends(get_db)):
    """
    Cross-firm platform intelligence with N>=25 rule for privacy & stat-sig.
    """
    # 1. Total volume across all firms
    total_cases = db.query(Run).count()
    if total_cases < 25:
        return {
            "status": "insufficient_data",
            "message": f"N={total_cases} < 25 threshold. Patterns hidden for privacy/stat-sig.",
            "total_cases": total_cases
        }
        
    # 2. CSI Distribution (simplified)
    # This is a placeholder for real CSI aggregation logic
    # In a real app, you'd query the event/run metrics_json
    csi_stats = {
        "avg_csi": 7.4, # Mocked for intelligence layer structure
        "sample_size": total_cases
    }
    
    # 3. Top Defense Vulnerability Fingerprints
    # This is also simplified to show the structure
    vulnerabilities = [
        {"fingerprint": "treatment_delay_30d+", "frequency": 0.42},
        {"fingerprint": "prior_similar_injury", "frequency": 0.38},
        {"fingerprint": "imaging_negative_soft_tissue", "frequency": 0.65}
    ]
    
    return {
        "status": "ok",
        "total_cases": total_cases,
        "signals": {
            "avg_csi": csi_stats["avg_csi"],
            "top_vulnerabilities": vulnerabilities,
            "injury_clusters": [
                {"category": "soft_tissue_neck", "count": 142},
                {"category": "orthopedic_shoulder", "count": 89},
                {"category": "neurological_tbi_mild", "count": 31}
            ]
        }
    }
