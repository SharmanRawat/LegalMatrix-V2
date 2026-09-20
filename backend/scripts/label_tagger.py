#!/usr/bin/env python3
"""Label-type tagger for the LegalMatrix audit dataset.

Classify every dataset photo as one of:
    front  — PDP / principal display panel (brand face, product name)
    back   — declarations block (MRP, net qty, manufacturer, dates, care…)
    side   — side panel (nutrition / extra dates / care)
    top    — cap / roof face (batch no, use-by, MRP/USP on snack packs)
    other  — packaging shots, seals, barcodes…

Run:
    cd backend && ./venv/bin/python scripts/label_tagger.py
Then open http://127.0.0.1:8765 — click photos or use keys 1-5 (Front,
Back, Side, Other); the app auto-advances to the next untagged photo.
Tags are saved instantly to backend/data/label_types.json (gitignored).

    --images-dir  default: <repo>/images
    --out         default: <repo>/backend/data/label_types.json
"""
import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_IMAGES = REPO / "images"
DEFAULT_OUT = REPO / "backend" / "data" / "label_types.json"

TAGS = ("front", "back", "side", "top", "other")

# Filename-embedded types may also use 'top' (cap/roof face) — first-class.
_EMBED_RE = re.compile(r"image(\d+)_(front|back|side|other|top|\d+)\.jpg$")
_EMBED_TO_TAG = {"front": "front", "back": "back", "side": "side",
                 "other": "other", "top": "top"}


def photo_tag(fname: str, tags: dict) -> str | None:
    """Effective label type for a photo: manual manifest tag wins over the
    type embedded in the filename (image1_front.jpg -> 'front')."""
    if fname in tags:
        return tags[fname]
    m = _EMBED_RE.match(fname)
    return _EMBED_TO_TAG.get(m.group(2)) if m else None

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LegalMatrix — Label-type tagger</title>
<style>
  :root { --ok:#16a34a; --okbg:#dcfce7; --bad:#dc2626; }
  * { box-sizing: border-box; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
         margin:0; background:#f3f4f6; color:#111827; }
  .top { position:sticky; top:0; z-index:10; background:#1f2937; color:#fff;
         padding:12px 20px; display:flex; align-items:center; gap:16px; }
  .top h1 { font-size:16px; margin:0; }
  .prog { flex:1; background:#374151; height:10px; border-radius:5px; overflow:hidden; }
  .prog > div { background:#22c55e; height:100%; width:0%; transition:width .2s; }
  .stat b { color:#22c55e; }
  .hint { font-size:11px; opacity:.75; }
  .group-title { padding:14px 20px 6px; font-weight:600; color:#374151;
                 background:#e5e7eb; margin:0; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
          gap:12px; padding:12px 20px 40px; }
  .card { background:#fff; border:1px solid #e5e7eb; border-radius:10px;
          overflow:hidden; }
  .card .imgwrap { position:relative; background:#000; }
  .card img { width:100%; height:auto; display:block; max-height:420px;
              object-fit:contain; cursor:zoom-in; }
  .card .badge { position:absolute; top:6px; left:6px; background:rgba(0,0,0,.72);
                 color:#fff; font-size:11px; padding:2px 7px; border-radius:4px; }
  .card .tagbadge { position:absolute; top:6px; right:6px; font-size:11px;
                    font-weight:700; padding:2px 8px; border-radius:4px;
                    background:rgba(0,0,0,.72); color:#fff; }
  .card .tagbadge.done { background:var(--ok); }
  .card .meta { padding:8px 10px 10px; }
  .card .meta .fname { font-size:12px; color:#6b7280; font-family:ui-monospace,monospace; }
  .btns { display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:8px; }
  .btns button { border:1px solid #d1d5db; background:#fff; color:#374151;
                 border-radius:6px; padding:7px 0; font-size:12px; font-weight:600;
                 cursor:pointer; }
  .btns button small { display:block; font-size:9px; font-weight:400; color:#9ca3af; }
  .btns button.active { background:var(--okbg); border-color:var(--ok); color:var(--ok); }
  .btns button.active small { color:var(--ok); }
  .card.focus { outline:3px solid #2563eb; outline-offset:2px; }
  .done-msg { font-size:11px; color:var(--ok); margin-top:6px; }
  .zoom { position:fixed; inset:0; background:rgba(0,0,0,.9); display:none;
          align-items:center; justify-content:center; z-index:50; }
  .zoom.open { display:flex; }
  .zoom img { max-width:96vw; max-height:96vh; border-radius:6px; }
</style></head>
<body>
<div class="top">
  <h1>LegalMatrix · label-type tagger</h1>
  <div class="prog"><div id="bar"></div></div>
  <div class="stat"><b id="count">0</b>/<span id="total">0</span> tagged</div>
  <div class="hint">keys: 1 Front · 2 Back · 3 Side · 4 Top · 5 Other — auto-advances.
     Space = zoom</div>
</div>
<div id="groups"></div>
<div class="zoom" id="zoom"><img id="zoomImg" alt="zoom"></div>
<script>
const TAGS = ["front", "back", "side", "top", "other"];
let data = { products: [] };
let focusIdx = null; // flattened index over photos

function flat() {
  const out = [];
  data.products.forEach(p => p.photos.forEach(ph => out.push({ p, ph })));
  return out;
}
function refreshProgress() {
  const all = flat();
  const done = all.filter(x => x.ph.tag).length;
  document.getElementById("count").textContent = done;
  document.getElementById("total").textContent = all.length;
  document.getElementById("bar").style.width =
    (all.length ? (done / all.length) * 100 : 0) + "%";
  const firstUntagged = all.findIndex(x => !x.ph.tag);
  if (firstUntagged !== -1 && focusIdx === null) focusIdx = firstUntagged;
  renderCards();
  document.title = `(${all.length - done} left) Label-type tagger`;
}
function label(tag) {
  return {"front":"Front · PDP","back":"Back · Decls","side":"Side","top":"Top · Cap","other":"Other"}[tag] || tag;
}
function renderCards() {
  const groups = document.getElementById("groups");
  groups.innerHTML = "";
  data.products.forEach(p => {
    const h = document.createElement("div");
    h.className = "group-title";
    h.textContent = `Product ${p.product}  (${p.photos.filter(x => x.tag).length}/${p.photos.length})`;
    groups.appendChild(h);
    const grid = document.createElement("div");
    grid.className = "grid";
    p.photos.forEach(ph => {
      const card = document.createElement("div");
      card.className = "card" + (flat()[focusIdx]?.ph.name === ph.name ? " focus" : "");
      card.dataset.name = ph.name;
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = ph.url;
      img.alt = ph.name;
      img.onclick = () => { openZoom(ph.url); };
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = ph.name;
      const tb = document.createElement("div");
      tb.className = "tagbadge" + (ph.tag ? " done" : "");
      tb.textContent = ph.tag ? label(ph.tag) : "untagged";
      const wrap = document.createElement("div");
      wrap.className = "imgwrap";
      wrap.append(img, badge, tb);
      const meta = document.createElement("div");
      meta.className = "meta";
      const fname = document.createElement("div");
      fname.className = "fname";
      fname.textContent = `${ph.name}  ·  product ${p.product}`;
      const btns = document.createElement("div");
      btns.className = "btns";
      TAGS.forEach((t, i) => {
        const b = document.createElement("button");
        b.dataset.tag = t;
        b.innerHTML = `${t[0].toUpperCase()}${t.slice(1)} <small>key ${i + 1}</small>`;
        if (ph.tag === t) b.classList.add("active");
        b.onclick = (e) => { e.stopPropagation(); setTag(ph.name, t); };
        btns.appendChild(b);
      });
      card.onclick = () => {
        focusIdx = flat().findIndex(x => x.ph.name === ph.name);
        renderCards();
      };
      meta.append(fname, btns);
      card.appendChild(wrap);
      card.appendChild(meta);
      grid.appendChild(card);
    });
    groups.appendChild(grid);
  });
}
async function setTag(name, tag) {
  const res = await fetch("/api/tag", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, tag }),
  });
  if (!res.ok) return alert("save failed");
  const ph = flat().find(x => x.ph.name === name).ph;
  ph.tag = tag;
  refreshProgress();
  advance();
}
function advance() {
  const all = flat();
  let i = focusIdx;
  const start = i;
  do {
    i = (i + 1) % all.length;
    if (all.length - all.filter(x => x.ph.tag).length === 0) { focusIdx = null; renderCards(); return; }
  } while (all[i].ph.tag && i !== start);
  focusIdx = i;
  renderCards();
  const el = document.querySelector(`.card[data-name="${all[i].ph.name}"]`);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}
function openZoom(url) {
  const z = document.getElementById("zoom");
  document.getElementById("zoomImg").src = url;
  z.classList.add("open");
}
document.addEventListener("keydown", (e) => {
  if (e.key === " ") { e.preventDefault();
    const ph = flat()[focusIdx];
    if (ph) openZoom(ph.ph.url); return; }
  const n = parseInt(e.key, 10);
  if (n >= 1 && n <= TAGS.length && flat()[focusIdx] && !flat()[focusIdx].ph.tag) {
    setTag(flat()[focusIdx].ph.name, TAGS[n - 1]); return;
  }
  if (flat()[focusIdx] && flat()[focusIdx].ph.tag) advance();
  const card = document.querySelector(`.card[data-name="${flat()[focusIdx]?.ph.name}"]`);
  if (card && (e.key === "ArrowRight" || e.key === "ArrowDown")) { advance(); }
});
document.getElementById("zoom").addEventListener("click", (e) => {
  if (e.target.id === "zoom") e.target.classList.remove("open");
});
(async () => {
  data = await (await fetch("/api/photos")).json();
  data.products.sort((a, b) => parseInt(a.product) - parseInt(b.product));
  refreshProgress();
})();
</script></body></html>
"""


def load_tags(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_tags(path: Path, tags: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tags, indent=2, sort_keys=True))
    tmp.replace(path)


class Handler(BaseHTTPRequestHandler):
    images_dir: Path = DEFAULT_IMAGES
    out_path: Path = DEFAULT_OUT
    tags: dict = {}

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/photos":
            items = []
            for f in sorted(self.images_dir.glob("image*.jpg")):
                if not _EMBED_RE.match(f.name):
                    continue
                items.append({
                    "product": _EMBED_RE.match(f.name).group(1),
                    "name": f.name,
                    "url": f"/img/{f.name}",
                    "tag": photo_tag(f.name, self.tags),
                })
            by_product = {}
            for it in items:
                by_product.setdefault(it["product"], []).append(it)
            products = [{"product": k, "photos": by_product[k]}
                        for k in sorted(by_product, key=lambda x: int(x))]
            self._json({"products": products})
            return
        m = re.match(r"^/img/([A-Za-z0-9_.-]+\.jpg)$", path)
        if m and _EMBED_RE.match(m.group(1)):
            f = self.images_dir / m.group(1)
            if f.exists():
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_error(404)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/tag":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            name, tag = payload.get("name"), payload.get("tag")
        except Exception:
            self._json({"ok": False, "error": "bad payload"}, 400)
            return
        if not _EMBED_RE.match(str(name or "")) or tag not in TAGS:
            self._json({"ok": False, "error": "invalid name/tag"}, 400)
            return
        self.tags[name] = tag
        save_tags(self.out_path, self.tags)
        done = sum(
            1 for f in self.images_dir.glob("image*.jpg")
            if photo_tag(f.name, self.tags)
        )
        self._json({"ok": True, "tagged": done})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images-dir", default=str(DEFAULT_IMAGES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    Handler.images_dir = Path(args.images_dir)
    Handler.out_path = Path(args.out)
    Handler.tags = {k: v for k, v in load_tags(Handler.out_path).items()
                    if (Handler.images_dir / k).exists()}
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Label-type tagger: http://{args.host}:{args.port}")
    print(f"  images : {Handler.images_dir}")
    print(f"  output : {Handler.out_path}")
    print("  keys 1-5 = front/back/side/top/other, auto-advances to next untagged.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())