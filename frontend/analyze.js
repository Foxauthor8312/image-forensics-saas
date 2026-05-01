export default async function handler(req, res) {
  try {
    const response = await fetch(
      "https://pixelproof-backend-v2.onrender.com/api/analyze",
      {
        method: "POST",
        body: req.body,
        headers: {
          "Content-Type": req.headers["content-type"]
        }
      }
    );

    const data = await response.json();
    res.status(200).json(data);

  } catch (err) {
    res.status(500).json({ error: "Proxy failed" });
  }
}
