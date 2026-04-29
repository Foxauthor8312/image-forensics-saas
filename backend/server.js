const multer = require("multer");
const upload = multer({ dest: "uploads/" });
const express = require("express");
const cors = require("cors");

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Root test
app.get("/", (req, res) => {
  res.send("PixelProof backend is running");
});

// Analyze endpoint (temporary working version)
app.post("/api/analyze", upload.single("image"), (req, res) => {

  const fakeGPS = {
    lat: 36.1699,
    lon: -115.1398,
    accuracy: 50
  };

  const fakeMetadata = {
    Camera: "iPhone 13",
    ISO: 200,
    Exposure: "1/120",
    Software: "Photoshop"
  };

  res.json({
    result: {
      analysis: "Possibly Modified",
      score: 62,
      confidence: 88,

      signals: {
        ela: 75,
        noise: 35,
        lighting: 55,
        edges: 40,
        metadata: 65
      },

      technical_explanation:
        "Compression artifacts and metadata inconsistencies suggest possible recompression or editing.",

      legal_explanation:
        "This image may not be admissible as original evidence without further forensic validation.",

      metadata: fakeMetadata,

      gps: fakeGPS,

      heatmap: null
    }
  });
});

app.listen(PORT, () => {
  console.log("Server running on port", PORT);
});
