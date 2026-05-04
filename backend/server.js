const express = require('express');
const multer = require('multer');
const exifr = require('exifr');
const sharp = require('sharp');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 10000;

// =========================
// MIDDLEWARE
// =========================
app.use(cors({ origin: "*" }));
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
version: "v1.4.1-fixed",
status: "stable",
time: new Date().toISOString()
});
});

// =========================
// HEALTH
// =========================
app.get('/', (req, res) => {
res.send("PixelProof backend v1.4.1");
});

// =========================
// EXIF
// =========================
async function extractExif(buffer) {
try {
return await exifr.parse(buffer);
} catch {
return null;
}
}

function cleanExif(exif) {
if (!exif) return null;

return {
camera: {
make: exif.Make || null,
model: exif.Model || null
},
capture: {
date: exif.DateTimeOriginal || null
},
gps: exif.latitude && exif.longitude
? { lat: exif.latitude, lon: exif.longitude }
: null
};
}

// =========================
// ELA (SAFE + FAST)
// =========================
async function runELA(buffer) {
try {

```
const normalized = await sharp(buffer)
  .rotate()
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

const diff = Buffer.alloc(orig.data.length);
let total = 0;

for (let i = 0; i < orig.data.length; i++) {
  const v = Math.min(255, Math.abs(orig.data[i] - comp.data[i]) * 10);
  diff[i] = v;
  total += v;
}

const elaImage = await sharp(diff, {
  raw: {
    width: orig.info.width,
    height: orig.info.height,
    channels: orig.info.channels
  }
}).png().toBuffer();

const overlay = await sharp(normalized)
  .composite([{ input: elaImage, blend: 'overlay', opacity: 0.6 }])
  .png()
  .toBuffer();

const score = total / orig.data.length;

return {
  overlay: "data:image/png;base64," + overlay.toString("base64"),
  score: Number(score.toFixed(2))
};
```

} catch (err) {
console.error("ELA error:", err);
return null;
}
}

// =========================
// ANALYZE
// =========================
app.post('/analyze', upload.single('image'), async (req, res) => {
  try {

    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    if (req.file.size > 10 * 1024 * 1024) {
      return res.status(400).json({ error: "File too large (10MB max)" });
    }

    console.log("File:", req.file.mimetype, req.file.size);

    const rawExif = await extractExif(req.file.buffer);
    const exif = cleanExif(rawExif);

    let ela = null;
    try {
      ela = await runELA(req.file.buffer);
    } catch (err) {
      console.error("ELA failed:", err.message);
    }

    // scoring
    let likelihood = 0.3;
    if (!rawExif) likelihood += 0.2;
    if (ela?.score > 10) likelihood += 0.3;
    if (ela?.score > 15) likelihood += 0.2;

    likelihood = Math.min(1, likelihood);

    let label = "Likely Original";
    if (likelihood > 0.75) label = "Highly Suspicious";
    else if (likelihood > 0.5) label = "Moderate Anomalies";
    else if (likelihood > 0.3) label = "Minor Inconsistencies";

    const reasons = [];
    if (!rawExif) reasons.push("Missing EXIF metadata");
    if (ela && ela.score > 10) reasons.push("Compression inconsistencies detected");

    res.json({
      success: true,
      confidence: 0.9,
      exif: exif ? { present: true, data: exif } : { present: false },
      ela: ela || { status: "skipped" },
      tampering: {
        likelihood: Number(likelihood.toFixed(2)),
        label,
        reasons
      }
    });

  } catch (err) {
    console.error("Server error:", err);
    res.status(500).json({ error: "Processing failed" });
  }
});

// =========================
// SIMPLE SCORING
// =========================
let likelihood = 0.3;

if (!rawExif) likelihood += 0.2;
if (ela?.score > 10) likelihood += 0.3;
if (ela?.score > 15) likelihood += 0.2;

likelihood = Math.min(1, likelihood);

let label = "Likely Original";
if (likelihood > 0.75) label = "Highly Suspicious";
else if (likelihood > 0.5) label = "Moderate Anomalies";
else if (likelihood > 0.3) label = "Minor Inconsistencies";

// =========================
// RESPONSE
// =========================
res.json({
  success: true,
  confidence: 0.9,
  exif: exif ? { present: true, data: exif } : { present: false },
  ela: ela || { status: "skipped" },
  tampering: {
    likelihood: Number(likelihood.toFixed(2)),
    label,
    reasons: [
      !rawExif ? "Missing EXIF metadata" : null,
      ela?.score > 10 ? "Compression inconsistencies detected" : null
    ].filter(Boolean)
  }
});
```

} catch (err) {
console.error("Server error:", err);
res.status(500).json({ error: "Processing failed" });
}
});

// =========================
// START
// =========================
app.listen(PORT, () => {
console.log("=== SERVER STARTED ===");
console.log(`Running on port ${PORT}`);
});
