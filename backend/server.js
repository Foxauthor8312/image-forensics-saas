const cors = require('cors');
const express = require('express');
const multer = require('multer');

const app = express();
const PORT = process.env.PORT || 10000;

const upload = multer({ storage: multer.memoryStorage() });

app.get('/', (req, res) => {
  res.send('OK');
});

app.post('/analyze', upload.single('image'), (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: "No file uploaded" });
  }

  res.json({
    success: true,
    size: req.file.size
  });
});

app.listen(PORT, () => {
  console.log('Running on port ' + PORT);
});
