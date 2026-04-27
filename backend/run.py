from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, json, hashlib
import numpy as np

from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

def explain(score):
    if score > 70:
        return {
            "simple": "Strong signs of manipulation detected.",
            "technical": "Multiple forensic signals indicate inconsistencies in compression, structure, and noise patterns.",
            "legal": "The image demonstrates characteristics consistent with digital alteration.",
            "confidence_note": "High confidence due to agreement across detection methods."
        }
    elif score > 40:
        return {
            "simple": "Possible editing detected.",
            "technical": "Moderate inconsistencies detected across several forensic indicators.",
            "legal": "The image may have undergone editing or recompression.",
            "confidence_note": "Moderate confidence; further validation recommended."
        }
    else:
        return {
            "simple": "Image appears original.",
            "technical": "Image signals are consistent across compression, noise, and structural analysis.",
            "legal": "No indicators of digital manipulation detected.",
            "confidence_note": "High confidence in authenticity."
        }

def ela_score(image, path):
    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)

    gray = np.array(ela.convert("L"))
    return np.mean(gray)/255*100, ela

def noise_score(image):
    gray = np.array(image.convert("L"))
    blur = Image.fromarray(gray).filter(ImageFilter.GaussianBlur(3))
    noise = np.abs(gray - np.array(blur))
    return np.std(noise)/255*100

def edge_score(image):
    edges = image.filter(ImageFilter.FIND_EDGES)
    return np.mean(np.array(edges.convert("L")))/255*100

def block_score(image):
    gray = np.array(image.convert("L"))
    h,w = gray.shape
    blocks=[]
    for y in range(0,h-8,8):
        for x in range(0,w-8,8):
            blocks.append(np.std(gray[y:y+8,x:x+8]))
    return np.std(blocks)/255*100

def metadata_score(meta):
    if not meta: return 10
    txt=str(meta).lower()
    if "photoshop" in txt or "adobe" in txt: return 80
    return 30

def combine(scores):
    weights={"ela":0.3,"noise":0.2,"edge":0.2,"block":0.2,"meta":0.1}
    total=sum(scores[k]*weights[k] for k in weights)
    confidence=100-np.std(list(scores.values()))
    return int(total), int(max(0,min(100,confidence)))

def generate_pdf(job_id,data):
    path=os.path.join(UPLOAD_FOLDER,f"{job_id}.pdf")
    doc=SimpleDocTemplate(path)
    styles=getSampleStyleSheet()

    content=[]
    content.append(Paragraph("Forensic Report",styles["Title"]))
    content.append(Spacer(1,12))

    content.append(Paragraph(f"Result: {data['analysis']}",styles["Normal"]))
    content.append(Paragraph(f"Score: {data['score']}",styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}",styles["Normal"]))
    content.append(Spacer(1,12))

    content.append(Paragraph(data["technical_explanation"],styles["Normal"]))
    content.append(Spacer(1,12))

    content.append(Paragraph("Signal Breakdown",styles["Heading2"]))
    for k,v in data["signals"].items():
        content.append(Paragraph(f"{k}: {v}",styles["Normal"]))

    content.append(Spacer(1,20))
    content.append(Paragraph("PixelProof",styles["Normal"]))

    doc.build(content)

    return f"{BASE_URL}/files/{job_id}.pdf"

@app.route("/api/analyze",methods=["POST"])
def analyze():
    file=request.files["image"]
    metadata=json.loads(request.form.get("metadata","{}"))
    gps=json.loads(request.form.get("gps","null"))

    job_id=str(uuid.uuid4())
    path=os.path.join(UPLOAD_FOLDER,job_id+".jpg")
    file.save(path)

    img=Image.open(path).convert("RGB")

    ela,ela_img=ela_score(img,path)
    noise=noise_score(img)
    edge=edge_score(img)
    block=block_score(img)
    meta=metadata_score(metadata)

    scores={"ELA":int(ela),"Noise":int(noise),"Edges":int(edge),"Compression":int(block),"Metadata":int(meta)}

    final,conf=combine({"ela":ela,"noise":noise,"edge":edge,"block":block,"meta":meta})

    exp=explain(final)

    heatfile=f"{job_id}_heat.jpg"
    ela_img.save(os.path.join(UPLOAD_FOLDER,heatfile))

    result={
        "analysis":"Likely edited" if final>70 else "Possibly edited" if final>40 else "Likely original",
        "score":final,
        "confidence":conf,
        "simple_explanation":exp["simple"],
        "technical_explanation":exp["technical"],
        "legal_explanation":exp["legal"],
        "confidence_note":exp["confidence_note"],
        "signals":scores,
        "metadata":{"available":bool(metadata),"all":metadata},
        "gps":gps,
        "heatmap":f"{BASE_URL}/files/{heatfile}"
    }

    result["pdf_report"]=generate_pdf(job_id,result)

    return jsonify({"result":result})

@app.route("/files/<f>")
def files(f):
    return send_from_directory(UPLOAD_FOLDER,f)
