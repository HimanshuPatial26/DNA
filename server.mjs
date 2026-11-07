#!/usr/bin/env node
/*
 * Zero-dependency static server for local development.
 *
 *   node server.mjs            -> http://localhost:8080
 *   PORT=3000 node server.mjs  -> http://localhost:3000
 *
 * Unlike `python -m http.server`, it answers HTTP Range requests, which
 * Safari requires before it will play <video> files.
 */
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PORT = Number(process.env.PORT) || Number(process.argv[2]) || 8080;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
};

function send(res, status, body = "", headers = {}) {
  res.writeHead(status, { "Content-Type": "text/plain; charset=utf-8", ...headers });
  res.end(body);
}

const server = createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "Method not allowed", { Allow: "GET, HEAD" });

  let path;
  try {
    path = decodeURIComponent(req.url.split(/[?#]/)[0]).replace(/\/{2,}/g, "/");
  } catch {
    return send(res, 400, "Bad request");
  }
  if (!path.startsWith("/")) path = "/" + path;
  // never serve dotfiles such as .git/
  if (path.split("/").some((part) => part.startsWith("."))) return send(res, 404, "Not found");
  if (path.endsWith("/")) path += "index.html";

  const file = resolve(ROOT, "." + path);
  if (file !== ROOT && !file.startsWith(ROOT + sep)) return send(res, 403, "Forbidden");

  let stat;
  try {
    stat = statSync(file);
  } catch {
    return send(res, 404, "Not found");
  }
  if (stat.isDirectory()) return send(res, 301, "", { Location: path + "/" });

  const headers = {
    "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
    "Accept-Ranges": "bytes",
    "Cache-Control": "no-cache",
    "Last-Modified": stat.mtime.toUTCString(),
  };
  const size = stat.size;
  const m = req.headers.range && /^bytes=(\d*)-(\d*)$/.exec(req.headers.range.trim());

  if (m && (m[1] !== "" || m[2] !== "")) {
    let start;
    let end;
    if (m[1] === "") {
      // suffix range: last N bytes
      start = Math.max(0, size - Number(m[2]));
      end = size - 1;
    } else {
      start = Number(m[1]);
      end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
    }
    if (start >= size || start > end) return send(res, 416, "", { "Content-Range": `bytes */${size}` });
    res.writeHead(206, { ...headers, "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": end - start + 1 });
    if (req.method === "HEAD") return res.end();
    return createReadStream(file, { start, end }).pipe(res);
  }

  res.writeHead(200, { ...headers, "Content-Length": size });
  if (req.method === "HEAD") return res.end();
  createReadStream(file).pipe(res);
});

server.listen(PORT, () => {
  console.log(`DNA site running at http://localhost:${PORT}  (Ctrl+C to stop)`);
});
