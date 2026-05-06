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

const upload = multer({ storage: multer.memoryStorage() });

/* ===== CLASSIFICATION ===== */
function classifyImage(exif, elaScore) {
  if (exif && elaScore < 10) return { type: "Likely Original", confidence: 0.9 };
  if (exif && elaScore > 25) return { type: "Recompressed", confidence: 0.8 };
  if (!exif && elaScore > 25) return { type: "Edited", confidence: 0.85 };
  return { type: "Unknown", confidence: 0.6 };
}

/* ===== ELA ===== */
async function runELA(buffer) {

  const normalized = await sharp(buffer)
    .resize({ width: 800, withoutEnlargement: true })
    .jpeg()
    .toBuffer();

  const recompressed = await sharp(normalized)
    .jpeg({ quality: 60 })
    .toBuffer();

  const orig = await sharp(normalized)
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

  return {
    score: total / orig.data.length,
    buffer: elaImage
  };
}

/* ===== ANALYZE ===== */
app.post('/analyze', upload.single('image'), async (req, res) => {

  try {
    const buffer = req.file.buffer;

    const rawExif = await exifr.parse(buffer, { gps: true });
    const ela = await runELA(buffer);
    const classification = classifyImage(rawExif, ela.score);

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
      classification
    });

  } catch (err) {
    console.error(err);
    res.status(500).send("Analyze error");
  }
});

/* ===== PDF REPORT ===== */
app.post('/report', upload.single('image'), async (req, res) => {

  try {

    const buffer = req.file.buffer;

    const hash = crypto.createHash('sha256').update(buffer).digest('hex');
    const rawExif = await exifr.parse(buffer, { gps: true });
    const ela = await runELA(buffer);
    const classification = classifyImage(rawExif, ela.score);

    const doc = new PDFDocument({ margin: 40 });

    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', 'attachment; filename=pixelproof-report.pdf');

    doc.pipe(res);

    /* TITLE */
    doc.fontSize(20).text('PixelProof Forensic Report');
    doc.moveDown();

    /* HASH */
    doc.fontSize(10).text('SHA-256 Hash:');
    doc.text(hash);
    doc.moveDown();

    /* RESULT */
    doc.fontSize(14).text(`Result: ${classification.type}`);
    doc.text(`Confidence: ${Math.round(classification.confidence * 100)}%`);
    doc.moveDown();

    /* IMAGE */
    doc.text('Original Image');
    doc.image(buffer, { width: 250 });
    doc.moveDown();

    /* ELA */
    doc.text('ELA Analysis');
    doc.image(ela.buffer, { width: 250 });

    doc.end();

  } catch (err) {
    console.error(err);
    res.status(500).send("Report error");
  }
});

app.listen(PORT, () => console.log("Server running on port " + PORT));
