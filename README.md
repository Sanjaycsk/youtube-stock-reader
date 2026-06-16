# YouTube Stock Reader

Trusted-source signal for the daily stock brief. Many investors follow specific
YouTube analysts and act on them — those views add a layer on top of what
financial blogs/news report. This project captures that layer.

## The problem it solves

YouTube blocks transcript fetches from **datacenter IPs** (cloud / CI), but
allows them from **residential IPs** (home). The analysis runs in Anthropic's
cloud (a datacenter IP), so it can't read YouTube directly.

## The split

```
  HOME PC (residential IP)            PUBLIC GITHUB                ANTHROPIC CLOUD (datacenter)
  ────────────────────────           ─────────────                ───────────────────────────
  fetch_transcripts.py  ──push──▶  data/transcripts.json  ──raw URL──▶  daily routine reads it
  (Task Scheduler, daily)          { last_updated, videos[] }            + live web research
                                                                         = ranked brief
```

- **Producer (here):** `fetch_transcripts.py` runs at home, pulls the newest
  transcripts from the channels in `channels.json`, and writes
  `data/transcripts.json`. `run_daily.ps1` then commits + pushes it.
- **Consumer (cloud):** the InvestAI routine `WebFetch`es the raw
  `data/transcripts.json`, uses the channel views as a trusted signal **on top
  of** web research, and writes the brief.

## Freshness rule

Each video carries a `fetched_date`, and the file has a top-level
`last_updated`. **If `last_updated` is not today**, the cloud brief says:
> "Suggestions are not based on YouTube today — financial blogs only."
So you always know whether the YouTube layer was included.

## Setup (one time, on your home PC)

```powershell
cd youtube-stock-reader
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python fetch_transcripts.py        # writes data/transcripts.json
```

Then schedule `run_daily.ps1` in **Task Scheduler** to run each morning
(~08:00 IST), before the cloud routine at 08:30 IST.

## Files

```
fetch_transcripts.py   producer — fetch newest transcripts -> data/transcripts.json
channels.json          trusted channels (te / ta / en)
run_daily.ps1          fetch + git commit + push (for Task Scheduler)
data/transcripts.json  the table the cloud reads (public)
```
