import subprocess
import random
import os
from concurrent.futures import ThreadPoolExecutor

ARCHETYPES = ["soft_tissue", "herniation", "surgical", "complex_prior", "minor"]
NOISE_LEVELS = ["none", "light", "heavy", "mixed"]
ANOMALY_LEVELS = ["none", "light", "heavy"]

def generate_packet(index):
    archetype = random.choice(ARCHETYPES)
    noise = random.choice(NOISE_LEVELS)
    anomalies = random.choice(ANOMALY_LEVELS)
    pages = random.randint(40, 500)
    seed = 1000 + index
    out_dir = f"./packetintake/batch_{index:03d}_{archetype}"
    
    if os.path.exists(out_dir):
        print(f"Skipping Batch {index:03d}: {out_dir} already exists.")
        return f"Batch {index:03d} Skipped"
    
    cmd = [
        "python", "-m", "tools.pi_packet_gen.cli",
        "--archetype", archetype,
        "--noise", noise,
        "--anomalies", anomalies,
        "--pages", str(pages),
        "--seed", str(seed),
        "--out", out_dir
    ]
    
    print(f"Starting batch {index:03d}: {archetype}, {pages} pages, noise={noise}")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return f"Batch {index:03d} Success"
    except subprocess.CalledProcessError as e:
        return f"Batch {index:03d} Failed: {e.stderr}"

def main():
    os.makedirs("packetintake", exist_ok=True)
    # Use 4 workers to speed up generation without totally pinning the CPU
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(generate_packet, range(11, 101)))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
