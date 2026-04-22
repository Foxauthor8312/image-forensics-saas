import React, { useState } from "react";
import axios from "axios";

function App() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const upload = async () => {
    if (!file) {
      alert("Please select a file first");
      return;
    }

    const formData = new FormData();
    formData.append("image", file);

    setLoading(true);

    try {
      const res = await axios.post(
        "https://pixelproof-backend.onrender.com/api/analyze", // 🔥 replace if your URL is different
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        }
      );

      setResult(res.data);
    } catch (err) {
      console.error(err);
      alert("Upload failed");
    }

    setLoading(false);
  };

  return (
    <div style={{ padding: 20, fontFamily: "Arial" }}>
      <h1>PixelProof</h1>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0])}
      />

      <br /><br />

      <button onClick={upload}>
        {loading ? "Analyzing..." : "Analyze"}
      </button>

      {result && (
        <div style={{ marginTop: 20 }}>
          <h3>Results</h3>

          <p><strong>Score:</strong> {result.score}%</p>
          <p><strong>Result:</strong> {result.ela_result}</p>

          <ul>
            {result.findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>

          {/* Optional images */}
          {result.original_image && (
            <div>
              <h4>Original</h4>
              <img
                src={`https://pixelproof-backend.onrender.com${result.original_image}`}
                alt="original"
                width="300"
              />
            </div>
          )}

          {result.heatmap_image && (
            <div>
              <h4>Heatmap</h4>
              <img
                src={`https://pixelproof-backend.onrender.com${result.heatmap_image}`}
                alt="heatmap"
                width="300"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default App;