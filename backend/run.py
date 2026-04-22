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


@app.route("/")
def home():
    return "Backend is running"


@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# HEATMAP + REGION DETECTION
# -----------------------------
def generate_heatmap(path):
    img = cv2.imread(path)

    if img is None:
        return None, []

    # 🔥 resize for performance
    img = cv2.resize(img, (800, 800))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    diff = cv2.absdiff(gray, blur)

    norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    heatmap = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.6, heatmap, 0.4, 0)

    _, thresh = cv2.threshold(norm, 50, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        if cv2.contourArea(c) > 500:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append([int(x), int(y), int(w), int(h)])
            cv2.rectangle(overlay, (x, y), (x+w, y+h), (0,255,0), 2)

    return overlay, boxes


# -----------------------------
# AI STYLE DETECTION
# -----------------------------
def ai_detection(score, noise, sharpness):
    value = (score * 0.5) + (noise * 0.25) + (sharpness * 0.25)

    if value > 60:
        return "Likely manipulated"
    elif value > 35:
        return "Possibly manipulated"
    else:
        return "Likely original"


# -----------------------------
# ANALYZE
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "No file"}), 400

        path = os.path.join(UPLOAD_FOLDER, "upload.jpg")
        file.save(path)

        metadata = {}

        # -----------------------------
        # EXIF
        # -----------------------------
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f)

            for tag in tags:
                val = str(tags[tag])
                if len(val) < 200:  # 🔥 prevent huge metadata
                    metadata[tag] = val
        except:
            pass

        # -----------------------------
        # LOAD IMAGE SAFELY
        # -----------------------------
        try:
            image = Image.open(path).convert("RGB")

            # 🔥 resize large images (CRITICAL FIX)
            max_size = 1200
            image.thumbnail((max_size, max_size))
            image.save(path)

        except:
            return jsonify({"error": "Invalid image format"}), 400

        # -----------------------------
        # ELA
        # -----------------------------
        temp = path + "_c.jpg"
        image.save(temp, "JPEG", quality=90)

        compressed = Image.open(temp)
        diff = ImageChops.difference(image, compressed)

        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = "ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr) / (np.max(arr) + 1e-5)) * 100)

        # -----------------------------
        # FAST NOISE + SHARPNESS
        # -----------------------------
        img_cv = cv2.imread(path, 0)

        if img_cv is not None:
            noise = float(np.mean(cv2.absdiff(img_cv, cv2.GaussianBlur(img_cv,(5,5),0))))
            sharp = float(cv2.Laplacian(img_cv, cv2.CV_64F).var())
        else:
            noise = 0
            sharp = 0

        noise_n = min(100, noise / 2)
        sharp_n = min(100, sharp / 50)

        # -----------------------------
        # CONFIDENCE
        # -----------------------------
        confidence = int(min(100, score*0.4 + noise_n*0.3 + sharp_n*0.3))

        # -----------------------------
        # HEATMAP
        # -----------------------------
        heatmap_img, boxes = generate_heatmap(path)
        heatmap_file = "heatmap.jpg"

        if heatmap_img is not None:
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), heatmap_img)

        # -----------------------------
        # AI RESULT
        # -----------------------------
        ai = ai_detection(score, noise_n, sharp_n)

        return jsonify({
            "score": score,
            "confidence": confidence,
            "ela_result": ai,
            "metadata": metadata,
            "ela_image": f"{BASE_URL}/files/{ela_file}",
            "heatmap": f"{BASE_URL}/files/{heatmap_file}",
            "regions": boxes
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# PDF REPORT
# -----------------------------
@app.route("/api/report", methods=["POST"])
def report():
    try:
        data = request.json

        file_path = os.path.join(UPLOAD_FOLDER, "report.pdf")
        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()

        content = []
        content.append(Paragraph("PixelProof Report", styles["Title"]))
        content.append(Spacer(1, 10))
        content.append(Paragraph(f"Score: {data['score']}", styles["Normal"]))
        content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
        content.append(Paragraph(f"Result: {data['ela_result']}", styles["Normal"]))

        doc.build(content)

        return jsonify({
            "report": f"{BASE_URL}/files/report.pdf"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
