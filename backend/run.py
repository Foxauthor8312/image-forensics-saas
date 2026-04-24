from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance

# AI
import torch
import torchvision.transforms as T
from torchvision.models import resnet18

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# AI MODEL
# -----------------------------
model = resnet18(weights="DEFAULT")
model.fc = torch.nn.Linear(model.fc.in_features, 2)
model.eval()

transform = T.Compose([
    T.Resize((224,224)),
    T.ToTensor(),
])

def run_ai_model(path):
    try:
        img = Image.open(path).convert("RGB")
        tensor = transform(img).unsqueeze(0)
        with torch.no_grad():
            out = model(tensor)
        prob = torch.softmax(out, dim=1)[0][1].item()
        return int(prob * 100)
    except:
        return None

# -----------------------------
# PDF REPORT
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")
        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
        content.append(Spacer(1,10))

        content.append(Paragraph(result["executive_summary"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Conclusion:", styles["Heading2"]))
        content.append(Paragraph(result["opinion"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Confidence:", styles["Heading2"]))
        content.append(Paragraph(result["confidence_reasoning"], styles["Normal"]))

        content.append(Spacer(1,10))

        content.append(Paragraph("Findings:", styles["Heading2"]))
        for e in result["explanation"]:
            content.append(Paragraph(f"- {e}", styles["Normal"]))

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg"), width=400, height=250))
        except:
            pass

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg"), width=400, height=250))
        except:
            pass

        doc.build(content)
        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF error:", e)
        return None

# -----------------------------
# PROCESS JOB
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"loading image"}

        image = Image.open(path).convert("RGB")
        image.thumbnail((800,800))
        image.save(path)

        # ELA
        jobs[job_id]["step"] = "running ELA"
        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # CV ANALYSIS
        jobs[job_id]["step"] = "analyzing structure"
        gray = cv2.imread(path,0)

        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        # AI
        jobs[job_id]["step"] = "running AI detection"
        ai_score = run_ai_model(path)

        # CONFIDENCE
        ela_c = score * 0.4
        noise_c = noise_n * 0.2
        sharp_c = sharp_n * 0.2
        ai_c = (ai_score or 0) * 0.2

        confidence = int(min(100, ela_c + noise_c + sharp_c + ai_c))

        # -----------------------------
        # REGION DETECTION + HEATMAP
        # -----------------------------
        jobs[job_id]["step"] = "detecting tamper regions"

        regions = []
        heatmap_file = None

        try:
            img = cv2.imread(path)
            img_small = cv2.resize(img,(600,600))

            gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))

            norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)
            _, thresh = cv2.threshold(norm,180,255,cv2.THRESH_BINARY)

            contours,_ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in contours[:5]:
                x,y,w,h = cv2.boundingRect(cnt)

                if w*h < 500:
                    continue

                reason = "Area shows unusual compression or texture differences."

                if noise_n > 40:
                    reason = "This region has irregular noise patterns."
                if sharp_n > 40:
                    reason = "Edges in this region appear inconsistent."

                regions.append({
                    "x":int(x),
                    "y":int(y),
                    "w":int(w),
                    "h":int(h),
                    "reason":reason
                })

            heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img_small,0.6,heat,0.4,0)

            heatmap_file = f"{job_id}_heatmap.jpg"
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        except Exception as e:
            print("Region error:", e)

        # -----------------------------
        # SIMPLE EXPLANATION
        # -----------------------------
        simple_explanation = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "risk_level": "High" if confidence>70 else "Moderate" if confidence>40 else "Low",
            "confidence_text": f"{confidence}% confidence",
            "meaning": "Indicates likelihood of manipulation based on multiple signals.",
            "reasons": ["Compression inconsistencies","Noise variation","AI detection"],
            "next_steps": "Verify before trusting."
        }

        # -----------------------------
        # RESULT
        # -----------------------------
        result_data = {
            "score":score,
            "confidence":confidence,
            "ai_score":ai_score,
            "ela_result":"Likely manipulated" if confidence>70 else "Likely original",
            "executive_summary":"Forensic indicators analyzed.",
            "opinion":"Possible manipulation." if confidence>40 else "No strong evidence.",
            "confidence_reasoning":f"Combined signals → {confidence}%",
            "ai_interpretation":f"AI suggests {ai_score}%" if ai_score else "AI unavailable",
            "methodology":["ELA","Noise","Sharpness","AI"],
            "evidence_analysis":{},
            "limitations":["Probabilistic analysis"],
            "recommendation":"Verify source.",
            "explanation":["Compression variation","Noise inconsistency"],
            "simple_explanation":simple_explanation,
            "confidence_breakdown":{
                "ela":int(ela_c),
                "noise":int(noise_c),
                "sharpness":int(sharp_c),
                "ai":int(ai_c)
            }
        }

        report_url = generate_pdf(job_id, result_data)

        jobs[job_id] = {
            "status":"done",
            "result":{
                **result_data,
                "ela_image":f"{BASE_URL}/files/{ela_file}",
                "heatmap":f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "regions":regions,
                "report":report_url
            }
        }

    except Exception as e:
        jobs[job_id] = {"status":"error","error":str(e)}

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error":"No file"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    jobs[job_id] = {"status":"processing"}
    threading.Thread(target=process_job,args=(job_id,path)).start()

    return jsonify({"job_id":job_id})

@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error"}))

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return jsonify({"status":"ok"})
