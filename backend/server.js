const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

app.get('/', function(req, res) {
  res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async function(req, res) {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    console.log("UPLOAD OK");

    const rawExif = await exifr.parse(req.file.buffer);

    console.log("EXIF PARSED");

  let exif = null;

if (rawExif) {
  exif = {
    make: rawExif.Make || rawExif.make || "Unknown",
    model: rawExif.Model || rawExif.model || "Unknown",
    date: rawExif.DateTimeOriginal || rawExif.CreateDate || "Unknown",
    iso: rawExif.ISO || null,
    lens: rawExif.LensModel || null,
    gps: rawExif.latitude && rawExif.longitude
      ? { lat: rawExif.latitude, lon: rawExif.longitude }
      : null
  };
}

function calculateTampering(exif) {
  let score = 0.3;
  const reasons = [];

  if (!exif) {
    score += 0.4;
    reasons.push("No metadata present");
  } else {
    if (!exif.make || !exif.model) {
      score += 0.2;
      reasons.push("Missing camera information");
    }

    if (!exif.date || exif.date === "Unknown") {
      score += 0.2;
      reasons.push("Missing capture date");
    }

    if (exif.gps) {
      reasons.push("Contains GPS metadata");
    } else {
      reasons.push("No GPS metadata");
    }
  }

  score = Math.min(score, 1);

  let label = "Likely Original";
  if (score > 0.75) label = "Highly Suspicious";
  else if (score > 0.5) label = "Moderate Anomalies";
  else if (score > 0.3) label = "Minor Inconsistencies";

  return {
    likelihood: Number(score.toFixed(2)),
    label,
    reasons
  };
}
    
const tampering = calculateTampering(exif);

res.json({
  success: true,
  size: req.file.size,
  exif: exif,
  tampering
});

  } catch (err) {
    console.log("ERROR:", err.message);
    res.status(500).json({ error: "Server error" });
  }
});

app.listen(PORT, function() {
  console.log("Running on port " + PORT);
});
