from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, json

from PIL import Image, ImageChops, ImageEnhance

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# EXPLANATIONS
# -----------------------------
def explain(score):
    if score > 70:
        return {
            "simple": "Strong signs of manipulation detected.",
            "technical": "High pixel inconsistency and compression anomalies detected.",
            "legal": "Significant irregularities in pixel structure and compression patterns indicate likely digital alteration.",
            "confidence_note": "High confidence due to consistent anomaly patterns."
        }
    elif score > 40:
        return {
            "simple": "Possible editing detected.",
            "technical": "Moderate inconsistencies in compression and pixel distribution.",
            "legal": "Moderate anomalies suggest possible recompression or partial editing.",
            "confidence_note": "Moderate confidence due to partial anomaly distribution."
        }
    else:
        return {
            "simple": "Image appears original.",
            "technical": "Pixel structure and compression patterns are consistent.",
            "legal": "No material irregularities detected. Image appears consistent with original capture.",
            "confidence_note": "High confidence in authenticity."
        }

# -----------------------------
# PDF GENERATION
# -----------------------------
def generate_pdf(job_id, data):
    path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

    doc = SimpleDocTemplate(path)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("Digital Image Forensic Report", styles["Title"]))
    content.append(Spacer(1,12))

    content.append(Paragraph(f"Result: {data['analysis']}", styles["Normal"]))
    content.append(Paragraph(f"Score: {data['score']}", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
    content.append(Spacer(1,12))

    content.append(Paragraph("Summary", styles["Heading2"]))
    content.append(Paragraph(data["simple_explanation"], styles["Normal"]))

    content.append(Paragraph("Technical Findings", styles["Heading2"]))
    content.append(Paragraph(data["technical_explanation"], styles["Normal"]))

    content.append(Paragraph("Conclusion", styles["Heading2"]))
    content.append(Paragraph(data["legal_explanation"], styles["Normal"]))

    content.append(Paragraph("Confidence Statement", styles["Heading2"]))
    content.append(Paragraph(data["confidence_note"], styles["Normal"]))

    doc.build(content)

    return f"{BASE_URL}/files/{job_id}_report.pdf"

# -----------------------------
# IMAGE ANALYSIS
# -----------------------------
def analyze_image(path, job_id):

    image = Image.open(path).convert("RGB")

    # ELA
    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)

    gray = ela.convert("L")
    pixels = list(gray.getdata())
    mean_val = sum(pixels) / len(pixels)

    score = int((mean_val / 255) * 100)
    confidence = score

    result = (
        "Likely edited" if score > 70 else
        "Possibly edited" if score > 40 else
        "Likely original"
    )

    explanations = explain(score)

    # Heatmap
    heat = ela.convert("RGB")
    heat = ImageEnhance.Color(heat).enhance(3)
    heat = ImageEnhance.Contrast(heat).enhance(2)

    heat_file = f"{job_id}_heatmap.jpg"
    heat.save(os.path.join(UPLOAD_FOLDER, heat_file))

    return score, confidence, result, explanations, heat_file

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():

    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No file"}), 400

    # 🔥 Metadata from frontend
    metadata = json.loads(request.form.get("metadata", "{}"))
    gps = json.loads(request.form.get("gps", "null"))

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id + ".jpg")
    file.save(path)

    try:
        score, confidence, result, exp, heatmap = analyze_image(path, job_id)

        result_data = {
            "analysis": result,
            "score": score,
            "confidence": confidence,
            "simple_explanation": exp["simple"],
            "technical_explanation": exp["technical"],
            "legal_explanation": exp["legal"],
            "confidence_note": exp["confidence_note"],
            "metadata": {
                "available": bool(metadata),
                "all": metadata
            },
            "gps": gps,
            "heatmap": f"{BASE_URL}/files/{heatmap}"
        }

        # Generate PDF
        result_data["pdf_report"] = generate_pdf(job_id, result_data)

        return jsonify({
            "status": "done",
            "result": result_data
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"status": "error", "error": str(e)})

# -----------------------------
# FILE SERVING
# -----------------------------
@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# HEALTH CHECK
# -----------------------------
@app.route("/health")
def health():
    return {"status": "ok"}
