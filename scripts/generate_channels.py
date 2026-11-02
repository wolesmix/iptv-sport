import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PLAYLIST_URL = (
    "https://raw.githubusercontent.com/"
    "wolesmix/iptv-sport/refs/heads/main/sports-iptv.m3u"
)

GUIDES_URL = "https://iptv-org.github.io/api/guides.json"

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_XML = ROOT / "epg-channels.xml"
OUTPUT_REPORT = ROOT / "epg-unmatched.json"

USER_AGENT = "BIONET-IPTV-EPG-Generator/1.0"


def download_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def parse_attributes(line):
    pattern = r'([\w-]+)="([^"]*)"'
    return {
        key.lower(): value.strip()
        for key, value in re.findall(pattern, line)
    }


def parse_playlist(content):
    channels = []
    current = None

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if line.startswith("#EXTINF:"):
            attrs = parse_attributes(line)

            name = line.rsplit(",", 1)[-1].strip()

            current = {
                "id": attrs.get("tvg-id", "").strip(),
                "name": name or attrs.get("tvg-name", "Unknown"),
                "group": attrs.get("group-title", ""),
                "logo": attrs.get("tvg-logo", "")
            }

        elif line and not line.startswith("#") and current:
            if current["id"]:
                channels.append(current)

            current = None

    return channels


def normalize(value):
    return str(value or "").strip().casefold()


def main():
    print("====================================")
    print(" BIONET SPORTS EPG GENERATOR")
    print("====================================")

    print("[1] Mengambil playlist...")
    playlist_text = download_text(PLAYLIST_URL)
    playlist_channels = parse_playlist(playlist_text)

    print("Channel playlist:", len(playlist_channels))

    print("[2] Mengambil database EPG...")
    guides = json.loads(download_text(GUIDES_URL))

    print("Data panduan EPG:", len(guides))

    # Index berdasarkan channel dan feed.
    exact_index = {}
    channel_index = {}

    for guide in guides:
        channel_id = normalize(guide.get("channel"))
        feed = normalize(guide.get("feed"))

        site = guide.get("site")
        site_id = guide.get("site_id")
        lang = guide.get("lang") or "en"
        sources = guide.get("sources") or []

        if not channel_id or not site or not site_id or not sources:
            continue

        record = {
            "site": site,
            "site_id": site_id,
            "lang": lang,
            "channel": channel_id,
            "feed": feed
        }

        full_id = channel_id
        if feed:
            full_id += "@" + feed

        exact_index.setdefault(full_id, []).append(record)
        channel_index.setdefault(channel_id, []).append(record)

    xml_root = ET.Element("channels")

    matched = []
    unmatched = []
    used = set()

    print("[3] Mencocokkan ID channel...")

    for channel in playlist_channels:
        tvg_id = channel["id"]
        normalized_id = normalize(tvg_id)

        candidates = exact_index.get(normalized_id, [])

        # Fallback hanya jika channel memiliki satu pilihan feed.
        if not candidates and "@" not in normalized_id:
            possible = channel_index.get(normalized_id, [])

            unique = {
                (x["site"], x["site_id"], x["feed"])
                for x in possible
            }

            if len(unique) == 1:
                candidates = possible

        if not candidates:
            unmatched.append({
                "tvg_id": tvg_id,
                "name": channel["name"],
                "group": channel["group"],
                "reason": "Tidak ditemukan sumber EPG yang cocok"
            })
            continue

        # Satu ID playlist bisa memiliki beberapa sumber.
        # Pilih satu sumber agar jadwal tidak terduplikasi.
        candidates = sorted(
            candidates,
            key=lambda x: (
                x["lang"] != "en",
                x["site"],
                x["site_id"]
            )
        )

        selected = candidates[0]

        unique_key = (
            normalized_id,
            selected["site"],
            selected["site_id"]
        )

        if unique_key in used:
            continue

        used.add(unique_key)

        ET.SubElement(
            xml_root,
            "channel",
            {
                "site": selected["site"],
                "site_id": selected["site_id"],
                "lang": selected["lang"],
                "xmltv_id": tvg_id
            }
        ).text = channel["name"]

        matched.append({
            "tvg_id": tvg_id,
            "name": channel["name"],
            "site": selected["site"],
            "site_id": selected["site_id"]
        })

    tree = ET.ElementTree(xml_root)
    ET.indent(tree, space="  ")
    tree.write(
        OUTPUT_XML,
        encoding="utf-8",
        xml_declaration=True
    )

    report = {
        "playlist": PLAYLIST_URL,
        "total_playlist_channels": len(playlist_channels),
        "matched_channels": len(matched),
        "unmatched_channels": len(unmatched),
        "matched": matched,
        "unmatched": unmatched
    }

    OUTPUT_REPORT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("------------------------------------")
    print("Total playlist :", len(playlist_channels))
    print("Cocok EPG      :", len(matched))
    print("Belum cocok    :", len(unmatched))
    print("------------------------------------")

    if not matched:
        print("ERROR: Tidak ada channel yang cocok.")
        sys.exit(1)

    print("File dibuat:")
    print(OUTPUT_XML)
    print(OUTPUT_REPORT)


if __name__ == "__main__":
    main()
