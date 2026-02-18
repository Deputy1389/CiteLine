import sys
import os

# Add project root to sys.path to allow importing from tools
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.pi_packet_gen.cli import main

if __name__ == "__main__":
    main()
