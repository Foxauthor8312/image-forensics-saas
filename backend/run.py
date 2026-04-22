from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import numpy as np
import cv2

from PIL import Image, ImageChops, ImageEnhance
import exifread

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"


# -----------------------------
# Utility functions
# -----------------------------

def analyze_noise(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    blur = cv2.GaussianBlur(img, (5, 5), 0)
    noise = cv2.absdiff(img, blur)
    return float(np.mean(noise))


def analyze_sharpness(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    laplacian = cv2.Laplacian(img, cv2.CV_64F)
    return float(laplacian.var())


# -----------------------------
# Routes
# -----------------------------

@app.route("/")
def home():
    return "Backend is running"


@app.route("/files/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# Analyze Image
# -----------------------------

@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")

    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    metadata = {}

    # -----------------------------
    # EXIF metadata
    # -----------------------------
    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f)

        for tag in tags:
            try:
                metadata[tag] = str(tags[tag])
            except:
                metadata[tag] = "Unreadable"

    except Exception as e:
        metadata["exif_error"] = str(e)

    # -----------------------------
    # PIL metadata
    # -----------------------------
    try:
        image = Image.open(filepath)
        metadata["Format"] = image.format
        metadata["Mode"] = image.mode
        metadata["Size"] = image.size

        if hasattr(image, "info"):
            for k, v in image.info.items():
                metadata[k] = str(v)

    except Exception as e:
        metadata["pil_error"] = str(e)

    # -----------------------------
    # ELA
    # -----------------------------
    try:
        original = Image.open(filepath).convert("RGB")

        temp_path = filepath + "_compressed.jpg"
        original.save(temp_path, "JPEG", quality=90)

        compressed = Image.open(temp_path)
        diff = ImageChops.difference(original, compressed)

        enhancer = ImageEnhance.Brightness(diff)
        ela_image = enhancer.enhance(10)

        ela_filename = os.path.basename(filepath) + "_ela.jpg"
        ela_path = os.path.join(UPLOAD_FOLDER, ela_filename)
        ela_image.save(ela_path)

        ela_array = np.array(ela_image)

        mean_diff = np.mean(ela_array)
        max_diff = np.max(ela_array)

        score = int((mean_diff / (max_diff + 1e-5)) * 100)

    except Exception as e:
        return jsonify({"error": f"ELA failed: {str(e)}"}), 500

    # -----------------------------
    # Additional analysis
    # -----------------------------
    noise_score = analyze_noise(filepath)
    sharpness_score = analyze_sharpness(filepath)

    noise_norm = min(100, noise_score / 2)
    sharpness_norm = min(100, sharpness_score / 50)

    # -----------------------------
    # Confidence scoring
    # -----------------------------
    confidence = (
        score * 0.4 +
        noise_norm * 0.3 +
        sharpness_norm * 0.3
    )

    if len(metadata) == 0:
        confidence += 10

    confidence = int(max(0, min(100, confidence)))

    # -----------------------------
    # Findings
    # -----------------------------
    findings = []

    if score > 50:
        findings.append("High compression inconsistencies (ELA)")

    if noise_norm > 40:
        findings.append("Noise pattern inconsistency detected")

    if sharpness_norm > 40:
        findings.append("Sharpness irregularities detected")

    if len(metadata) == 0:
        findings.append("Metadata missing or stripped")

    if not findings:
        findings.append("No strong forensic anomalies detected")

    # -----------------------------
    # Result classification
    # -----------------------------
    if confidence > 70:
        result = "Likely manipulated"
    elif confidence > 40:
        result = "Possibly manipulated"
    else:
        result = "No strong evidence of manipulation"

    # -----------------------------
    # Response
    # -----------------------------
    return jsonify({
        "score": score,
        "confidence": confidence,
        "ela_result": result,
        "metadata": metadata,
        "findings": findings,
        "ela_image": f"{BASE_URL}/files/{ela_filename}"
    })


# -----------------------------
# PDF Report
# -----------------------------

@app.route("/api/report", methods=["POST"])
def generate_report():
    data = request.json

    filename = "report.pdf"
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
    content.append(Spacer(1, 12))

    content.append(Paragraph(f"Score: {data['score']}", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
    content.append(Paragraph(f"Conclusion: {data['ela_result']}", styles["Normal"]))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Findings:", styles["Heading2"]))
    for f in data["findings"]:
        content.append(Paragraph(f"- {f}", styles["Normal"]))

    content.append(Spacer(1, 10))
    content.append(Paragraph("Metadata Summary:", styles["Heading2"]))

    for k, v in list(data.get("metadata", {}).items())[:15]:
        content.append(Paragraph(f"{k}: {v}", styles["Normal"]))

    doc.build(content)

    return jsonify({
        "report": f"{BASE_URL}/files/{filename}"
    })


# -----------------------------
# Run locally
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
