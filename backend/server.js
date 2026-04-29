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
app.post("/api/analyze", upload.single("image"), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No image uploaded" });
    }

    // Simulated analysis (stable)
    const result = {
      score: 62,
      signals: {
        ela: 68,
        noise: 45,
        metadata: 20
      },
      metadata: {
        camera: "Unknown",
        software: "None",
        gps: {
          lat: 36.1699,
          lon: -115.1398
        }
      },
      heatmap: null,
      analysis: "Simulated forensic result"
    };

    res.json({ result });

  } catch (err) {
    console.error("ANALYZE ERROR:", err);
    res.status(500).json({ error: "Server failed to analyze image" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Server running on", PORT));
