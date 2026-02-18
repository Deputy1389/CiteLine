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
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    
    args = parser.parse_args()
    
    valid_noise = ["none", "light", "heavy", "mixed"]
    if args.noise not in valid_noise:
        raise ValueError(f"Invalid noise level: {args.noise}. Must be one of {valid_noise}")
    
    config = PacketConfig(
        archetype=Archetype(args.archetype),
        target_pages=args.pages,
        noise_level=args.noise,
        seed=args.seed
    )
    
    print(f"Generating packet with Seed: {args.seed}, Archetype: {args.archetype}")
    os.makedirs(args.out, exist_ok=True)
    
    # 1. Generate Case
    gen = CaseGenerator(config)
    case = gen.generate()
    
    # Dump Ground Truth
    with open(os.path.join(args.out, "ground_truth.json"), "w") as f:
        json.dump(case.ground_truth, f, indent=2, default=str)
        
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
            messy.messify_document(filepath, doc.date)
    
    # 3. Merge
    merger = PacketMerger(args.out)
    merger.merge(case)
    
    print(f"Success! Packet generated at {args.out}/packet.pdf")

if __name__ == "__main__":
    main()
