import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from html import escape
from datetime import datetime
from urllib.parse import urljoin, urlparse
import re
import os
import hashlib

# ============================================================
# CONFIG
# ============================================================

BLOG = "https://euestouvivo.blogspot.com"
OUT = Path("backup/site")
OUT.mkdir(parents=True, exist_ok=True)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
IMG_DIR_NAME = "images"
FAILED_IMAGES_FILE = OUT / "failed_images.txt"
INITIAL_VISIBLE = 15
LOAD_MORE_STEP = 15

# ============================================================
# HELPERS
# ============================================================

def safe(v):
    return v if isinstance(v, str) else ""

def get_text(entry, tag):
    el = entry.find(f"atom:{tag}", ATOM_NS)
    return el.text if el is not None and el.text else ""

def clean_text(html: str) -> str:
    return re.sub("<[^<]+?>", "", html or "")

def format_content(html: str) -> str:
    if "<" not in (html or ""):
        return "<p>" + html.replace("\n", "<br>") + "</p>"
    return html

def ordinal_day(d: int) -> str:
    if 11 <= d <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"{d}{suffix}"

def url_to_path(url: str) -> str:
    try:
        path = urlparse(url).path.strip("/")
        return f"posts/{path}" if path else "posts/post.html"
    except:
        return "posts/post.html"

def rel_to_root(path: str):
    depth = path.count("/")
    return "../" * depth + "index.html"

def posted_by_text(dt, path):
    if not dt:
        return ""
    profile_link = rel_to_root(path).replace("index.html", "profile.html") if path else "profile.html"
    return f'Posted {ordinal_day(dt.day)} {dt.strftime("%B %Y")} by <a href="{profile_link}" target="_blank">euexisto</a>'

def date_ribbon(dt, href):
    if not dt:
        return ""
    return f"""
    <a href="{href}" class="ribbon date" title="{ordinal_day(dt.day)} {dt.strftime('%B %Y')}" itemprop="url">
        <div class="top ribbon-piece">{dt.strftime('%b')}</div>
        <div class="bottom ribbon-piece">{dt.strftime('%d')}</div>
        <div class="tail">
            <div class="left ribbon-piece"></div>
            <div class="right ribbon-piece"></div>
        </div>
    </a>
    """

# ============================================================
# FAILED IMAGES CACHE
# ============================================================

def load_failed_images():
    if FAILED_IMAGES_FILE.exists():
        return set(FAILED_IMAGES_FILE.read_text(encoding="utf-8").splitlines())
    return set()

def save_failed_image(url):
    with open(FAILED_IMAGES_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")

# ============================================================
# CONTENT CLEANUP / IMAGES
# ============================================================

def clean_html_attrs(content_html: str) -> str:
    if not content_html:
        return content_html

    content_html = re.sub(r'\s*onblur="[^"]*"', '', content_html)
    content_html = re.sub(r"\s*onblur='[^']*'", '', content_html)
    content_html = re.sub(r'cursor:\s*hand;?', '', content_html, flags=re.I)

    return content_html

def add_lazy_loading(content_html: str) -> str:
    """Adiciona loading='lazy' a todas as <img> que ainda não tenham."""
    if not content_html:
        return content_html

    def add_attr(match):
        tag = match.group(0)
        if "loading=" in tag:
            return tag
        return tag[:-1] + ' loading="lazy">' if tag.endswith(">") else tag

    return re.sub(r'<img\b[^>]*>', add_attr, content_html, flags=re.I)

def process_images(content_html, post_path, failed_images):
    if not content_html:
        return content_html

    depth = post_path.count("/")
    img_rel_dir = ("../" * depth) + IMG_DIR_NAME
    img_dir = OUT / IMG_DIR_NAME
    img_dir.mkdir(parents=True, exist_ok=True)

    img_urls = set(re.findall(r'(?:src|href)="(https?://[^"]+\.(?:jpg|jpeg|png|gif|webp))"', content_html, re.I))

    for img_url in img_urls:
        if img_url in failed_images:
            continue

        ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
        fname = hashlib.md5(img_url.encode()).hexdigest() + ext
        local_path = img_dir / fname

        if not local_path.exists():
            try:
                resp = requests.get(img_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
            except Exception as ex:
                print(f"Falhou imagem {img_url}: {ex}")
                failed_images.add(img_url)
                save_failed_image(img_url)
                continue

        local_url = f"{img_rel_dir}/{fname}"
        content_html = content_html.replace(f'"{img_url}"', f'"{local_url}"')

    return content_html

# ============================================================
# FETCH FEED
# ============================================================

def fetch_feed(start):
    url = (
        f"{BLOG}/feeds/posts/default"
        f"?alt=atom&start-index={start}&max-results=150"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text

def parse(xml):
    root = ET.fromstring(xml)
    return root.findall("atom:entry", ATOM_NS)

# ============================================================
# SHARED CSS
# ============================================================

CSS = """
* { box-sizing: border-box; }

body {
    font-family: system-ui, sans-serif;
    margin:0;
    background:#f5f5f5;
    color:#222;
}

header {
    position: fixed;
    top:0;
    left:0;
    right:0;
    background:#111;
    color:white;
    padding:20px 30px;
    z-index:100;
    box-shadow:0 2px 8px rgba(0,0,0,0.2);
}

header h1 {
    margin:0;
    font-size:24px;
}

header p {
    margin:5px 0 0;
    font-size:14px;
    color:#bbb;
}

.container {
    max-width:800px;
    margin:auto;
    padding:20px;
    padding-top:100px;
}

.post-card {
    position: relative;
    padding: 20px 20px 20px 75px;
    background:white;
    border-radius:10px;
    overflow:hidden;
    margin-bottom:20px;
    box-shadow:0 2px 8px rgba(0,0,0,0.06);
}

.post-content h2 {
    margin-top:0;
}

.post-content h2 a {
    color:#222;
    text-decoration:none;
}

.post-content h2 a:hover {
    text-decoration:underline;
}

.post-meta {
    margin-top:15px;
    font-size:13px;
    color:#888;
}

.post-meta a {
    color:#0a66c2;
    text-decoration:none;
}

img {
    max-width:100%;
    border-radius:8px;
}

.load-more-wrap {
    display:flex;
    justify-content:center;
    margin: 20px 0 60px;
}

#loadMoreBtn {
    padding:12px 24px;
    border:none;
    border-radius:6px;
    background:#111;
    color:white;
    cursor:pointer;
    font-size:14px;
}

#loadMoreBtn:hover {
    background:#333;
}

.ribbon.date {
    position: absolute;
    left: 20px;
    top: 20px;
    color: #eee;
    text-decoration: none;
    cursor: pointer;
    display: inline-block;
    text-align: center;
    width: 35px;
}

.ribbon.date:visited {
    color: #eee;
}

.ribbon .top {
    border-bottom: solid 1px rgba(255,255,255,0.6);
    border-radius: 1px 1px 0 0;
    font-size: 11px;
    padding: 4px 0;
    position: relative;
    text-transform: uppercase;
}

.ribbon .ribbon-piece {
    background-color: rgba(102,102,102,1);
    box-shadow: 0 0 5px rgba(0,0,0,0.2);
    transition: background-color 0.5s ease-in;
}

.ribbon .bottom {
    font-size: 17px;
    padding: 5px 0;
}

.ribbon .tail {
    height: 10px;
    overflow: hidden;
    position: relative;
}

.ribbon .tail .left,
.ribbon .tail .right {
    height: 10px;
    position: absolute;
    top: -10px;
    width: 50px;
}

.ribbon .tail .left {
    left: -9px;
    transform: rotate(-25deg);
}

.ribbon .tail .right {
    right: -9px;
    transform: rotate(25deg);
}
"""

# ============================================================
# BUILD SITE
# ============================================================

def main():

    failed_images = load_failed_images()

    posts = []
    start = 1

    print("A ler feed...")

    while True:
        xml = fetch_feed(start)
        entries = parse(xml)

        if not entries:
            break

        for e in entries:
            content_node = e.find("atom:content", ATOM_NS)
            content = content_node.text if content_node is not None else ""

            url = ""
            for l in e.findall("atom:link", ATOM_NS):
                if l.attrib.get("rel") == "alternate":
                    url = l.attrib.get("href", "")

            posts.append({
                "title": get_text(e, "title") or "",
                "published": get_text(e, "published") or "",
                "url": url or "",
                "content_html": content or ""
            })

        start += 150

    print(f"Posts encontrados: {len(posts)}")

    posts.sort(key=lambda p: p["published"], reverse=True)

    # ========================================================
    # POST BLOCKS + INDIVIDUAL PAGES
    # ========================================================

    index_blocks = []

    for p in posts:

        url = safe(p["url"])
        path = url_to_path(url)

        title = safe(p["title"])

        raw_content = safe(p["content_html"])
        raw_content = clean_html_attrs(raw_content)
        raw_content = process_images(raw_content, path, failed_images)
        raw_content = add_lazy_loading(raw_content)
        content = format_content(raw_content)

        dt = None
        try:
            dt = datetime.fromisoformat(p["published"])
        except:
            pass

        title_html_index = f'<h2><a href="{path}">{escape(title)}</a></h2>' if title else ""
        title_html_post = f'<h2>{escape(title)}</h2>' if title else ""

        # ----- index card -----
        index_blocks.append(f"""
        <article class="post-card">
            {date_ribbon(dt, path)}
            <div class="post-content">
                {title_html_index}
                {content}
                <div class="post-meta">
                    {posted_by_text(dt, "")}
                </div>
            </div>
        </article>
        """)

        # ----- individual post page -----
        full_path = OUT / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        page_title = escape(title) or "Eu existo"

        post_page_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
{CSS}
</style>
</head>
<body>

<header>
<h1>Eu existo</h1>
<p>A esplanada é, a seguir à roda, a melhor invenção do homem.</p>
</header>

<div class="container">
<article class="post-card">
    {date_ribbon(dt, rel_to_root(path))}
    <div class="post-content">
        {title_html_post}
        {content}
        <div class="post-meta">
            {posted_by_text(dt, path)}
        </div>
        <p style="margin-top:20px"><a href="{rel_to_root(path)}">← voltar ao arquivo</a></p>
    </div>
</article>
</div>

</body>
</html>
"""

        full_path.write_text(post_page_html, encoding="utf-8")

    # ========================================================
    # INDEX PAGE (single page, incremental render)
    # ========================================================

    index_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Eu existo — Arquivo</title>
<style>
{CSS}
</style>
</head>
<body>

<header>
<h1>Eu existo</h1>
<p>A esplanada é, a seguir à roda, a melhor invenção do homem.</p>
</header>

<div class="container">
    <div id="posts">
{''.join(index_blocks)}
    </div>

    <div class="load-more-wrap">
        <button id="loadMoreBtn">Carregar mais</button>
    </div>
</div>

<script>
const STEP = {LOAD_MORE_STEP};
const INITIAL = {INITIAL_VISIBLE};
const cards = document.querySelectorAll("#posts > .post-card");
const btn = document.getElementById("loadMoreBtn");
let visible = 0;

function showMore() {{
    const next = Math.min(visible + (visible === 0 ? INITIAL : STEP), cards.length);
    for (let i = visible; i < next; i++) {{
        cards[i].style.display = "block";
    }}
    visible = next;
    if (visible >= cards.length) {{
        btn.style.display = "none";
    }}
}}

cards.forEach(c => c.style.display = "none");
showMore();

btn.addEventListener("click", showMore);
</script>

</body>
</html>
"""

    (OUT / "index.html").write_text(index_html, encoding="utf-8")

    print(f"\n{len(posts)} posts gerados (index.html + páginas individuais).")

    print("SITE GERADO EM:", OUT.resolve())

# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()