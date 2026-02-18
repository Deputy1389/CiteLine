import unittest
import os
import shutil
import json
import hashlib
from tools.pi_packet_gen.casegen import CaseGenerator
from tools.pi_packet_gen.schema import PacketConfig, Archetype
from tools.pi_packet_gen.cli import main
import sys
from io import StringIO
from unittest.mock import patch

class TestPiPacketGen(unittest.TestCase):
    def setUp(self):
        self.output_dir = "output/test_gen_run"
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir)

    def tearDown(self):
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_determinism(self):
        """Verify that the same seed produces identical ground truth."""
        config = PacketConfig(
            archetype=Archetype.SOFT_TISSUE,
            target_pages=10,
            noise_level="none",
            seed=42
        )
        
        # Run 1
        gen1 = CaseGenerator(config)
        case1 = gen1.generate()
        gt1 = json.dumps(case1.ground_truth, sort_keys=True)
        
        # Run 2
        gen2 = CaseGenerator(config)
        case2 = gen2.generate()
        gt2 = json.dumps(case2.ground_truth, sort_keys=True)
        
        self.assertEqual(gt1, gt2, "Ground truth should be identical for same seed")
        
        # Verify specific content stability
        self.assertEqual(case1.patient.name, case2.patient.name)
        self.assertEqual(case1.incident_date, case2.incident_date)

    def test_schema_validity(self):
        """Verify generated structure matches expectations."""
        config = PacketConfig(
            archetype=Archetype.HERNIATION,
            target_pages=10,
            noise_level="none",
            seed=123
        )
        gen = CaseGenerator(config)
        case = gen.generate()
        gt = case.ground_truth
        
        required_keys = ["case_id", "seed", "archetype", "patient", "incident", "key_events"]
        for key in required_keys:
            self.assertIn(key, gt)
            
        self.assertEqual(gt["archetype"], "herniation")
        self.assertTrue(len(gt["imaging"]) > 0, "Herniation archetype should have imaging")
        
    def test_cli_execution(self):
        """Test full CLI flow."""
        test_args = [
            "generate_synth_pi_packet.py",
            "--archetype", "soft_tissue",
            "--pages", "5",
            "--seed", "999",
            "--out", self.output_dir
        ]
        
        with patch.object(sys, 'argv', test_args):
            # We import main inside to patch sys.argv, or patch it before calling
            # But here we are calling main() directly which uses argparse
            # Note: cli.py main() parses args.
            
            # Since main() is in cli.py, we need to import it. 
            # Note: In the test file imports, I imported 'main' from 'tools.pi_packet_gen.cli'.
            
            try:
                main()
            except SystemExit as e:
                self.assertEqual(e.code, 0)
                
        # Check outputs
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "packet.pdf")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "ground_truth.json")))
        self.assertTrue(os.path.exists(os.path.join(self.output_dir, "packet_index.json")))

if __name__ == '__main__':
    unittest.main()
