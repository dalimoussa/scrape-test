# Bet365 Real-Time Scraper & API

A real-time Bet365 scraper, pre-match fixtures, and betting odds.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Backend API
```bash
python local_api.py
```
> Server runs on `http://127.0.0.1:8485`

### 3. Load the Chrome Extension
1. Open Google Chrome and go to `chrome://extensions/`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `chrome_extention` folder.
4. Navigate to [Bet365](https://www.bet365.com) (In-Play or Sports fixtures).

---

## 📡 API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` or `/dashboard` | `GET` | Web Dashboard UI |
| `/live` | `GET` | Live in-play matches & odds (e.g. `?sport=1`) |
| `/prematch` | `GET` | Pre-match fixtures & odds (e.g. `?sport=1`) |
| `/fixtures` | `GET` | Combined live and pre-match fixtures |
| `/sports` | `GET` | Active sports list & fixture counts |
| `/soccer/stats` | `GET` | In-play football stats (corners, cards, etc.) |
| `/data` | `POST`/`GET` | Extension ingestion & raw data endpoint |

---

## 📄 License

MIT License
