import { useState } from "react";
import axios from "axios";

function App() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);

  const upload = async () => {
    const formData = new FormData();
    formData.append("image", file);

    const res = await axios.post(
      process.env.REACT_APP_API_URL + "/api/analyze",
      formData
    );

    setResult(res.data);
  };

  return (
    <div style={{ padding: 20 }}>
      <h1>PixelProof</h1>

      <input type="file" onChange={(e) => setFile(e.target.files[0])} />

      <button onClick={upload}>Analyze</button>

      {result && (
        <div>
          <p>Score: {result.score}%</p>
          <p>{result.ela_result}</p>
        </div>
      )}
    </div>
  );
}

export default App;