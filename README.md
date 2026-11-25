# Sympany — Social Media Listening & Media Compliance Platform

A responsible‑AI platform for **Sympany**, the Swiss health insurer headquartered in Basel
(https://www.sympany.ch), that:

1. **Monitors** public social & community platforms (Instagram, Facebook, YouTube, X, Quora,
   Google Play / App Store reviews of the **mySympany** app, Google Maps reviews of Sympany
   agencies) for mentions of Sympany, classifies each with an LLM into a
   **reputational / compliance‑conduct / market‑abuse / cyber‑operational** risk taxonomy,
   maps findings to **RACM/KRI**, and surfaces them in a branded analytics console.
2. **Benchmarks** Sympany against the Swiss health insurers **CSS, Helsana, SWICA and Visana**
   (Share of Voice, sentiment, engagement, followers and reply times).
3. **Screens** marketing creatives (text, image, **video**) against **FINMA** supervisory
   expectations and Swiss insurance advertising rules in the **Media Compliance Analyzer**
   (hidden by default), with OCR + speech transcription, a config‑driven rule engine, and an
   append‑only audit register.

Everything runs as **one container image** (React SPA + FastAPI API) — on AWS (ECS Fargate in
eu-central-2 Zurich, Amazon Bedrock, Transcribe, DynamoDB) or locally. Sign-in is built into
the app (username + password; no Cognito / SSO). See **`DEPLOY.md`**.

---

## Table of contents
- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick start (local dev)](#quick-start-local-dev)
- [Run as a single container](#run-as-a-single-container)
- [Configuration](#configuration)
- [Data collection & the knowledge base](#data-collection--the-knowledge-base)
- [Video / reel sentiment](#video--reel-sentiment)
- [Media Compliance Analyzer](#media-compliance-analyzer)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Deployment (AWS)](#deployment-aws)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Security, privacy & legal](#security-privacy--legal)

---

## Features

**Listening & risk**
- Multi‑channel collection via **Apify** actors (Instagram, Facebook, YouTube channel + Shorts,
  X, Quora, Google Play, App Store, Google Maps) and **Bright Data** (YouTube keyword search).
- First‑party monitoring of **Sympany's own accounts** (Instagram `@sympany`, Facebook
  `facebook.com/sympany`, the Sympany YouTube channel), scanned first in every scan.
- Sympany‑scoped **relevance filter**, **sentiment + AI risk classification** (Amazon Bedrock),
  **severity** scoring and **RACM/KRI** mapping.
- **Collection window** — only content published since the configured date (default
  **10 May 2026**) is stored; each scan catches up on the days since the previous one.
- **Competitor benchmark** — CSS, Helsana, SWICA and Visana collected on the same sources.

**Analytics console** — Overview, Listening, Influencers & UGC, Topics & Themes, Content
Performance, PR & Reputation, Campaign Analytics, Marketing Report, Competition Benchmarking
(Share of Voice), Keyword Campaigns.

**Media Compliance Analyzer** — screen content / image / video creatives against FINMA /
Swiss insurance advertising rules; frame‑by‑frame OCR + voice‑over transcription (German,
French, Italian, English); Approve / Advisory / Manual‑review / Reject verdict; append‑only
audit register; officer‑managed Do's & Don'ts.

**Video / reel understanding** — Instagram Reels and YouTube clips are **transcribed**
so their sentiment reflects what was said, not just the caption. A single video can also be
analysed on demand by URL (`POST /api/analyze/video`).

---

## Architecture

```
  DATA SOURCES     Instagram · Facebook · X · Quora · YouTube channel   (Apify actors)
                   Google Play · App Store · Google Maps reviews        (Apify actors)
                   YouTube keyword search                               (Bright Data)
                   competitors CSS · Helsana · SWICA · Visana           (same sources)
                          |
                          v
  CONNECTORS       normalise every payload -> shared "Post" model
                          |
                          v
  PIPELINE         ingest -> collection-window filter -> relevance filter
                   -> video transcript enrichment (IG/YouTube)
                   -> sentiment + AI risk classification (Amazon Bedrock)
                   -> severity -> case (+ RACM/KRI) -> escalation
                          |
                          v
  API + STORES     FastAPI /api/*  <->  JSON / JSONL knowledge base
                          |            (Amazon DynamoDB: posts, cases, settings, audit)
                          v
  WEB CONSOLE      React SPA (dashboards, reports, Media Compliance)

  MEDIA COMPLIANCE (parallel) creative -> OCR + transcription -> rule engine -> verdict -> audit register
```

The Python backend does **raw extraction only**; the compliance **rule/decision engine is a
pure TypeScript function** (`frontend/src/compliance/`), so verdicts are reproducible.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18 + TypeScript, Vite, Vitest; hand‑built SVG charts |
| Backend | Python 3.12, FastAPI, Uvicorn; PyYAML + python‑dotenv |
| AI / ML | **Amazon Bedrock** (In‑Region, eu‑central‑2) — Qwen3 235B (risk/sentiment/language), Qwen3 VL 235B (OCR); **Amazon Transcribe** streaming (speech‑to‑text); local VADER pre‑pass. No non‑AWS AI service is used |
| Media | ffmpeg (frames + audio), Pillow / pillow‑heif (image normalisation), youtube‑transcript‑api |
| Data providers | Apify actors (Instagram, Facebook, YouTube, X, Quora, Google Play, App Store, Google Maps), Bright Data (YouTube keyword search) |
| Deploy | Docker (multi‑stage) built by CodeBuild → Amazon ECR → ECS Fargate (2 web tasks; scans run inside them on Run Scan, optionally daily via `scan.daily_at`, Swiss time), ALB + WAF; app sign‑in (PBKDF2 password hashes, signed session cookie) |
| Storage | Amazon DynamoDB (data table with TTL + audit table); JSON files under `data/` in local mode |

---

## Prerequisites

- **Python 3.11+** and **Node.js 20+**
- **ffmpeg** on the PATH (video frame sampling + audio extraction)
  - macOS `brew install ffmpeg` · Debian/Ubuntu `sudo apt-get install -y ffmpeg`
  - *(optional, for iPhone HEIC images)* `libheif` (`sudo apt-get install -y libheif1`)
- API keys (see [Configuration](#configuration)):
  - **AWS credentials** that can call the two Bedrock models and Amazon Transcribe in eu‑central‑2
  - **Bright Data** and **Apify** (required for live collection)

---

## Quick start (local dev)

```bash
# 1. Clone
git clone <your-repo-url>
cd <repository folder>

# 2. Backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Secrets
cp .env.example .env                 # then edit .env (AWS credentials come from your AWS profile)

# 4. Run the API (serves /api on :8000)
uvicorn src.api:app --reload --port 8000
```

In a second terminal:

```bash
# 5. Frontend dev server (proxies /api -> :8000)
cd frontend
npm install
npm run dev                          # open http://localhost:5173
```

Open **http://localhost:5173**. The dashboard loads whatever is stored in the knowledge base.
Click **Run Scan** to collect & classify fresh content (billable — calls Bright Data/Apify/Amazon Bedrock).

> The current page is kept in the URL hash (e.g. `#campaign`), so a refresh keeps you on the
> same module. Only **real stored data** is shown — there is no demo/placeholder data.

---

## Run as a single container

The Dockerfile builds the SPA and serves it together with the API on one port — identical to
production.

```bash
docker build -t sympany-socmon .
docker run --rm -p 8080:8080 \
  -e STORAGE_BACKEND=local -e AUTH_MODE=none -e SCAN_LAUNCH=local \
  -e AWS_REGION=eu-central-2 -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
  -e BRIGHTDATA_API_KEY=your_key \
  -e APIFY_TOKEN=your_token \
  sympany-socmon
# open http://localhost:8080
```

---

## Configuration

Two files drive everything. **Secrets are only in `.env`, never in the YAML.**

### `.env` (copy from `.env.example`)

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_USERS`, `SESSION_SECRET` | for sign‑in | dashboard accounts (`python -m tools.create_app_user`) and the session‑cookie key (`AUTH_MODE=password`) |
| `FEATURE_MEDIA_COMPLIANCE` | optional | `true` shows the Media Compliance module (hidden by default) |
| `BRIGHTDATA_API_KEY` | for live | YouTube keyword search |
| `APIFY_TOKEN` | for live | Instagram, Facebook, YouTube channel, X, Quora, app stores, Google Maps |
| `QUORA_SESSION_COOKIES` | for Quora | the Quora actor returns 0 results without valid `quora.com` cookies |
| `INSTAGRAM_SESSION_COOKIES` | optional | improves Instagram throughput |

### `config/config.yaml` (non‑secret)

Key sections:

- `collection` — the **date window** kept in the knowledge base and the video‑transcription budget:
  ```yaml
  collection:
    since: "2026-05-10"
    until: ""                       # empty = no upper bound
    transcribe_video: true          # download + transcribe (Amazon Transcribe) videos without captions
    max_video_mb: 20
    max_video_transcriptions: 10     # per‑scan cap (cost control)
  ```
- `target` — organisation name (Sympany), aliases, official handles and owned accounts
  (drives the relevance filter, follower counts and reply times).
- `thresholds` — min LLM confidence to raise HIGH / MEDIUM / LOW alerts.
- `analysis` — Amazon Bedrock model ids + throttle.
- `transcription` — Amazon Transcribe languages (de‑CH, fr‑FR, it‑IT, en‑US; preferred de‑CH).
- `compliance` — vision/transcribe models + video frame‑OCR budget.
- `apify.actors` / `brightdata.datasets` — provider IDs and input templates.
- `channels` — which channels run and via which provider/mode. Modes:
  `brightdata` · `apify` · `n8n` · `demo` · `live`.
- `competitors` — Share‑of‑Voice benchmark set (CSS, Helsana, SWICA, Visana) with their
  official accounts. Handles and app ids that are not verified are left out and must be set
  before scanning those sources.

---

## Data collection & the knowledge base

Click **Run Scan** in the UI (or `POST /api/scan`, or the CLI below) to run one collection
cycle across every enabled channel. Each item is: window‑filtered → relevance‑filtered →
(video) transcribed → classified → appended to **`data/mentions.jsonl`** (the knowledge base).
Re‑scans are **manual** to control provider cost; stored data is reused between sessions.

```bash
# CLI (one cycle, then exit)
python -m src.main --once
```

**Channels & providers**

| Channel | Provider / mode | Notes |
| --- | --- | --- |
| Instagram (Sympany) | Apify `apify/instagram-scraper` | Sympany's own posts, posts tagging `@sympany`, `#sympany` |
| Facebook (Sympany) | Apify `apify/facebook-posts-scraper` | posts on `facebook.com/sympany` |
| YouTube (Sympany) | Apify `streamers/youtube-scraper` + Shorts scraper | first‑party uploads, transcribed |
| Instagram | Apify (`apify`) | popular posts **and reels** by keyword; reels are transcribed |
| Facebook | Apify (`apify`) | public posts by keyword |
| X | Apify `apidojo/tweet-scraper` | tweets naming Sympany |
| Quora | Apify (`apify`) | questions / answers by keyword |
| Google Play | Apify (`apify`) | reviews of the mySympany app (`ch.sympany.clientportal`) |
| App Store | Apify (`apify`) | reviews of mySympany — disabled until its App Store id is set |
| Google Maps | Apify `compass/crawler-google-places` | reviews of Sympany agencies in Switzerland |
| YouTube | Bright Data (`brightdata`) | videos by keyword |

---

## Video / reel sentiment

For Instagram Reels and YouTube, the pipeline folds a **transcript** of the spoken
content into the item's text before classification, so the sentiment reflects the clip:

- **YouTube** — caption transcript via `youtube-transcript-api`.
- **Instagram Reels** — download the reel and transcribe it (when a video URL is returned).

Analyse a **single video by URL** on demand:

```bash
curl -X POST http://localhost:8000/api/analyze/video \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=<video id>"}'
# -> { sentiment, risk_category, severity, confidence, rationale, transcript, ... }
# also supports youtu.be, instagram.com reel and tiktok.com URLs; the result is stored.
```

---

## Media Compliance Analyzer

Open **Media Compliance** in the sidebar. Paste content, or upload an image or video; the
backend extracts everything readable (image + frame‑by‑frame OCR, voice‑over transcription,
caption), the rule engine screens it against the **Sympany rule set** (FINMA / Swiss
insurance advertising rules), and returns an
**Approve / Advisory / Manual‑review / Reject** verdict. Every screening and rule‑set change
is appended to **`data/compliance/audit.jsonl`** (the advertising audit register).

Rules live in `config/rules/sympany-ch-v1.json` (shipped default) and
`data/compliance/ruleset-active.json` (runtime overlay written from **Settings**). Officers can
add custom Do's & Don'ts in the Settings page.

On the **Overview** dashboard, each analysed post shows a read‑only **Compliant / Non‑compliant**
status. Open a row to see **why** it is non‑compliant (the exact rules that fired) and to
**send a notification to the author** (demo action).

---

## API reference

Base path `/api` (same origin as the SPA).

| Method & path | Purpose |
| --- | --- |
| `GET /api/health` | liveness |
| `GET /api/mentions` | analysed‑item feed (the knowledge base) |
| `GET /api/authors` · `GET /api/sentiment` | per‑account activity · sentiment by platform |
| `GET /api/stats` · `GET /api/channels` | dashboard aggregates · configured channels |
| `POST /api/scan` · `GET /api/scan/status` | trigger a collection cycle · poll status |
| `GET /api/competitors` · `POST /api/scan/competitors` | Share‑of‑Voice (`own` = Sympany, `competitors` = CSS, Helsana, SWICA, Visana) · competitor scan |
| `POST /api/analyze/video` | analyse one YouTube/Instagram/TikTok URL |
| `GET/POST /api/keywords` | manage campaign keywords |
| `POST /api/compliance/extract` · `/extract/video` · `/extract/link` | OCR / transcription |
| `GET/PUT /api/compliance/ruleset` | read / replace the active rule set |
| `POST/GET /api/compliance/audit` · `GET /api/compliance/audit.csv` | compliance audit register |

---

## Project structure

```
config/
  config.yaml                 runtime config (channels, providers, collection window, models)
  rules/sympany-ch-v1.json   shipped Sympany rule set (FINMA / Swiss advertising rules)
src/
  api.py                      FastAPI app: /api/* + serves the built SPA
  main.py                     orchestrator: build_connectors + run_cycle (+ CLI)
  media_enrich.py             video/reel transcript enrichment for sentiment
  compliance.py               OCR, transcription, frame sampling, YouTube fetch
  mentions.py                 the mentions knowledge base
  store.py                    persistence: DynamoDB on AWS, files under data/ locally
  llm.py · speech.py          Amazon Bedrock calls · Amazon Transcribe streaming
  auth.py                     app sign-in (password hashes, signed session cookie); optional Cognito/ALB mode
  scan_job.py                 one scan run (status, collection, alerts)
  scan_runner.py              scans inside the web app: Run Scan + daily timer, DynamoDB lock
  connectors/                 apify, brightdata, youtube_channel, n8n, demo, ...
  pipeline/                   ingest, relevance, sentiment, risk_classifier, alerting
frontend/
  src/App.tsx                 hash routing + data loading (real data only)
  src/pages, src/components   dashboards, tables, drawer, Media Compliance UI
  src/compliance/             pure TS rule engine, matcher, decision engine, audit log
data/                         local-mode data (also seeded once into DynamoDB)
tools/                        seed_dynamodb.py, make_release_zip.py, backfill_mention_meta.py
deploy/aws/                   ECS task definitions + IAM policy templates
Dockerfile · buildspec.yml    image build (CodeBuild → ECR)
```

---

## Deployment (AWS)

See **`DEPLOY.md`**. In short: upload the release zip to S3, let AWS CodeBuild build the image
into Amazon ECR, then run it on ECS Fargate — a web service with two tasks behind WAF + ALB (app sign-in). Scans
run inside the web tasks (Run Scan, at most once per Swiss calendar day). Never zip the folder by
hand — `.env` holds live keys; use `python tools/make_release_zip.py`.
Data lives in DynamoDB; provider keys in SSM Parameter Store; alerts go to SNS.

---

## Testing

```bash
# Frontend unit tests (decision engine, matcher, audit log)
cd frontend && npm test

# Type-check + production build
npm run build
```

---

## Troubleshooting

- **Dashboard empty / "Backend unreachable"** — ensure the API is running on `:8000` (dev) and
  reachable; the SPA calls `/api` on the same origin.
- **"No stored mentions yet"** — click **Run Scan** (needs the provider keys) or run
  `python -m src.main --once`.
- **A channel is skipped** — its provider credential is missing in `.env` (check the API logs).
- **Quora returns nothing** — set valid `QUORA_SESSION_COOKIES` from the `quora.com` domain.
- **Video not transcribed** — install `ffmpeg`; some YouTube videos have captions disabled
  (then only the title/caption is scored). Transcription uses Amazon Transcribe.
- **OCR fails for some images** — install `libheif` for HEIC; the backend otherwise normalises
  common formats to JPEG automatically.

---

## Security, privacy & legal

- **Public / authorised data only.** ToS‑gated connectors are off by default; WhatsApp E2E
  content is never read.
- **PII minimisation** — author identifiers are pseudonymised (SHA‑256) in stored cases;
  retention and allow‑lists are config‑driven (aligned with the Swiss FADP / revFADP and GDPR).
- **Human‑in‑the‑loop** — the platform flags and routes; it takes no enforcement action.
- **Auditability** — the compliance decision engine is a pure, reproducible function; every
  screening and rule‑set change is written to an append‑only register.
- Never commit `.env` or provider cookies.
