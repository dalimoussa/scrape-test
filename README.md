# Bet365 Scraper & Real-Time Dashboard

A lightweight, real-time Bet365 scraper and HTTP API that intercepts WebSocket traffic in Chrome and serves structured live scores, pre-match fixtures, betting odds, and tech stats via REST endpoints and a modern responsive dashboard.

![Bet365 Scraper Hub](https://img.shields.io/badge/Bet365-Live%20%26%20Pre--Match-238636?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square)
![Flask](https://img.shields.io/badge/Flask-API-lightgrey?style=flat-square)

---

## ✨ Features

- 🔴 **Live In-Play Scraping**: Real-time scores, match timer, periods, and betting odds across all sports (Football, Basketball, Tennis, etc.).
- 📅 **Pre-Match / Upcoming Fixtures**: Scheduled kickoff timestamps, competition/league names, teams, and decimal/fractional odds.
- ⚽ **Football Technical Stats**: Real-time corners, yellow/red cards, throw-ins, and free kicks parsed from `OVS1` feeds.
- ⚡ **Modern Scoreboard UI**: Responsive dark-theme dashboard with Live/Pre-Match toggle, search, sport filtering, and 2-second auto-refresh.
- 🌐 **Language-Agnostic**: Automatically detects language locale (English, French, Chinese, etc.) from `GamingContext.languageId`.

---

## 📁 Project Structure

```
├── local_api.py            # Python Flask backend: parser, REST API & Web Dashboard
├── requirements.txt        # Python dependencies (flask, flask-cors, pytz)
├── .gitignore
├── README.md
└── chrome_extention/       # Chrome Manifest V3 Extension
    ├── manifest.json       # Extension configuration
    ├── popup.html          # Extension popup UI
    ├── img/logo.png
    └── js/
        ├── hook.js         # Injected WebSocket interceptor (socketDataCallback)
        ├── content.js      # Bridge script
        ├── background.js   # Service worker forwarding frames via HTTP POST
        └── popup.js        # Settings script
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the API Server
```bash
python local_api.py
```
*Server will start listening on `http://127.0.0.1:8485`.*

### 3. Load the Chrome Extension
1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** (top right switch).
3. Click **Load unpacked** and select the `chrome_extention` folder.

### 4. Open Bet365
1. Open [Bet365](https://www.bet365.com) in your Chrome browser.
2. Navigate to **In-Play** (for live matches) or **Sports / Competitions** (for pre-match fixtures).
3. Data will automatically stream to the backend.

---

## 📊 REST API Endpoints

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| **`/`** or **`/dashboard`** | `GET` | Web Dashboard UI (Live & Pre-Match views) |
| **`/live`** | `GET` | All live matches (optional `?sport=1` for football, `?sport=18` for basketball) |
| **`/prematch`** | `GET` | All pre-match fixtures (optional `?sport=1`, `?competition=Premier+League`) |
| **`/fixtures`** | `GET` | Combined union of both Live + Pre-Match fixtures |
| **`/sports`** | `GET` | Active sports list & match counts (optional `?scope=live\|prematch`) |
| **`/soccer/stats`** | `GET` | Live football technical stats (corners, cards, etc.) |
| **`/prematch/<fixture_id>`** | `GET` | Detailed pre-match fixture by fixture ID |
| **`/data`** | `POST`/`GET` | Ingestion endpoint for Chrome extension / Raw debug dump |

---

## 📦 Sample API Responses

### Live Match (`GET /live?sport=1`)
```json
[
  {
    "fixtureId": "199859215",
    "sportId": "1",
    "sport": "Football",
    "league": "Australia - New South Wales Premier League",
    "event": "NWS Spirit FC v SD Raiders",
    "homeTeam": "NWS Spirit FC",
    "awayTeam": "SD Raiders",
    "score": "2 - 1",
    "homeScore": 2,
    "awayScore": 1,
    "period": "SecondHalf",
    "time": "68:45",
    "markets": [
      {
        "name": "Full Time Result",
        "odds": [
          { "name": "1", "oddsDecimal": 1.40, "oddsFractional": "2/5" },
          { "name": "X", "oddsDecimal": 4.75, "oddsFractional": "15/4" },
          { "name": "2", "oddsDecimal": 8.00, "oddsFractional": "7/1" }
        ]
      }
    ],
    "stats": {
      "Corner": { "home": 5, "away": 2 },
      "YellowCard": { "home": 1, "away": 3 }
    }
  }
]
```

### Pre-Match Fixture (`GET /prematch?sport=1`)
```json
[
  {
    "fixtureId": "199767158",
    "sportId": "1",
    "sport": "Football",
    "league": "England - Premier League",
    "event": "Arsenal v Chelsea",
    "homeTeam": "Arsenal",
    "awayTeam": "Chelsea",
    "scheduledTime": "2026-08-23T16:30:00Z",
    "scheduledDisplay": "23 Aug 16:30 UTC",
    "status": "prematch",
    "score": { "home": null, "away": null, "display": "" },
    "markets": [
      {
        "name": "Full Time Result",
        "odds": [
          { "name": "1", "oddsDecimal": 2.10, "oddsFractional": "11/10" },
          { "name": "X", "oddsDecimal": 3.40, "oddsFractional": "12/5" },
          { "name": "2", "oddsDecimal": 3.60, "oddsFractional": "13/5" }
        ]
      }
    ]
  }
]
```

---

## 🛠️ Tech Stack

- **Python 3.8+**
- **Flask** & **Flask-CORS**
- **Chrome Extension (Manifest V3)**
- **HTML5 / CSS3 / Vanilla JS**

---

## 📄 License

MIT License
