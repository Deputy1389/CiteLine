
from reportlab.pdfgen import canvas

def create_multipage_pdf():
    c = canvas.Canvas("multipage_test.pdf")
    
    # Page 1: Clinical Note
    c.drawString(100, 750, "Medical Record - Progress Note")
    c.drawString(100, 730, "Date: 2023-01-01")
    c.drawString(100, 710, "Patient: Test Patient")
    c.drawString(100, 690, "Assessment: Hypertension")
    c.showPage()
    
    # Page 2: Continuation (no explicit date, or same date)
    c.drawString(100, 750, "Medical Record - Progress Note")
    c.drawString(100, 730, "Plan: Continue meds.")
    c.showPage()
    
    # Page 3: Imaging
    c.drawString(100, 750, "Radiology Report - MRI Brain")
    c.drawString(100, 730, "Date: 2023-01-01")
    c.drawString(100, 710, "Findings: Normal.")
    c.showPage()
    
    c.save()
    print("Created multipage_test.pdf")

if __name__ == "__main__":
    create_multipage_pdf()
