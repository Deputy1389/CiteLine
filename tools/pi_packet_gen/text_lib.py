import random

class TextLibrary:
    def __init__(self, seed: int):
        self.rnd = random.Random(seed)

    def get_pt_narrative(self, pain_score: int, trend: str) -> str:
        templates = [
            "Patient demonstrates {guarding} during therapeutic exercises.",
            "Tolerance to treatment is {tolerance}.",
            "Noted {spasm} after activities.",
            "Patient reports {sleep} since last visit.",
            "Compliance with HEP (Home Exercise Program) is {compliance}."
        ]
        
        guarding = "significant guarding" if pain_score > 6 else "mild guarding" if pain_score > 3 else "minimal guarding"
        tolerance = "poor" if pain_score > 7 else "fair" if pain_score > 4 else "good"
        spasm = "increased paraspinal spasm" if pain_score > 5 else "slight muscle tension"
        sleep = "improved sleep" if trend == "improving" else "disturbed sleep due to pain"
        compliance = "excellent" if self.rnd.random() > 0.3 else "limited"

        narratives = []
        # Deterministically select 2-3 templates
        selected_indices = sorted(self.rnd.sample(range(len(templates)), self.rnd.randint(2, 3)))
        for i in selected_indices:
            narratives.append(templates[i].format(
                guarding=guarding, tolerance=tolerance, spasm=spasm, sleep=sleep, compliance=compliance
            ))
        
        return " ".join(narratives)

    def get_ortho_hpi_segment(self, symptom: str) -> str:
        segments = {
            "radicular": "Patient continues to experience sharp, radiating pain into the upper extremity consistent with nerve root irritation.",
            "headache": "Intermittent cervicogenic headaches remain a significant concern for the patient, occurring 3-4 times per week.",
            "spasm": "Physical examination reveals persistent hypertonicity and spasm in the cervical paraspinal musculature.",
            "sleep": "Sleep remains non-restorative due to inability to find a comfortable position."
        }
        return segments.get(symptom, "Patient's clinical presentation remains consistent with previous evaluation.")
