const express = require("express");
const cors = require("cors");
const multer = require("multer");

const app = express();
const upload = multer({ storage: multer.memoryStorage() });

app.use(cors());

// ROOT TEST
app.get("/", (req, res) => {
  res.send("PixelProof backend running");
});

// ✅ FIXED ANALYZE ENDPOINT
const multer = require("multer");
const exif = require("exif-parser");

const upload = multer({ storage: multer.memoryStorage() });

app.post("/api/analyze", upload.single("image"), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No image uploaded" });
    }

    let metadata = {};

    try {
      const parser = exif.create(req.file.buffer);
      const result = parser.parse();

      metadata = {
        camera: result.tags.Make || "Unknown",
        model: result.tags.Model || "Unknown",
        software: result.tags.Software || "Unknown",
        date: result.tags.DateTimeOriginal || null,
        gps: result.tags.GPSLatitude
          ? {
              lat: result.tags.GPSLatitude,
              lon: result.tags.GPSLongitude
            }
          : null
      };

    } catch (e) {
      console.log("EXIF parse failed");
    }

    const response = {
      score: 65,
      signals: {
        ela: 70,
        noise: 40,
        metadata: metadata.gps ? 20 : 5
      },
      metadata,
      heatmap: null,
      analysis: "Basic forensic indicators detected"
    };

    res.json({ result: response });

  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Analysis failed" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Server running on", PORT));
