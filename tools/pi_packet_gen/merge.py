import os
import io
import json
from pypdf import PdfReader, PdfWriter
from .schema import DocumentType

class PacketMerger:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        
    def merge(self, case):
        merger = PdfWriter()
        docs_dir = os.path.join(self.output_dir, "docs")
        index_data = []
        
        current_page = 1
        
        # Sort documents by date generally
        sorted_docs = sorted(case.documents, key=lambda d: d.date)
        
        for doc in sorted_docs:
            filepath = os.path.join(docs_dir, doc.filename)
            if not os.path.exists(filepath):
                continue
                
            # Read to get actual page count
            try:
                reader = PdfReader(filepath)
                page_count = len(reader.pages)
                merger.append(reader)
            except:
                page_count = 0
                continue
            
            date_str = doc.date.isoformat()
            if doc.doc_type == DocumentType.PACKET_NOISE:
                date_str = f"FAXED: {date_str}"
            
            index_data.append({
                "filename": doc.filename,
                "doc_type": doc.doc_type.value,
                "date": date_str,
                "start_page": current_page,
                "end_page": current_page + page_count - 1,
                "page_count": page_count
            })

            # Map global pages for anomalies
            for anomaly in doc.anomalies:
                anomaly.page_global = current_page + anomaly.page_in_doc - 1

            current_page += page_count
            
        outfile = os.path.join(self.output_dir, "packet.pdf")
        merger.write(outfile)
        merger.close()

        # Update ground truth with mapped global pages
        case.ground_truth["anomalies"] = [a.model_dump(mode='json') for a in case.anomalies]
        
        # Mapping Anchors to global pages (first page of matching doc)
        for anchor in case.ground_truth.get("expected_text_anchors", []):
            matching_entries = [e for e in index_data if e["doc_type"] == anchor["doc_type"]]
            if matching_entries:
                anchor["page_global"] = matching_entries[0]["start_page"]
        
        with open(os.path.join(self.output_dir, "packet_index.json"), "w") as f:
            json.dump(index_data, f, indent=2)


