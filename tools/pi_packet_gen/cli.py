import argparse
import os
import json
from .schema import PacketConfig, Archetype
from .casegen import CaseGenerator
from .render import DocumentRenderer
from .merge import PacketMerger
from .messify import Messifier

def main():
    parser = argparse.ArgumentParser(description="Generate Synthetic PI PDF Packet")
    parser.add_argument("--archetype", type=str, choices=[e.value for e in Archetype], default="soft_tissue")
    parser.add_argument("--pages", type=int, default=50)
    parser.add_argument("--noise", type=str, choices=["none", "light", "heavy", "mixed"], default="none")
    parser.add_argument("--anomalies", type=str, choices=["none", "light", "heavy"], default="none")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    
    args = parser.parse_args()
    
    # Auto-anomaly level if mixed/heavy noise
    anomalies_level = args.anomalies
    if anomalies_level == "none" and args.noise in ["mixed", "heavy"]:
        anomalies_level = "light"

    config = PacketConfig(
        archetype=Archetype(args.archetype),
        target_pages=args.pages,
        noise_level=args.noise,
        anomalies_level=anomalies_level,
        seed=args.seed
    )
    
    print(f"Generating packet with Seed: {args.seed}, Archetype: {args.archetype}, Anomalies: {anomalies_level}")
    os.makedirs(args.out, exist_ok=True)
    
    # 1. Generate Case
    gen = CaseGenerator(config)
    case = gen.generate()
    
    # 2. Render Docs
    renderer = DocumentRenderer(args.out)
    renderer.render_case(case)
    
    # 2b. Messify (Optional - per document)
    if args.noise != "none":
        print(f"Applying {args.noise} noise to documents...")
        messy = Messifier(args.noise, seed=args.seed)
        docs_dir = os.path.join(args.out, "docs")
        for doc in case.documents:
            filepath = os.path.join(docs_dir, doc.filename)
            messy.messify_document(filepath, doc.date, doc.anomalies)
    
    # 3. Merge
    merger = PacketMerger(args.out)
    merger.merge(case)
    
    # 4. Export Ground Truth (again after merge to get mapped global pages)
    with open(os.path.join(args.out, "ground_truth.json"), "w") as f:
        json.dump(case.ground_truth, f, indent=2, default=str)
    
    # 3. Merge
    merger = PacketMerger(args.out)
    merger.merge(case)
    
    print(f"Success! Packet generated at {args.out}/packet.pdf")

if __name__ == "__main__":
    main()
