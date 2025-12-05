# Spotify Routine Maker (Backend MVP)

A backend system that lets users create **time-based music routines** using Spotify playlists — similar to Pomodoro, but powered by music. Users can schedule focus, break, and wind-down blocks that automatically transition based on time.

This is built as a **backend-first MVP** with production-style OAuth handling, background scheduling, and real playback control.

---

## Why Spotify (and not Apple Music)?

Apple Music does not currently expose public playback control APIs for third-party developers.  
Spotify’s Web API allows full playback control, making it ideal for building and validating this concept as a real working system.

The core logic is **platform-agnostic** and can theoretically be adapted to any streaming service with proper API access.

---

## Core Features

- Spotify OAuth authentication with **automatic token refresh**
- Full playback control:
  - Play
  - Pause / Resume (toggle)
  - Stop routine
  - Device detection
- **Time-based routine engine**
  - Multiple playlists in sequence
  - Each block runs for a fixed duration
  - Automatic transition between blocks
- **Dynamic routines via API**
  - Pass any number of playlists with custom durations
- Preset routines (focus / break / wind-down)
- Background scheduler using Python threads
- Long-session safe (no manual re-login required)

---

## Tech Stack

- Python  
- FastAPI  
- Spotify Web API  
- OAuth 2.0 + Token Refresh  
- Requests  
- Threaded background execution  

---

## Current Status

- ✅ Backend: Stable MVP  
- ✅ OAuth + token refresh fully implemented  
- ✅ Playback + routine engine working  
- ✅ Presets supported  
- ⏳ Frontend: In progress (React planned)  

---

## Example Use Case

A user can define a routine like:

- 25 minutes → Deep Work playlist  
- 5 minutes → Break playlist  
- 15 minutes → Wind Down playlist  

The system will:

- Start playback automatically  
- Switch between playlists based on time  
- Pause / resume the entire routine  
- Stop everything instantly if needed  

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/your-username/spotify-routine-maker.git
cd spotify-routine-maker
