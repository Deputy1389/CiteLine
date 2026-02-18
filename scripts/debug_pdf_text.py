from pdfminer.high_level import extract_text
text = extract_text("c:/CiteLine/data/mimic_demo/pdfs/Patient_100001.pdf")
print("--- START PDF TEXT ---")
print(text)
print("--- END PDF TEXT ---")
