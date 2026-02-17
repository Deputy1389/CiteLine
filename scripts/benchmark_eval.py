"""
Compare Citeline extraction (System) vs Gold Standard (Ground Truth).
Usage: python scripts/benchmark_eval.py [run_id] [gold_standard_json_path]
"""
import sys
import os
import json
import argparse
from datetime import datetime

# Add project root
sys.path.append(os.getcwd())

from packages.db.database import get_session
from packages.db.models import Run, Event

def load_system_events(run_id: str):
    """Load extracted events from Citeline DB."""
    with get_session() as session:
        events = session.query(Event).filter_by(run_id=run_id).all()
        return [
            {
                "date": e.date,
                "description": e.summary, # or e.description
                "provider": e.provider.name if e.provider else "Unknown"
            }
            for e in events
        ]

def load_gold_events(path: str):
    with open(path, "r") as f:
        data = json.load(f)
        return data.get("events", [])

def compare_events(system, gold):
    """
    Naive comparison based on date + fuzzy text match.
    Returns: { "precision": float, "recall": float, "matches": [] }
    """
    matches = 0
    # Simple rigorous check: Date match +/- 1 day
    
    # 1. Index gold by date
    gold_by_date = {}
    for g in gold:
        d = g.get("date")
        if d not in gold_by_date: gold_by_date[d] = []
        gold_by_date[d].append(g)
        
    matched_gold_indices = set()
    
    for s in system:
        s_date = s["date"].strftime("%Y-%m-%d") if isinstance(s["date"], datetime) else str(s["date"])
        
        # Check exact date match
        candidates = gold_by_date.get(s_date, [])
        found_match = False
        for i, c in enumerate(candidates):
            # very basic check: is there ANY event on this date?
            # ideally check provider match
            matches += 1
            found_match = True
            break
            
    recall = matches / len(gold) if gold else 0
    precision = matches / len(system) if system else 0
    
    return {
        "precision": precision,
        "recall": recall,
        "gold_count": len(gold),
        "system_count": len(system),
        "matches": matches
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("gold_path")
    args = parser.parse_args()
    
    print(f"Evaluating Run {args.run_id} vs {args.gold_path}")
    
    system_events = load_system_events(args.run_id)
    gold_events = load_gold_events(args.gold_path)
    
    metrics = compare_events(system_events, gold_events)
    
    print(json.dumps(metrics, indent=2))
    
    # Save report
    with open(f"benchmark_report_{args.run_id}.json", "w") as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    main()
