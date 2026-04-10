/* jshint esversion: 11 */
/**
 * Tiny HTTP server that toggles vim.enable in VS Code workspace settings.
 * Called by the nginx proxy when the user appends ?vim=1 or ?vim=0 to the URL.
 */
const http = require("http");
const fs = require("fs");

const SETTINGS_PATH = "/opt/src/.vscode/settings.json";

function readSettings() {
  try {
    return JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf8"));
  } catch {
    return {};
  }
}

function writeSettings(settings) {
  fs.writeFileSync(SETTINGS_PATH, JSON.stringify(settings, null, 2));
}

http
  .createServer((req, res) => {
    try {
      const settings = readSettings();
      if (req.url === "/vim/enable") {
        settings["vim.enable"] = true;
      } else if (req.url === "/vim/disable") {
        settings["vim.enable"] = false;
      }
      writeSettings(settings);
      res.writeHead(302, { Location: "/code/" });
      res.end();
    } catch (e) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end(e.message);
    }
  })
  .listen(8081, "0.0.0.0", () => {
    console.log("Vim toggle server listening on :8081");
  });
