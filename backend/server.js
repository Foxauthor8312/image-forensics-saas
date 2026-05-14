const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');
const sharp = require('sharp');
const PDFDocument = require('pdfkit');
const crypto = require('crypto');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());
const path = require('path');

app.use(express.static(path.join(__dirname, '../frontend')));
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, '../frontend/index.html'));
});
app.use(express.static('public'));


const upload = multer({ storage: multer.memoryStorage() });

/* ===== CLASSIFICATION ===== */
function classifyImage(exif, elaScore) {
  if (exif && elaScore < 10) return { type: "Likely Original", confidence: 0.9 };
  if (exif && elaScore > 25) return { type: "Recompressed", confidence: 0.8 };
  if (!exif && elaScore > 25) return { type: "Edited", confidence: 0.85 };
  return { type: "Unknown", confidence: 0.6 };
}

/* ===== AI DETECTION ===== */
function detectAI(elaScore, exif) {

  let score = 0;

  // Missing metadata (common in AI, but also screenshots)
  if (!exif) score += 15;

  // Extremely uniform compression (common in AI renders)
  if (elaScore < 5) score += 25;

  // Very low variation (over-smoothed images)
  if (elaScore < 10) score += 15;

  // Clamp result
  return Math.min(score, 60);
}

/* ===== ELA ===== */
async function runELA(buffer) {
  const normalizedImage = await sharp(buffer)
    .resize({ width: 800, withoutEnlargement: true })
    .jpeg()
    .toBuffer();

  const recompressed = await sharp(normalizedImage)
    .jpeg({ quality: 60 })
    .toBuffer();

  const orig = await sharp(normalizedImage)
    .raw()
    .toBuffer({ resolveWithObject: true });

  const comp = await sharp(recompressed)
    .raw()
    .toBuffer({ resolveWithObject: true });

  let total = 0;
  for (let i = 0; i < orig.data.length; i++) {
    total += Math.abs(orig.data[i] - comp.data[i]);
  }

  const diff = Buffer.alloc(orig.data.length);
  for (let i = 0; i < orig.data.length; i++) {
    diff[i] = Math.min(255, Math.abs(orig.data[i] - comp.data[i]) * 10);
  }

  const elaImage = await sharp(diff, {
    raw: {
      width: orig.info.width,
      height: orig.info.height,
      channels: orig.info.channels
    }
  }).jpeg().toBuffer();

  
  const rawScore = total / orig.data.length;

// normalize to 0–100 range
const normalized = Math.min(100, rawScore * 10);

return {
  score: normalized,
  buffer: elaImage
};
}

/* ===== ANALYZE ===== */
app.post('/analyze', upload.single('image'), async (req, res) => {

  const buffer = req.file.buffer;

  const rawExif = await exifr.parse(buffer, { gps: true });
  const ela = await runELA(buffer);
  const classification = classifyImage(rawExif, ela.score);
  const aiScore = detectAI(ela.score, rawExif);

  res.json({
    ela: {
      score: ela.score,
      overlay: `data:image/jpeg;base64,${ela.buffer.toString('base64')}`
    },
    exif: rawExif,
    gps: {
      lat: rawExif?.latitude || null,
      lon: rawExif?.longitude || null
    },
    classification,
    ai: {
      likelihood: aiScore
    }
  });
});

/* ===== PDF REPORT ===== */
app.post('/report', upload.single('image'), async (req, res) => {

  const buffer = req.file.buffer;

  const hash = crypto.createHash('sha256').update(buffer).digest('hex');
  const rawExif = await exifr.parse(buffer, { gps: true });
  const ela = await runELA(buffer);
  const classification = classifyImage(rawExif, ela.score);
  const aiScore = detectAI(ela.score, rawExif);

  /* ===== SIGNALS ===== */
  const signals = {
   compression: Math.max(0,100-ela),
    anomalies: ela,
    metadata: rawExif
  ? (rawExif.Make ? 90 : 70)
  : 20,
    ai: aiScore
  };

  const score = Math.round(
    signals.compression*0.3 +
    signals.anomalies*0.3 +
    signals.metadata*0.2 +
    signals.ai*0.2
  );

  /* ===== NARRATIVE ===== */
  const narrative = {
    what: signals.anomalies > 65
      ? "Different parts of the image appear to have been saved differently."
      : "The image appears to have been processed consistently as a whole.",

    why: signals.anomalies > 65
      ? "This typically occurs when part of an image is edited separately and then recompressed."
      : "This is consistent with normal image processing such as resizing or compression.",

    meaning: score >= 70
      ? "There is a meaningful risk that this image has been altered. Verification is recommended."
      : "No strong indicators of manipulation were detected, but results should be interpreted in context."
  };

  const doc = new PDFDocument({ margin: 40 });

  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Disposition', 'attachment; filename=pixelproof-report.pdf');

  doc.pipe(res);

  /* HEADER */
  doc.fontSize(20).text('PixelProof Forensic Report');
  doc.moveDown();

  doc.fontSize(10).text(`SHA-256 Hash: ${hash}`);
  doc.moveDown();

  /* RESULTS */
  doc.fontSize(14).text(`Score: ${score}/100`);
  doc.text(`Classification: ${classification.type}`);
  doc.text(`Confidence: ${Math.round(classification.confidence * 100)}%`);
  doc.text(`AI Likelihood: ${aiScore}%`);
  doc.moveDown();

  /* EXPLANATION */
  doc.fontSize(12).text("What was found:");
  doc.text(narrative.what);
  doc.moveDown();

  doc.text("Why this matters:");
  doc.text(narrative.why);
  doc.moveDown();

  doc.text("What this means:");
  doc.text(narrative.meaning);
  doc.moveDown();

  /* SCORE BREAKDOWN */
  doc.text("How the score was calculated:");
  doc.text("Compression consistency (30%)");
  doc.text("Localized anomalies (30%)");
  doc.text("Metadata presence (20%)");
  doc.text("AI likelihood (20%)");
  doc.moveDown();

  /* METADATA */
  doc.text("Metadata Summary:");
  doc.text(`Camera: ${rawExif?.Make || "-"}`);
  doc.text(`Model: ${rawExif?.Model || "-"}`);
  doc.text(`Date: ${rawExif?.DateTimeOriginal || "-"}`);
  doc.text(`Resolution: ${rawExif?.ImageWidth || "-"} x ${rawExif?.ImageHeight || "-"}`);
  doc.text(`Location: ${rawExif?.latitude || "N/A"}, ${rawExif?.longitude || "N/A"}`);
  doc.moveDown();

  /* IMAGES */
  doc.text("Original Image:");
  doc.image(buffer, { width: 250 });
  doc.moveDown();

  doc.text("ELA Analysis:");
  doc.image(ela.buffer, { width: 250 });
  doc.moveDown();
app.get('/api/event', async (req, res) => {

  try {

    const url = req.query.url;

    console.log('Fetching:', url);

    const response = await fetch(url);

    const html = await response.text();

    res.send(html);

  } catch (err) {

    console.error(err);

    res.status(500).send('Failed to load event');

  }

});
  
  /* NEXT STEPS */
  doc.text("Recommended Next Steps:");
  doc.text("- Verify the original source of the image");
  doc.text("- Compare with other versions online");
  doc.text("- Check trusted news or official sources");
  doc.text("- Inspect suspicious areas for inconsistencies");
  doc.moveDown();

  doc.end();
});

app.listen(PORT, () => console.log("Server running on port " + PORT));
