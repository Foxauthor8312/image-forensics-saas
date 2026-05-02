const express = require("express");
const cors = require("cors");
const multer = require("multer");
const exifr = require("exifr");
const sharp = require("sharp");

const app = express();
const upload = multer({ storage: multer.memoryStorage() });

app.use(cors({ origin: "*" }));

// ROOT TEST
app.get("/", (req, res) => {
res.send("PixelProof backend running");
});

// 🧠 REAL ELA ANALYSIS
app.post("/api/analyze", upload.single("image"), async (req, res) => {
try {
if (!req.file) {
return res.status(400).json({ error: "No image uploaded" });
}

```
const original = req.file.buffer;

// ======================
// 🧠 METADATA (CLEAN)
// ======================
let metadata = {};

try {
  const exifData = await exifr.parse(original, {
    gps: true,
    reviveValues: true
  });

  console.log("EXIF FULL:", exifData);

  function dmsToDecimal(dms) {
    if (!Array.isArray(dms)) return dms;
    return dms[0] + dms[1] / 60 + dms[2] / 3600;
  }

  let lat = null;
  let lon = null;

  if (exifData?.latitude != null && exifData?.longitude != null) {
    lat = exifData.latitude;
    lon = exifData.longitude;
  } else if (exifData?.GPSLatitude && exifData?.GPSLongitude) {
    lat = dmsToDecimal(exifData.GPSLatitude);
    lon = dmsToDecimal(exifData.GPSLongitude);
  } else if (exifData?.gps) {
    lat = dmsToDecimal(exifData.gps.latitude);
    lon = dmsToDecimal(exifData.gps.longitude);
  }

  metadata = {
    camera: exifData?.Make || "Unknown",
    model: exifData?.Model || "Unknown",
    software: exifData?.Software || "Unknown",
    date: exifData?.DateTimeOriginal || exifData?.CreateDate || null,
    gps: (lat != null && lon != null) ? { lat, lon } : null
  };

} catch (e) {
  console.log("EXIF parse failed:", e.message);
}

// ======================
// 🧠 ELA ANALYSIS
// ======================
const recompressed = await sharp(original)
  .jpeg({ quality: 70 })
  .toBuffer();

const origRaw = await sharp(original).raw().toBuffer({ resolveWithObject: true });
const recomRaw = await sharp(recompressed).raw().toBuffer({ resolveWithObject: true });

const oData = origRaw.data;
const rData = recomRaw.data;

let diffSum = 0;
for (let i = 0; i < oData.length; i++) {
  diffSum += Math.abs(oData[i] - rData[i]);
}

const avgDiff = diffSum / oData.length;
const elaScore = Math.min(100, Math.round(avgDiff * 2));

// ======================
// 🧠 SCORING
// ======================
const signals = {
  ela: elaScore,
  noise: Math.max(20, Math.min(80, elaScore - 10)),
  metadata: metadata.gps ? 20 : 5
};

const score = Math.round(
  signals.ela * 0.5 +
  signals.noise * 0.25 +
  signals.metadata * 0.25
);

let analysis = "";

if (elaScore > 70) {
  analysis = "High compression inconsistencies detected across the image.";
} else if (elaScore > 40) {
  analysis = "Moderate compression variation observed.";
} else {
  analysis = "Compression appears consistent across the image.";
}

const conclusion =
  score > 70
    ? "Strong evidence of alteration"
    : score > 40
    ? "Possible modification detected"
    : "Likely authentic image";

res.json({
  result: {
    score,
    signals,
    metadata,
    heatmap: null,
    analysis,
    conclusion
  }
});
```

} catch (err) {
console.error("ELA ERROR:", err);
res.status(500).json({ error: "ELA analysis failed" });
}
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Server running on", PORT));
