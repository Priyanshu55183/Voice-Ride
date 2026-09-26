# VoiceRide — Personal Voice Assistant for Parallel Cab Booking

> **⚠️ Personal-use only.** This tool automates **my own accounts** on Uber, Ola, and Rapido. It is not designed for distribution, multi-user access, or scraping other people's data.

## What It Does

When I need a cab, I currently open multiple apps, book on one, wait, and if no driver is found, manually cancel and switch to another app. This wastes time.

**VoiceRide automates this:** I say "Book a cab from Mekhri Circle to BMSIT College," and it:
1. Requests a ride on **multiple platforms simultaneously**
2. **Polls** each platform's ride status every ~4 seconds
3. The **moment any platform finds a driver**, it automatically **cancels the pending requests** on the others
4. Confirms via voice/notification: which platform won, driver ETA

## How Detection Works (Polling, Not Instant)

This is **not** a real-time race. There are no public booking APIs — detection is via **UI polling** every ~4 seconds. This means:
- There's a ~0-4 second delay between a driver being assigned and VoiceRide detecting it
- Cancellations happen within seconds of detection, but are not instantaneous
- The system cancels within each platform's **free-cancellation grace window** where possible, to minimize impact on drivers

## Platform Terms of Service

- This automates **my own accounts only** — no multi-user distribution
- Automation of personal accounts exists in a gray area of most platform ToS
- This is scoped to **personal use** specifically to minimize any policy concerns
- I use this for my own convenience, not to gain unfair advantage at scale
- Cancel-on-other-platform-confirm behavior is manually achievable — this just automates what I'd do by hand

## Architecture

```
[Voice Input] → STT → LLM Intent Extraction → Platform Dispatcher
    → [Uber (Playwright/web), Ola (Appium), Rapido (Appium)]
    → Status Poller (per platform, async)
    → First-Confirm Detector → Cancel-Others Executor
    → TTS Confirmation + Desktop Notification
    → SQLite Logging
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, FastAPI, asyncio |
| Uber automation | Playwright → m.uber.com |
| Ola/Rapido automation | Appium → Android app |
| STT | Whisper (local) |
| LLM | OpenAI/Anthropic API |
| TTS | pyttsx3 |
| Database | SQLite (via aiosqlite) |
| Secrets | OS keyring |
| Notifications | Windows toasts (plyer) |

## Setup

### Prerequisites

- Python 3.11 or newer
- Git

### Installation

```bash
# Clone the repo
git clone <your-repo-url>
cd Voice-Ride

# Create virtual environment
python -m venv venv
venv\Scripts\activate       # Windows

# Install dependencies
pip install -e .

# Install Playwright browsers
python -m playwright install chromium
```

### Configuration

```bash
# Copy the environment template
copy .env.example .env
# Edit .env with your settings (defaults work for Phase 1)
```

### First-Time Uber Login

```bash
# Run the interactive login helper (opens a browser window)
python scripts/uber_login.py

# Log in manually in the browser window
# Session is saved automatically to data/uber_session/
```

### Usage (Phase 1 — CLI)

```bash
# Book a ride
python -m voiceride.cli book --pickup "Mekhri Circle" --drop "BMSIT College"

# View recent runs
python -m voiceride.cli status

# View events for a specific run
python -m voiceride.cli status --run-id <run-id>
```

### Session Storage

Uber login sessions are stored as Playwright persistent browser contexts in `data/uber_session/`. This directory contains cookies and localStorage — treat it as sensitive. It is gitignored.

For API keys and tokens, VoiceRide uses the OS keyring (Windows Credential Manager). Nothing is stored in plaintext config files.

## Build Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | 🔨 In Progress | Uber-only pipeline, manual CLI trigger |
| 2 | ⏳ Planned | Voice input (Whisper) + NLU (LLM) + TTS |
| 3 | ⏳ Planned | Add Ola via Appium |
| 4 | ⏳ Planned | Parallel dispatch + first-confirm-wins + cancel-others |
| 5 | ⏳ Planned | Add Rapido via Appium |
| 6 | ⏳ Planned | Edge case hardening + Streamlit dashboard |

## Project Structure

```
Voice-Ride/
├── voiceride/
│   ├── cli.py                  # CLI commands (book, status)
│   ├── config.py               # Settings from .env
│   ├── logging_config.py       # Structured logging setup
│   ├── orchestrator/
│   │   ├── models.py           # Pydantic data models
│   │   ├── state_machine.py    # Booking run lifecycle
│   │   ├── dispatcher.py       # Parallel platform dispatch
│   │   └── first_confirm.py    # First-confirm + cancel-others
│   ├── platforms/
│   │   ├── base.py             # Abstract adapter interface
│   │   └── uber/
│   │       ├── adapter.py      # UberAdapter(PlatformAdapter)
│   │       ├── automation.py   # Playwright page-object actions
│   │       ├── selectors.py    # CSS/XPath selectors (isolated)
│   │       └── session.py      # Login/session management
│   ├── storage/
│   │   ├── database.py         # SQLite operations
│   │   └── secrets.py          # OS keyring wrapper
│   └── notifications/
│       └── desktop.py          # Windows toast notifications
├── scripts/
│   └── uber_login.py           # Interactive login helper
├── data/                       # Runtime data (gitignored)
├── logs/                       # Log files (gitignored)
└── tests/                      # Test suite
```

## License

Personal use only. Not for distribution.
