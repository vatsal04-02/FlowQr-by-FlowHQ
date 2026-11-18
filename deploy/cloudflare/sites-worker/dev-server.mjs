// LOCAL DEVELOPMENT ONLY. Runs the real Worker code (index.mjs) on your machine against the files the backend's LocalDirectoryProvider wrote, so you can click through a published site.
// It pretends to be Cloudflare: KV = the hosts/*.json pointer files, R2 = the sites/ folder. Nothing here talks to Cloudflare.
//
//   SITES_DIR=/path/to/sites-dir SITES_BASE_DOMAIN=sites.localhost FLOWQR_API_URL=http://127.0.0.1:8102 SITES_SERVICE_TOKEN=<same as the backend> node dev-server.mjs
//   then open http://<slug>.sites.localhost:8787/   (browsers resolve *.localhost to this machine)
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join, normalize, sep } from "node:path";
import worker from "./index.mjs";

const DIR = process.env.SITES_DIR;
if (!DIR) { console.error("Set SITES_DIR to the folder the backend writes to."); process.exit(1); }
const PORT = Number(process.env.PORT || 8787);
const env = {
  SITES_BASE_DOMAIN: process.env.SITES_BASE_DOMAIN || "sites.localhost", FLOWQR_API_URL: process.env.FLOWQR_API_URL || "http://127.0.0.1:8000", SITES_SERVICE_TOKEN: process.env.SITES_SERVICE_TOKEN || "",
  HOSTS: { async get(key) { const f = join(DIR, "hosts", key.replace(/^host:/, "") + ".json"); return existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : null; } },
  SITES: { async get(key) {
    const f = normalize(join(DIR, key));
    if (!f.startsWith(normalize(DIR) + sep) || !existsSync(f) || !statSync(f).isFile()) return null;
    return { body: new Response(readFileSync(f)).body, httpEtag: '"dev"' };
  } },
};

createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const host = req.headers.host || "";
  const hostname = host.split(":")[0];
  if (req.headers.origin) req.headers.origin = `https://${hostname}`; // local pages are plain http; the Worker checks the https origin it will see in production
  const r = new Request(`http://${host}${req.url}`, { method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
  const out = await worker.fetch(r, env);
  res.writeHead(out.status, Object.fromEntries(out.headers));
  res.end(Buffer.from(await out.arrayBuffer()));
}).listen(PORT, "127.0.0.1", () => console.log(`Local sites server on http://<slug>.${env.SITES_BASE_DOMAIN}:${PORT}/`));
