from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, json, hashlib
from datetime import datetime

from PIL import Image, ImageChops, ImageEnhance

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# HASH FUNCTION
# -----------------------------
def generate_file_hash(path):
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

# -----------------------------
# EXPLANATIONS
# -----------------------------
def explain(score):
    if score > 70:
        return {
            "simple": "Strong signs of manipulation detected.",
            "technical": "High pixel inconsistency and compression anomalies detected across multiple regions.",
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
# ANALYSIS
# -----------------------------
def analyze_image(path, job_id):

    image = Image.open(path).convert("RGB")

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
# PDF REPORT
# -----------------------------
def generate_pdf(job_id, data):
    path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

    doc = SimpleDocTemplate(path)
    styles = getSampleStyleSheet()

    content = []

    # Title
    content.append(Paragraph("Digital Image Forensic Analysis Report", styles["Title"]))
    content.append(Spacer(1, 12))

    # Summary
    content.append(Paragraph("<b>1. Analysis Summary</b>", styles["Heading2"]))
    content.append(Paragraph(f"Result: {data['analysis']}", styles["Normal"]))
    content.append(Paragraph(f"Score: {data['score']} / 100", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
    content.append(Spacer(1, 12))

    # Score Interpretation
    content.append(Paragraph("<b>2. Score Interpretation</b>", styles["Heading2"]))

    if data["score"] > 70:
        score_text = "High irregularity indicating likely manipulation."
    elif data["score"] > 40:
        score_text = "Moderate irregularities; possible editing or recompression."
    else:
        score_text = "Image appears structurally consistent."

    content.append(Paragraph(score_text, styles["Normal"]))
    content.append(Spacer(1, 12))

    # Methodology
    content.append(Paragraph("<b>3. Methodology</b>", styles["Heading2"]))
    content.append(Paragraph(
        "Error Level Analysis (ELA) evaluates compression consistency across an image. Edited regions often show different compression behavior.",
        styles["Normal"]
    ))
    content.append(Spacer(1, 12))

    # Technical
    content.append(Paragraph("<b>4. Technical Findings</b>", styles["Heading2"]))
    content.append(Paragraph(data["technical_explanation"], styles["Normal"]))
    content.append(Spacer(1, 12))

    # Confidence
    content.append(Paragraph("<b>5. Confidence Assessment</b>", styles["Heading2"]))
    content.append(Paragraph(data["confidence_note"], styles["Normal"]))
    content.append(Spacer(1, 12))

    # Metadata
    content.append(Paragraph("<b>6. Metadata</b>", styles["Heading2"]))
    if data["metadata"]["available"]:
        for k, v in list(data["metadata"]["all"].items())[:10]:
            content.append(Paragraph(f"{k}: {v}", styles["Normal"]))
    else:
        content.append(Paragraph("No metadata available.", styles["Normal"]))
    content.append(Spacer(1, 12))

    # GPS
    content.append(Paragraph("<b>7. GPS Data</b>", styles["Heading2"]))
    if data["gps"]:
        content.append(Paragraph(f"Latitude: {data['gps']['lat']}", styles["Normal"]))
        content.append(Paragraph(f"Longitude: {data['gps']['lon']}", styles["Normal"]))
    else:
        content.append(Paragraph("No GPS data available.", styles["Normal"]))
    content.append(Spacer(1, 12))

    # Integrity Section
    content.append(Paragraph("<b>8. Forensic Integrity</b>", styles["Heading2"]))
    content.append(Paragraph(f"Timestamp: {data['integrity']['timestamp']}", styles["Normal"]))
    content.append(Paragraph(f"Dimensions: {data['integrity']['width']} x {data['integrity']['height']}", styles["Normal"]))
    content.append(Paragraph(f"File Size: {data['integrity']['file_size']} bytes", styles["Normal"]))
    content.append(Paragraph(f"SHA-256 Hash: {data['integrity']['hash']}", styles["Normal"]))
    content.append(Spacer(1, 12))

    content.append(Paragraph(
        "This hash uniquely identifies the analyzed file. Any change to the file will produce a different hash.",
        styles["Normal"]
    ))
    content.append(Spacer(1, 12))

    # Conclusion
    content.append(Paragraph("<b>9. Conclusion</b>", styles["Heading2"]))
    content.append(Paragraph(data["legal_explanation"], styles["Normal"]))

    doc.build(content)

    return f"{BASE_URL}/files/{job_id}_report.pdf"

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():

    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No file"}), 400

    metadata = json.loads(request.form.get("metadata", "{}"))
    gps = json.loads(request.form.get("gps", "null"))

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id + ".jpg")
    file.save(path)

    # Integrity data
    file_hash = generate_file_hash(path)
    image = Image.open(path)
    width, height = image.size
    file_size = os.path.getsize(path)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

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
        "heatmap": f"{BASE_URL}/files/{heatmap}",
        "integrity": {
            "hash": file_hash,
            "timestamp": timestamp,
            "width": width,
            "height": height,
            "file_size": file_size
        }
    }

    result_data["pdf_report"] = generate_pdf(job_id, result_data)

    return jsonify({"status": "done", "result": result_data})

# -----------------------------
# FILE SERVING
# -----------------------------
@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# HEALTH
# -----------------------------
@app.route("/health")
def health():
    return {"status": "ok"}
