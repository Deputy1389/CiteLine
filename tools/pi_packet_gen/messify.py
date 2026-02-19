import os
import random
import io
from datetime import date, timedelta
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

class Messifier:
    def __init__(self, noise_level: str, seed: int = 42):
        self.noise_level = noise_level
        self.enabled = noise_level != "clean" and noise_level != "none"
        self.rnd = random.Random(seed)

    def messify_document(self, filepath: str, doc_date: date, anomalies: list = None):
        """Apply noise and fax header to a single document."""
        if not self.enabled:
            return

        # Determine effective noise level for this document
        doc_noise = self.noise_level
        if self.noise_level == "mixed":
            roll = self.rnd.random()
            if roll < 0.2: doc_noise = "clean"
            elif roll < 0.7: doc_noise = "light"
            else: doc_noise = "heavy"

        if doc_noise == "clean":
            return # Keep as pure digital PDF

        print(f"Messifying {os.path.basename(filepath)} ({doc_noise})...")
        
        try:
            reader = PdfReader(filepath)
            writer = PdfWriter()
            
            # Generate fax metadata
            fax_delay = self.rnd.randint(0, 14)
            fax_date = doc_date + timedelta(days=fax_delay)
            fax_ts = f"{fax_date.strftime('%m/%d/%Y')} {self.rnd.randint(8, 18):02d}:{self.rnd.randint(0, 59):02d}"
            fax_num = f"({self.rnd.randint(200, 999)}) {self.rnd.randint(100, 999)}-{self.rnd.randint(1000, 9999)}"
            fax_style = self.rnd.choice(["standard", "minimal", "server"])
            
            # Chance of fax header?
            # Heavy: 80%, Light: 40%
            add_fax = self.rnd.random() < (0.8 if doc_noise == "heavy" else 0.4)

            for i, page in enumerate(reader.pages):
                page_num = i + 1
                # 1. Rotation (Skew) - Simulate Scanning
                angle = 0
                if doc_noise == "light":
                    angle = self.rnd.uniform(-0.5, 0.5)
                elif doc_noise == "heavy":
                    angle = self.rnd.uniform(-2.0, 2.0)
                
                if angle != 0:
                    op = Transformation().rotate(angle)
                    page.add_transformation(op)
                    
                    # 2. Scale (Shrink to fit printable area often seen in scans)
                    scale = self.rnd.uniform(0.95, 0.99)
                    op_scale = Transformation().scale(scale, scale)
                    page.add_transformation(op_scale)

                # 3. Fax Header / Occlusion
                anomaly = None
                if anomalies:
                    from .schema import AnomalyType
                    for a in anomalies:
                        if a.type == AnomalyType.OCCLUSION and a.page_in_doc == page_num:
                            anomaly = a
                            break

                if add_fax or anomaly:
                    overlay_pdf = self._create_fax_overlay(fax_ts, fax_num, page_num, fax_style, anomaly)
                    overlay_page = PdfReader(overlay_pdf).pages[0]
                    page.merge_page(overlay_page)

                writer.add_page(page)

            # Overwrite file
            with open(filepath, "wb") as f:
                writer.write(f)
                
        except Exception as e:
            print(f"Error messifying {filepath}: {e}")

    def _create_fax_overlay(self, timestamp: str, fax_num: str, page_num: int, style: str, anomaly: any = None) -> io.BytesIO:
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        width, height = letter
        
        text = ""
        if style == "standard":
            text = f"{timestamp}  FROM: {fax_num}  TO: RECORDS DEPT  PAGE: {page_num:03d}"
        elif style == "minimal":
            text = f"{timestamp}   {fax_num}   P.{page_num}"
        elif style == "server":
            text = f"Fax ID: {self.rnd.randint(100000,999999)} | {timestamp} | Page {page_num}"
        
        can.setFont("Courier", 9 if style != "server" else 7)
        can.setFillColorRGB(0.1, 0.1, 0.1)
        
        # Position varies
        header_top = self.rnd.choice([True, False])
        if anomaly and anomaly.details["overlap_type"] == "FAX_HEADER":
            # Force overlap by placing header further in
            y = height - 100 if header_top else 100
            can.drawString(50, y, "--- FAX TRANSMISSION OVERLAP TEST --- " + text)
        else:
            if header_top:
                can.drawString(20, height - 15, text)
            else:
                can.drawString(20, 15, text)

        if anomaly and anomaly.details["overlap_type"] == "STAMP_RECEIVED":
            can.setFont("Helvetica-Bold", 40)
            can.setFillColorRGB(0.8, 0.2, 0.2, alpha=0.4)
            can.saveState()
            can.translate(width/2, height/2)
            can.rotate(30)
            can.drawCentredString(0, 0, "RECEIVED")
            can.restoreState()
            
        can.save()
        packet.seek(0)
        return packet
