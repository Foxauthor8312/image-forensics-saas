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
app.post("/api/analyze", (req, res) => {
  res.json({
    result: {
      analysis: "Test OK",
      score: 50,
      confidence: 90,
      signals: {
        ela: 60,
        noise: 20,
        lighting: 40,
        edges: 30,
        metadata: 10
      },
      details: {
        technical: "This is a test response.",
        legal: "Not a forensic determination."
      },
      heatmap: null
    }
  });
});

app.listen(PORT, () => {
  console.log("Server running on port", PORT);
});
