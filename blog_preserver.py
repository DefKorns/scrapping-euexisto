import requests
import xml.etree.ElementTree as ET
from pathlib import Path
import json
import time

BLOG = "https://euestouvivo.blogspot.com"
OUT = Path("backup")
OUT.mkdir(exist_ok=True)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

def get_feed(start):
    url = f"{BLOG}/feeds/posts/default?alt=atom&start-index={start}&max-results=150"
    return requests.get(url, timeout=60).text

def parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    return root.findall("atom:entry", ATOM_NS)

def get_text(node, tag):
    el = node.find(f"atom:{tag}", ATOM_NS)
    return el.text if el is not None else ""

def main():

    all_posts = []
    start = 1

    while True:

        xml = get_feed(start)
        entries = parse_feed(xml)

        if not entries:
            break

        for e in entries:

            content_node = e.find("atom:content", ATOM_NS)

            post = {
                "title": get_text(e, "title"),
                "published": get_text(e, "published"),
                "updated": get_text(e, "updated"),
                "url": next(
                    (l.attrib["href"] for l in e.findall("atom:link", ATOM_NS)
                     if l.attrib.get("rel") == "alternate"),
                    ""
                ),
                "categories": [
                    c.attrib.get("term", "")
                    for c in e.findall("atom:category", ATOM_NS)
                ],
                "content_html": content_node.text if content_node is not None else ""
            }

            all_posts.append(post)

        start += 150
        time.sleep(0.3)

    # guardar tudo
    with open(OUT / "archive.json", "w", encoding="utf-8") as f:
        json.dump(all_posts, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(all_posts)} posts guardados")

if __name__ == "__main__":
    main()