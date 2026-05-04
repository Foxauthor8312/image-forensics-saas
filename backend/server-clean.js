const express = require('express');
const app = express();
const port = process.env.PORT || 10000;

app.get('/', (req, res) => {
  res.send('OK');
});

app.listen(PORT, () => {
  console.log('Running on prt '+ PORT);
});