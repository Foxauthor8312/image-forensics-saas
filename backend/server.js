const express = require('express');
const multer = require('multer');
const exifr = require('exifr');

const app = express();
const PORT = process.env.PORT || 10000;

// =========================
// MIDDLEWARE
// =========================
app.use(express.json());

app.use((req, res, next) => {
  console.log(`[REQ] ${req.method} ${req.url}`);
  next();
});

const upload = multer({ storage: multer.memoryStorage() });

// =========================
// VERSION
// =========================
app.get('/version', (req, res) => {
  res.json({
    version: "v1.1.0",
    status: "clean-build",
    time: new Date().toISOString()
  });
});

// =========================
// HEALTH
// =========================
app.get('/', (req, res) => {
  res.send("PixelProof backend v1.1.0");
});

// =========================
// EXIF CLEANER
// =========================
function cleanExif(exif) {
  if (!exif) return null;

  return {
    camera: {
      make: exif.Make || null,
      model: exif.Model || null
    },
    capture: {
      date: exif.DateTimeOriginal || null,
      modified: exif.ModifyDate || null
    },
    image: {
      width: exif.ExifImageWidth || null,
      height: exif.ExifImageHeight || null
    },
    gps: exif.latitude && exif.longitude
      ? {
          lat: exif.latitude,
          lon: exif.longitude
        }
      : null
  };
}

// =========================
// EXIF EXTRACTION
// =========================
async function extractExif(buffer) {
  try {
    const data = await exifr.parse(buffer);
    return data;
  } catch (err) {
    console.log("EXIF error:", err.message);
    return null;
  }
}

// =========================
// CONFIDENCE SCORING
// =========================
function calculateConfidence(exif) {
  // Simple baseline logic (expand later)
  if (!exif) return 0.3;

  let score = 0.5;

  if (exif.Make) score += 0.1;
  if (exif.Model) score += 0.1;
  if (exif.DateTimeOriginal) score += 0.1;
  if (exif.latitude && exif.longitude) score += 0.1;

  return Math.min(score, 0.9);
}

// =========================
// ANALYZE ROUTE
// =========================
app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    console.log("File:", req.file.mimetype, req.file.size);

    // EXIF
    const rawExif = await extractExif(req.file.buffer);
    const cleanedExif = cleanExif(rawExif);

    const exifResult = cleanedExif
      ? { present: true, data: cleanedExif }
      : { present: false, message: "No metadata (common for mobile uploads)" };

    // CONFIDENCE
    const confidence = calculateConfidence(rawExif);

    // =========================
    // ELA (HOOK YOUR REAL ONE HERE)
    // =========================
    const elaResult = {
      status: "pending",
      note: "Integrate ELA processing here"
    };

    // =========================
    // RESPONSE
    // =========================
    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      confidence,
      exif: exifResult,
      ela: elaResult
    });

  } catch (err) {
    console.error("Processing error:", err);
    res.status(500).json({ error: "Processing failed" });
  }
});

// =========================
// START SERVER
// =========================
app.listen(PORT, () => {
  console.log("=== SERVER STARTED ===");
  console.log(`Running on port ${PORT}`);
});
