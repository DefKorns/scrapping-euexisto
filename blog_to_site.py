import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from html import escape
from datetime import datetime
from urllib.parse import urlparse
import re
import os
import hashlib
import json
import argparse
import time

BLOG = None  # set in main() via --url argument
OUT = Path("backup/site")
OUT.mkdir(parents=True, exist_ok=True)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
IMG_DIR_NAME = "images"
FAILED_IMAGES_FILE = OUT / "failed_images.txt"
COMMENTS_CACHE_FILE = OUT / "comments_cache.json"
INITIAL_VISIBLE = 15
LOAD_MORE_STEP = 15


def safe(v):
    return v if isinstance(v, str) else ""


def get_text(entry, tag):
    el = entry.find(f"atom:{tag}", ATOM_NS)
    return el.text if el is not None and el.text else ""


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


def rel_to_root(path: str) -> str:
    depth = path.count("/")
    return "../" * depth + "index.html"


def rel_to_css(path: str) -> str:
    depth = path.count("/")
    return "../" * depth + "style.css"


def posted_by_text(dt, path):
    if not dt:
        return ""
    profile_link = rel_to_root(path).replace(
        "index.html", "profile.html") if path else "profile.html"
    return f'Posted {ordinal_day(dt.day)} {dt.strftime("%B %Y")} by <a href="{profile_link}" target="_blank">euexisto</a>'


def date_ribbon(dt, href=None):
    if not dt:
        return ""
    title = f"{ordinal_day(dt.day)} {dt.strftime('%B %Y')}"
    inner = f"""
        <div class="top ribbon-piece">{dt.strftime('%b')}</div>
        <div class="bottom ribbon-piece">{dt.strftime('%d')}</div>
        <div class="tail">
            <div class="left ribbon-piece"></div>
            <div class="right ribbon-piece"></div>
        </div>
    """
    if href:
        return f'<a href="{href}" class="ribbon date" title="{title}" itemprop="url">{inner}</a>'
    return f'<div class="ribbon date" title="{title}">{inner}</div>'


def load_failed_images():
    if FAILED_IMAGES_FILE.exists():
        return set(FAILED_IMAGES_FILE.read_text(encoding="utf-8").splitlines())
    return set()


def save_failed_image(url):
    with open(FAILED_IMAGES_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def load_comments_cache() -> dict:
    if COMMENTS_CACHE_FILE.exists():
        try:
            return json.loads(COMMENTS_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_comments_cache(cache: dict):
    COMMENTS_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def clean_html_attrs(content_html: str) -> str:
    if not content_html:
        return content_html
    content_html = re.sub(r'\s*onblur="[^"]*"', '', content_html)
    content_html = re.sub(r"\s*onblur='[^']*'", '', content_html)
    content_html = re.sub(r'cursor:\s*hand;?', '', content_html, flags=re.I)
    return content_html


def add_lazy_loading(content_html: str) -> str:
    if not content_html:
        return content_html

    def add_attr(match):
        tag = match.group(0)
        if "loading=" in tag:
            return tag
        return tag[:-1] + ' loading="lazy">' if tag.endswith(">") else tag

    return re.sub(r'<img\b[^>]*>', add_attr, content_html, flags=re.I)


def process_images(content_html, post_path, failed_images, img_dir):
    if not content_html:
        return content_html

    depth = post_path.count("/")
    img_rel_dir = ("../" * depth) + IMG_DIR_NAME

    img_urls = set(re.findall(
        r'(?:src|href)="(https?://[^"]+\.(?:jpg|jpeg|png|gif|webp))"', content_html, re.I))

    for img_url in img_urls:
        if img_url in failed_images:
            continue

        ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
        fname = hashlib.md5(img_url.encode()).hexdigest() + ext
        local_path = img_dir / fname

        if not local_path.exists():
            try:
                resp = requests.get(img_url, timeout=30, headers={
                                    "User-Agent": "Mozilla/5.0"})
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


def fetch_feed(start, retries=3):
    url = (
        f"{BLOG}/feeds/posts/default"
        f"?alt=atom&start-index={start}&max-results=150"
    )
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return r.text
        except Exception as ex:
            print(f"  Falhou feed (tentativa {attempt}/{retries}): {ex}")
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def parse(xml):
    root = ET.fromstring(xml)
    return root.findall("atom:entry", ATOM_NS)


def fetch_comments_from_api(post_id: str) -> list[dict]:
    """Fetch native Blogger comments for a post via Atom feed.
    Returns a list of dicts with JSON-serializable values (dates as ISO strings)."""
    try:
        numeric_id = post_id.split(".")[-1].replace("post-", "")
    except Exception:
        return []

    comments = []
    start = 1

    while True:
        url = (
            f"{BLOG}/feeds/{numeric_id}/comments/default"
            f"?alt=atom&start-index={start}&max-results=100"
        )
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
        except Exception as ex:
            print(f"  Falhou comentários para post {numeric_id}: {ex}")
            break

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            break

        entries = root.findall("atom:entry", ATOM_NS)
        if not entries:
            break

        for e in entries:
            author_el = e.find("atom:author", ATOM_NS)
            author_name = ""
            author_uri = ""
            if author_el is not None:
                name_el = author_el.find("atom:name", ATOM_NS)
                uri_el = author_el.find("atom:uri",  ATOM_NS)
                author_name = name_el.text if name_el is not None else ""
                author_uri = uri_el.text if uri_el is not None else ""

            content_el = e.find("atom:content", ATOM_NS)
            content = content_el.text if content_el is not None else ""

            published = get_text(e, "published")

            comments.append({
                "author":     author_name or "Anónimo",
                "author_uri": author_uri,
                "content":    content or "",
                "published":  published,  # ISO string, kept as-is for JSON
            })

        start += 100

        if len(entries) < 100:
            break

    return comments


def get_comments(post_id: str, cache: dict) -> list[dict]:
    """Return comments for a post, using cache if available, else fetching and caching."""
    if post_id in cache:
        return cache[post_id]

    comments = fetch_comments_from_api(post_id)
    cache[post_id] = comments
    return comments


def render_comments_block(comments: list[dict]) -> str:
    """Render the comments list. Returns empty string if there are none."""
    if not comments:
        return ""

    items = []
    for c in comments:
        author_html = (
            f'<a href="{escape(c["author_uri"])}" target="_blank" rel="noopener">{escape(c["author"])}</a>'
            if c["author_uri"]
            else escape(c["author"])
        )
        dt = None
        try:
            dt = datetime.fromisoformat(c["published"])
        except Exception:
            pass
        date_str = dt.strftime(
            f"{ordinal_day(dt.day)} %B %Y, %H:%M") if dt else ""
        content_html = format_content(c["content"])
        items.append(f"""
        <div class="comment">
            <div class="comment-meta">
                <span class="comment-author">{author_html}</span>
                {"<span class='comment-date'>" + date_str + "</span>" if date_str else ""}
            </div>
            <div class="comment-body">{content_html}</div>
        </div>
        """)

    return f"""
<div class="comments-list">
    {"".join(items)}
</div>
"""


CSS = """
* { box-sizing: border-box; }

body {
    font-family: system-ui, sans-serif;
    margin: 0;
    background: #f5f5f5;
    color: #222;
}

header {
    position: fixed;
    top: 0; left: 0; right: 0;
    background: #111;
    color: white;
    padding: 20px 30px;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

header h1 { margin: 0; font-size: 24px; }
header p  { margin: 5px 0 0; font-size: 14px; color: #bbb; }

.container {
    max-width: 800px;
    margin: auto;
    padding: 20px;
    padding-top: 100px;
}

.post-card {
    position: relative;
    padding: 20px 20px 20px 75px;
    background: white;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.post-content h2 { margin-top: 0; }

.post-content h2 a {
    color: #222;
    text-decoration: none;
}

.post-content h2 a:hover { text-decoration: underline; }

.post-meta {
    margin-top: 15px;
    font-size: 13px;
    color: #888;
}

.post-meta a { color: #0a66c2; text-decoration: none; }

img { max-width: 100%; border-radius: 8px; }

.load-more-wrap {
    display: flex;
    justify-content: center;
    margin: 20px 0 60px;
}

#loadMoreBtn {
    padding: 12px 24px;
    border: none;
    border-radius: 6px;
    background: #111;
    color: white;
    cursor: pointer;
    font-size: 14px;
}

#loadMoreBtn:hover { background: #333; }

/* ===================== RIBBON DATE ===================== */

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

.ribbon.date:visited { color: #eee; }

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

.ribbon .bottom { font-size: 17px; padding: 5px 0; }

.ribbon .tail { height: 10px; overflow: hidden; position: relative; }

.ribbon .tail .left,
.ribbon .tail .right {
    height: 10px;
    position: absolute;
    top: -10px;
    width: 50px;
}

.ribbon .tail .left  { left: -9px;  transform: rotate(-25deg); }
.ribbon .tail .right { right: -9px; transform: rotate(25deg);  }


.comments-list {
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid #eee;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

.comment {
    background: #f9f9f9;
    border-left: 3px solid #ddd;
    border-radius: 0 6px 6px 0;
    padding: 10px 14px;
}

.comment-meta {
    display: flex;
    gap: 12px;
    align-items: baseline;
    margin-bottom: 6px;
    font-size: 13px;
}

.comment-author { font-weight: 600; color: #222; }
.comment-author a { color: #0a66c2; text-decoration: none; }
.comment-author a:hover { text-decoration: underline; }
.comment-date { color: #aaa; font-size: 12px; }

.comment-body { font-size: 14px; line-height: 1.6; }
.comment-body p { margin: 0 0 8px; }
.comment-body p:last-child { margin-bottom: 0; }
"""


def page_head(title: str, css_path: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{css_path}">
</head>"""


HEADER_HTML = """
<header>
    <h1>Eu existo</h1>
    <p>A esplanada é, a seguir à roda, a melhor invenção do homem.</p>
</header>
"""


def main():
    global BLOG

    parser = argparse.ArgumentParser(
        description="Gera um backup estático de um blog Blogger.")
    parser.add_argument("-url", "--url", required=True,
                        help="URL do blog, ex: https://someblog.blogspot.com")
    parser.add_argument("--initial-visible", type=int, default=INITIAL_VISIBLE,
                        help="Posts visíveis inicialmente no index")
    parser.add_argument("--load-more-step", type=int, default=LOAD_MORE_STEP,
                        help="Posts adicionados por clique em 'Carregar mais'")
    args = parser.parse_args()

    BLOG = args.url.rstrip("/")
    initial_visible = args.initial_visible
    load_more_step = args.load_more_step

    failed_images = load_failed_images()
    comments_cache = load_comments_cache()

    img_dir = OUT / IMG_DIR_NAME
    img_dir.mkdir(parents=True, exist_ok=True)

    # Write the shared CSS file once
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    print("style.css gerado.")

    posts = []
    start = 1

    print("A ler feed de posts...")

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

            post_id = get_text(e, "id")

            posts.append({
                "id":           post_id,
                "title":        get_text(e, "title") or "",
                "published":    get_text(e, "published") or "",
                "url":          url or "",
                "content_html": content or ""
            })

        start += 150

    print(f"Posts encontrados: {len(posts)}")
    posts.sort(key=lambda p: p["published"], reverse=True)

    index_blocks = []

    for i, p in enumerate(posts):

        url = safe(p["url"])
        path = url_to_path(url)
        title = safe(p["title"])

        raw_content = safe(p["content_html"])
        raw_content = clean_html_attrs(raw_content)
        raw_content = process_images(raw_content, path, failed_images, img_dir)
        raw_content = add_lazy_loading(raw_content)
        content = format_content(raw_content)

        dt = None
        try:
            dt = datetime.fromisoformat(p["published"])
        except Exception:
            pass

        post_id = safe(p["id"])
        if post_id in comments_cache:
            print(
                f"  [{i+1}/{len(posts)}] Comentários em cache: {title[:50] or path}")
        else:
            print(
                f"  [{i+1}/{len(posts)}] A obter comentários: {title[:50] or path}")
        comments = get_comments(post_id, comments_cache)
        print(f"    → {len(comments)} comentário(s)")

        if (i + 1) % 10 == 0:
            save_comments_cache(comments_cache)

        comments_html = render_comments_block(comments)

        title_html_index = f'<h2><a href="{path}">{escape(title)}</a></h2>' if title else ""
        title_html_post = f'<h2>{escape(title)}</h2>' if title else ""

        # ----- index card (sem comentários para não sobrecarregar) -----
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

        full_path = OUT / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        page_title = escape(title) or "Eu existo"
        css_rel = rel_to_css(path)
        back_link = rel_to_root(path)

        post_page_html = f"""{page_head(page_title, css_rel)}
<body>

{HEADER_HTML}

<div class="container">
<article class="post-card">
    {date_ribbon(dt)}
    <div class="post-content">
        {title_html_post}
        {content}
        <div class="post-meta">
            {posted_by_text(dt, path)}
        </div>
        {comments_html}
        <p style="margin-top:20px"><a href="{back_link}">← voltar ao arquivo</a></p>
    </div>
</article>
</div>

</body>
</html>
"""
        full_path.write_text(post_page_html, encoding="utf-8")

    index_html = f"""{page_head("Eu existo — Arquivo", "style.css")}
<body>

{HEADER_HTML}

<div class="container">
    <div id="posts">
{''.join(index_blocks)}
    </div>

    <div class="load-more-wrap">
        <button id="loadMoreBtn">Carregar mais</button>
    </div>
</div>

<script>
const STEP    = {load_more_step};
const INITIAL = {initial_visible};
const cards   = document.querySelectorAll("#posts > .post-card");
const btn     = document.getElementById("loadMoreBtn");
let visible   = 0;

function showMore() {{
    const next = Math.min(visible + (visible === 0 ? INITIAL : STEP), cards.length);
    for (let i = visible; i < next; i++) {{
        cards[i].style.display = "block";
    }}
    visible = next;
    if (visible >= cards.length) btn.style.display = "none";
}}

cards.forEach(c => c.style.display = "none");
showMore();
btn.addEventListener("click", showMore);
</script>

</body>
</html>
"""

    (OUT / "index.html").write_text(index_html, encoding="utf-8")
    print(f"\n{len(posts)} posts gerados.")

    save_comments_cache(comments_cache)
    print("comments_cache.json actualizado.")

    print("SITE GERADO EM:", OUT.resolve())


if __name__ == "__main__":
    main()
