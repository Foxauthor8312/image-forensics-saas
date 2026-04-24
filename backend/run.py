# --- ONLY SHOWING NEW/UPDATED PARTS ---

def build_legal_explanation(score, confidence):
    if confidence > 70:
        opinion = "The analysis indicates a high likelihood that the image has been digitally altered."
    elif confidence > 40:
        opinion = "The analysis identifies indicators that may be consistent with digital alteration, but findings are not conclusive."
    else:
        opinion = "The analysis does not identify strong indicators of digital alteration."

    explanation = (
        "This conclusion is based on a combination of compression analysis (ELA), "
        "noise distribution, and sharpness consistency across the image. "
        "Irregularities in these factors may indicate localized edits or manipulation."
    )

    limitations = [
        "Results are probabilistic and not definitive proof.",
        "Recompression (e.g., social media) may introduce artifacts.",
        "Low resolution images reduce reliability.",
        "This system does not identify exact edit methods."
    ]

    return {
        "opinion": opinion,
        "explanation": explanation,
        "confidence_text": f"Confidence level: {confidence}% based on combined forensic signals.",
        "limitations": limitations
    }
