const express = require("express");
const serveIndex = require("serve-index");

const app = express();

const publicDir = process.env.FILE_FOLDER;

app.use(
  process.env.URL_PATH,
  express.static(publicDir),
  serveIndex(publicDir, { icons: true }),
);

app.listen(80);
