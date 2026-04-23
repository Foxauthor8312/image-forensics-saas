from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading
import numpy as np
import cv2

from PIL import Image, ImageChops, ImageEnhance
import exifread

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"
jobs = {}

# -----------------------------
# GPS extraction
# -----------------------------
def get_gps_coords(tags):
    try:
        def convert(v):
            d = float(v.values[0].num) / float(v.values[0].den)
            m = float(v.values[1].num) / float(v.values[1].den)
            s = float(v.values[2].num) / float(v.values[2].den)
            return d + m/60 + s/3600

        lat = convert(tags["GPS GPSLatitude"])
        if tags["GPS GPSLatitudeRef"].values != "N":
            lat = -lat

        lon = convert(tags["GPS GPSLongitude"])
        if tags["GPS GPSLongitudeRef"].values != "E":
            lon = -lon

        return [lat, lon]
    except:
        return None


# -----------------------------
# WORKER
# -----------------------------
def process_job(job_id, path):
    try:
        metadata = {}
        gps = None

        # EXIF
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f)

            for tag in tags:
                val = str(tags[tag])
                if len(val) < 200:
                    metadata[tag] = val

            gps = get_gps_coords(tags)
        except:
            pass

        # Resize
        image = Image.open(path).convert("RGB")
        image.thumbnail((800, 800))
        image.save(path)

        # -----------------------------
        # ELA
        # -----------------------------
        temp = path + "_c.jpg"
        image.save(temp, "JPEG", quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela_path = os.path.join(UPLOAD_FOLDER, ela_file)
        ela.save(ela_path)

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # -----------------------------
        # CV ANALYSIS
        # -----------------------------
        img_cv = cv2.imread(path, 0)

        if img_cv is not None:
            noise = float(np.mean(cv2.absdiff(img_cv, cv2.GaussianBlur(img_cv,(5,5),0))))
            sharp = float(cv2.Laplacian(img_cv, cv2.CV_64F).var())
        else:
            noise = 0
            sharp = 0

        noise_n = min(100, noise/2)
        sharp_n = min(100, sharp/50)

        # -----------------------------
        # CONFIDENCE
        # -----------------------------
        ela_c = score * 0.4
        noise_c = noise_n * 0.3
        sharp_c = sharp_n * 0.3
        meta_c = 10 if len(metadata) == 0 else 0

        confidence = int(min(100, ela_c + noise_c + sharp_c + meta_c))

        # -----------------------------
        # SCORE EXPLANATION
        # -----------------------------
        if score < 10:
            score_explanation = (
                f"Score {score} indicates very low compression differences. "
                "This suggests uniform compression typical of original images."
            )
        elif score < 40:
            score_explanation = (
                f"Score {score} indicates moderate compression variation. "
                "This can result from recompression or light editing."
            )
        else:
            score_explanation = (
                f"Score {score} indicates high compression inconsistencies. "
                "This may suggest localized edits or compositing."
            )

        # -----------------------------
        # CONFIDENCE EXPLANATION
        # -----------------------------
        if confidence < 30:
            confidence_explanation = (
                f"Confidence {confidence}% is low. Signals are weak and do not strongly indicate manipulation."
            )
        elif confidence < 70:
            confidence_explanation = (
                f"Confidence {confidence}% is moderate. Some indicators exist, but evidence is not conclusive."
            )
        else:
            confidence_explanation = (
                f"Confidence {confidence}% is high. Multiple indicators strongly suggest manipulation."
            )

        # -----------------------------
        # RISK LEVEL
        # -----------------------------
        if confidence > 70:
            risk = "High"
        elif confidence > 40:
            risk = "Moderate"
        else:
            risk = "Low"

        # -----------------------------
        # LEGAL CONCLUSION
        # -----------------------------
        if confidence > 70:
            legal_conclusion = (
                "Based on the forensic analysis performed, there is a high degree of confidence that this image "
                "contains indicators consistent with digital manipulation or alteration. These findings are supported "
                "by multiple analytical signals."
            )
        elif confidence > 40:
            legal_conclusion = (
                "Based on the forensic analysis performed, there are observable indicators that may be consistent with "
                "image editing or recompression. However, these findings are not conclusive."
            )
        else:
            legal_conclusion = (
                "Based on the forensic analysis performed, there is no strong evidence to suggest that this image "
                "has been manipulated."
            )

        # -----------------------------
        # HEATMAP
        # -----------------------------
        heatmap_file = None
        regions = []

        try:
            img = cv2.imread(path)
            img = cv2.resize(img, (600,600))

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))

            norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)
            heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

            _,th = cv2.threshold(norm,50,255,cv2.THRESH_BINARY)
            cnts,_ = cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)

            for c in cnts:
                if cv2.contourArea(c)>500:
                    x,y,w,h = cv2.boundingRect(c)
                    regions.append([int(x),int(y),int(w),int(h)])
                    cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,255,0),2)

            heatmap_file = f"{job_id}_heatmap.jpg"
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        except:
            pass

        # -----------------------------
        # NARRATIVE
        # -----------------------------
        narrative = (
            "This image was analyzed using compression (ELA), noise consistency, and sharpness variation. "
        )

        if confidence > 70:
            narrative += "Strong indicators of manipulation were detected."
        elif confidence > 40:
            narrative += "Moderate anomalies were detected that may indicate editing."
        else:
            narrative += "No strong evidence of manipulation was detected."

        # -----------------------------
        # JUSTIFICATION
        # -----------------------------
        justification = (
            f"The confidence score ({confidence}%) is derived from compression, noise, and sharpness signals, "
            f"placing this image in the {risk.lower()} risk category."
        )

        result = "Likely manipulated" if confidence > 70 else \
                 "Possibly manipulated" if confidence > 40 else \
                 "Likely original"

        # -----------------------------
        # SAVE RESULT
        # -----------------------------
        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "score_explanation": score_explanation,
                "confidence_explanation": confidence_explanation,
                "risk_level": risk,
                "legal_conclusion": legal_conclusion,
                "justification": justification,
                "ela_result": result,
                "metadata": metadata,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "regions": regions,
                "gps": gps,
                "narrative": narrative,
                "confidence_breakdown": {
                    "ela": int(ela_c),
                    "noise": int(noise_c),
                    "sharpness": int(sharp_c),
                    "metadata_bonus": meta_c
                }
            }
        }

    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}
