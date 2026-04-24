from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid

from PIL import Image, ImageChops, ImageEnhance
import piexif

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# METADATA + GPS
# -----------------------------
def extract_metadata_and_gps(path):
    try:
        img = Image.open(path)
        exif_data = img.info.get("exif")

        metadata = {"available": False, "all": {}}
        gps = None

        if not exif_data:
            print("❌ No EXIF found in file")
            return metadata, gps

        exif_dict = piexif.load(exif_data)
        metadata["available"] = True

        for ifd in exif_dict:
            for tag in exif_dict[ifd]:
                try:
                    name = piexif.TAGS[ifd][tag]["name"]
                    metadata["all"][name] = str(exif_dict[ifd][tag])
                except:
                    pass

        gps_ifd = exif_dict.get("GPS", {})

        if gps_ifd:
            def convert(coord):
                try:
                    d = coord[0][0]/coord[0][1]
                    m = coord[1][0]/coord[1][1]
                    s = coord[2][0]/coord[2][1]
                    return d + m/60 + s/3600
                except:
                    return None

            lat = convert(gps_ifd.get(piexif.GPSIFD.GPSLatitude))
            lon = convert(gps_ifd.get(piexif.GPSIFD.GPSLongitude))

            if lat and lon:
                if gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef) == b'S':
                    lat = -lat
                if gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef) == b'W':
                    lon = -lon

                gps = {"lat": lat, "lon": lon}

        return metadata, gps

    except Exception as e:
        print("EXIF ERROR:", e)
        return {"available": False}, None

# -----------------------------
# EXPLANATIONS
# -----------------------------
def explain(score):
    if score > 70:
        return {
            "simple": "Strong signs of manipulation detected.",
            "technical": "High pixel inconsistency and compression anomalies.",
            "legal": "Significant irregularities indicate likely digital alteration.",
            "confidence_note": "High confidence."
        }
    elif score > 40:
        return {
            "simple": "Possible editing detected.",
            "technical": "Moderate inconsistencies in compression.",
            "legal": "Moderate anomalies suggest possible editing or recompression.",
            "confidence_note": "Moderate confidence."
        }
    else:
        return {
            "simple": "Image appears original.",
            "technical": "Pixel structure is consistent.",
            "legal": "No significant irregularities detected.",
            "confidence_note": "High confidence in authenticity."
        }

# -----------------------------
# PDF REPORT
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
    mean = sum(pixels)/len(pixels)

    score = int((mean/255)*100)
    confidence = score

    result = (
        "Likely edited" if score > 70 else
        "Possibly edited" if score > 40 else
        "Likely original"
    )

    exp = explain(score)

    heat = ela.convert("RGB")
    heat = ImageEnhance.Color(heat).enhance(3)
    heat = ImageEnhance.Contrast(heat).enhance(2)

    heat_file = f"{job_id}_heatmap.jpg"
    heat.save(os.path.join(UPLOAD_FOLDER, heat_file))

    return score, confidence, result, exp, heat_file

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():

    file = request.files.get("image")
    if not file:
        return {"error":"No file"},400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id + ".jpg")
    file.save(path)

    score, confidence, result, exp, heat = analyze_image(path, job_id)
    metadata, gps = extract_metadata_and_gps(path)

    result_data = {
        "analysis": result,
        "score": score,
        "confidence": confidence,
        "simple_explanation": exp["simple"],
        "technical_explanation": exp["technical"],
        "legal_explanation": exp["legal"],
        "confidence_note": exp["confidence_note"],
        "metadata": metadata,
        "gps": gps,
        "heatmap": f"{BASE_URL}/files/{heat}"
    }

    result_data["pdf_report"] = generate_pdf(job_id, result_data)

    return jsonify({"status":"done","result":result_data})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return {"status":"ok"}
