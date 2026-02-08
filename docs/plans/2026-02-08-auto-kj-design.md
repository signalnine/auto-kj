# auto-kj: Voice-Controlled Karaoke Machine

## Overview

A dedicated karaoke appliance (mini PC, N100-class) connected to a TV and speakers. Controlled by voice between songs and a keyboard during playback. Sources music from YouTube via yt-dlp, strongly prefers karaoke videos with baked-in lyrics, falls back to AI vocal separation (Spleeter) with synced lyrics overlay. The mic signal path is entirely hardware — Python never touches live audio.

## Hardware Signal Path

```
USB Mic → Reverb Box → Speakers/Mixer (hardware, zero latency)
Mini PC → HDMI → TV (video) + Speakers (mpv audio)
```

The mic audio and mpv playback audio are mixed at the hardware level (mixer/amp). Python handles playback, voice commands, and the song pipeline — not live mic audio. Feedback is managed through physical mic/speaker placement and gain staging.

## Core Flow

1. System boots into idle mode, wake word listening active
2. User says "Hey Karaoke, play Bohemian Rhapsody"
3. System searches YouTube for karaoke version first, falls back to original
4. If original: Spleeter separates vocals, LRCLIB fetches synced lyrics
5. Song queued and played via mpv fullscreen on TV
6. During playback: mic goes through hardware reverb to speakers (no software involvement)
7. Song ends, system returns to idle, announces "Queue is empty"

## Platform

- Mini PC (Intel N100 or similar)
- HDMI out to TV for display
- USB mic → hardware reverb box → speakers/mixer
- Speakers via mixer or amp (combines mic + HDMI/PC audio)
- Always-on appliance

## Voice Interface

### Two Mic Modes

| State | Mic behavior |
|-------|-------------|
| Idle / between songs | OpenWakeWord listening via USB mic, then Whisper for commands |
| Song playing | Hardware passthrough only (mic → reverb → speakers). Software not involved. |

### Wake Word

- Engine: OpenWakeWord (open source, custom wake words)
- Wake word: "Hey Karaoke"
- Only active when no song is playing
- Plays a chime when triggered to signal listening

### Speech-to-Text

- Engine: OpenAI Whisper (local, small model)
- Activated after wake word detection or spacebar press
- Records up to 5 seconds or until silence detected
- Returns transcribed text for command parsing

### Command Set

| Intent | Trigger phrases | Action |
|--------|----------------|--------|
| play | "play X", "sing X", "add X" | Search + enqueue song |
| skip | "skip", "next", "next song" | Skip to next in queue |
| pause | "pause", "stop" | Pause playback |
| resume | "resume", "continue", "go" | Resume playback |
| queue | "what's next", "show queue" | Read queue aloud via TTS |
| volume | "volume up/down", "louder/quieter" | Adjust mpv volume |
| cancel | "cancel", "never mind" | Discard, return to listening |

### TTS Feedback

- Engine: pyttsx3 or espeak
- Spoken responses: "Added X to the queue", "Skipping", "Queue is empty"

## Keyboard Controls

| Key | During playback | When idle/paused |
|-----|----------------|-----------------|
| Spacebar | Pause + activate Whisper for command | Activate Whisper (bypass wake word) |
| Escape | Skip current song | — |
| Up/Down | Volume up/down | Volume up/down |
| Q | — | Quit application |

## Song Search & Download Pipeline

### Step 1: Search for karaoke version (primary path)
```
yt-dlp "ytsearch5:{song} karaoke" --dump-json
```
Score results by title keywords: "karaoke", "lyrics", "sing along". Almost all popular songs have karaoke versions on YouTube. If a good match is found, download the video — it has baked-in lyrics, no processing needed.

### Step 2: Fall back to original + Spleeter (rare)
```
yt-dlp "ytsearch3:{song}" --dump-json
```
Download best match, run Spleeter (2stems model) to separate vocals from instrumentals. Spleeter is lightweight and fast on N100-class hardware. Fetch synced lyrics from LRCLIB API.

### Step 3: Cache everything
Store processed songs in `~/.auto-kj/cache/` keyed by YouTube video ID. SQLite DB tracks cache index with metadata. LRU eviction when cache exceeds configured size limit (default 10GB).

### Processing Pipeline (background worker)
```
Song requested
  -> Check cache (SQLite lookup)
  -> Cache hit -> enqueue cached files
  -> Cache miss:
      -> yt-dlp search "{song} karaoke" -> score results
      -> Good karaoke hit? -> download video -> cache -> enqueue
      -> No good hit:
          -> yt-dlp search "{song}" -> download best match
          -> Spleeter separate -> save instrumental
          -> Fetch LRC lyrics from LRCLIB
          -> Cache all artifacts -> enqueue
```

Processing runs in background thread. First song has cold-start delay with spoken feedback: "Searching for Bohemian Rhapsody... this may take a moment."

## Playback

### Engine: mpv via python-mpv

- Karaoke video found: play video fullscreen, audio out via HDMI or analog
- Spleeter-separated track: play instrumental audio, load LRC as subtitles via --sub-file

## State Machine

```
IDLE (wakeword listening)
  |-- command received -> search/enqueue -> IDLE
  |-- queue not empty -> PLAYING
  |-- spacebar -> LISTENING (whisper)

PLAYING (song playing, mic = hardware passthrough)
  |-- song ends -> next in queue or IDLE
  |-- spacebar -> PAUSED + LISTENING
  |-- escape -> skip -> next song or IDLE

PAUSED (wakeword listening)
  |-- spacebar -> LISTENING (whisper)
  |-- wakeword -> LISTENING (whisper)
  |-- "resume" command -> PLAYING

LISTENING (whisper capturing, up to 5s)
  |-- command parsed -> act -> return to previous state
```

## Cache Structure

```
~/.auto-kj/cache/
  {youtube_id}/
    video.mp4           # original or karaoke video
    instrumental.wav    # spleeter output (if separated)
    lyrics.lrc          # synced lyrics (if fetched)
    metadata.json       # title, artist, source type, last_accessed
  cache.db              # SQLite index (tracks size, LRU eviction)
```

## Project Structure

```
auto-kj/
  main.py               # Entry point, starts all subsystems
  config.py             # Settings (cache dir, cache size limit, audio device, etc.)
  playback.py           # mpv control (play, pause, skip, volume)
  voice/
    wakeword.py         # OpenWakeWord listener
    transcribe.py       # Whisper speech-to-text
    commands.py         # Intent parsing from transcribed text
    tts.py              # Spoken feedback
  songs/
    search.py           # yt-dlp search (karaoke first, then original)
    download.py         # yt-dlp download + cache management
    separate.py         # Spleeter vocal separation
    lyrics.py           # LRCLIB synced lyrics fetch
    cache.py            # SQLite cache index + LRU eviction
  queue.py              # Song queue management
  keyboard.py           # Key capture (spacebar, escape, volume)
  requirements.txt
```

## Tech Stack

| Component | Tool |
|-----------|------|
| Song search/download | yt-dlp |
| Vocal separation (fallback) | spleeter (2stems) |
| Video/audio playback | mpv via python-mpv |
| Wake word | openwakeword |
| Speech-to-text | openai-whisper (small model) |
| Lyrics | LRCLIB API |
| TTS feedback | pyttsx3 / espeak |
| Cache DB | sqlite3 |
| Keyboard input | evdev |
| Mic effects | Hardware reverb box (not software) |

## Error Handling

- **Song not found**: TTS "Sorry, I couldn't find that song"
- **Spleeter fails**: Fall back to playing original with vocals, TTS notification
- **Network down**: Cached songs still play, new requests fail gracefully
- **Queue empty**: Return to idle, TTS "Queue is empty. What should I play next?"
- **Whisper mishears**: TTS echoes what it heard ("I heard X, searching...") so user can correct

## Hardware Setup Notes

- Position mic away from speakers to avoid feedback
- Use a directional/cardioid mic pointed away from speaker output
- Set gain conservatively — the hardware reverb box handles effects
- Speakers should face the audience, not the mic
