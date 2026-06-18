"""
YouTube Stock Reader — PRODUCER (run on a RESIDENTIAL IP, e.g. your home PC).

Why this exists:
  YouTube blocks transcript fetches from datacenter IPs (cloud / CI / GitHub
  Actions) but allows them from home connections. The analysis runs in
  Anthropic's cloud (a datacenter IP), so it can't read YouTube directly.

  This script runs at HOME, pulls the latest transcripts from your trusted
  stock channels, and writes them to data/transcripts.json. That file is pushed
  to a PUBLIC GitHub repo so the cloud routine can read it via the raw URL —
  the cloud never touches YouTube itself.

Run:
    python fetch_transcripts.py
Then commit + push (run_daily.ps1 does the fetch + push in one step).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import date, datetime, timezone

import requests

BASE = pathlib.Path(__file__).resolve().parent
CHANNELS_PATH = BASE / "channels.json"
DATA_PATH = BASE / "data" / "transcripts.json"

UPLOADS_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockReader/1.0)"}

MAX_VIDEOS_PER_CHANNEL = 4    # newest N uploads per channel
KEEP_DAYS = 5                 # keep a rolling 5-day window of transcripts
MAX_TRANSCRIPT_CHARS = 5000   # cap each transcript so the cloud file stays lean


def load_channels() -> list[dict]:
    with open(CHANNELS_PATH, encoding="utf-8") as fh:
        return json.load(fh).get("channels", [])


def resolve_channel_id(url: str) -> str | None:
    m = re.search(r"/channel/(UC[\w-]+)", url)
    if m:
        return m.group(1)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]+)"', r.text)
        if m:
            return m.group(1)
        m = re.search(r"/channel/(UC[\w-]+)", r.text)
        return m.group(1) if m else None
    except Exception as exc:
        print(f"  ! could not resolve channel id for {url}: {exc}")
        return None


def recent_videos(channel_id: str, limit: int) -> list[dict]:
    import feedparser
    try:
        r = requests.get(UPLOADS_FEED.format(cid=channel_id), headers=HEADERS, timeout=20)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        out = []
        for e in parsed.entries[:limit]:
            vid = e.get("yt_videoid")
            if not vid:
                m = re.search(r"v=([\w-]{11})", e.get("link", ""))
                vid = m.group(1) if m else None
            if vid:
                out.append({
                    "video_id": vid,
                    "title": e.get("title", ""),
                    "published": e.get("published", ""),
                })
        return out
    except Exception as exc:
        print(f"  ! uploads feed failed for {channel_id}: {exc}")
        return []


def fetch_transcript(video_id: str, languages: list[str]) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        # 0.6.x classmethod API
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
            return " ".join(p["text"] for p in parts)
        # 1.x instance API
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
        return " ".join(s.text for s in fetched)
    except Exception as exc:
        first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        print(f"  ! transcript unavailable for {video_id}: {first}")
        return ""


def load_existing() -> list[dict]:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8")).get("videos", [])
        except Exception:
            return []
    return []


def main() -> None:
    today = date.today().isoformat()
    channels = load_channels()
    existing = {v["video_id"]: v for v in load_existing()}
    print(f"Fetching transcripts for {len(channels)} channel(s) — {today}")

    new_count = 0
    for ch in channels:
        name = ch.get("name", "?")
        lang = ch.get("language", "en")
        langs = [lang, "en"] if lang != "en" else ["en"]
        print(f"- {name} ({lang})")
        for url in ch.get("urls", []):
            cid = resolve_channel_id(url)
            if not cid:
                continue
            for v in recent_videos(cid, MAX_VIDEOS_PER_CHANNEL):
                vid = v["video_id"]
                if vid in existing and existing[vid].get("transcript"):
                    continue  # already captured in a previous run
                text = fetch_transcript(vid, langs)
                if not text:
                    continue
                existing[vid] = {
                    "video_id": vid,
                    "channel": name,
                    "language": lang,
                    "title": v["title"],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "published": v["published"],
                    "fetched_date": today,
                    "transcript": text[:MAX_TRANSCRIPT_CHARS],
                }
                new_count += 1
                print(f"    + {v['title'][:60]} ({len(text)} chars)")

    # Prune entries older than KEEP_DAYS; newest first.
    def keep(v: dict) -> bool:
        try:
            d = datetime.fromisoformat(v.get("fetched_date", today)).date()
        except Exception:
            return True
        return (date.today() - d).days <= KEEP_DAYS

    videos = sorted(
        (v for v in existing.values() if keep(v)),
        key=lambda v: v.get("fetched_date", ""),
        reverse=True,
    )

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": today,
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "channel_count": len(channels),
        "video_count": len(videos),
        "videos": videos,
    }
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {DATA_PATH.name}: {len(videos)} videos ({new_count} new). last_updated={today}")


if __name__ == "__main__":
    # Windows consoles default to cp1252; force UTF-8 for Telugu/Tamil titles.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
