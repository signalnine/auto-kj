# auto-kj

Voice-controlled karaoke machine. Say a song name, it finds it on YouTube, strips the vocals if needed, and plays it on your TV. You sing through a hardware mic + reverb setup.

## How it works

```
"Hey Karaoke, play Bohemian Rhapsody"
  → searches YouTube for a karaoke version
  → downloads and caches it
  → plays fullscreen on TV via mpv
  → you sing through your mic + reverb box
```

If no karaoke version exists, it downloads the original, runs Spleeter to strip vocals, and fetches synced lyrics from LRCLIB.

## Hardware

```
USB Mic → Reverb Box → Speakers/Mixer
Mini PC → HDMI → TV + Speakers
```

The mic signal path is entirely hardware — Python never touches live audio. The mini PC handles playback, voice commands, and the song pipeline. Mic and playback audio are mixed at the hardware level.

**What you need:**
- Mini PC (Intel N100 or similar)
- TV with HDMI
- USB microphone (cardioid recommended)
- Hardware reverb/effects box
- Speakers or mixer/amp
- Internet connection

## Install

```bash
./install.sh
```

This installs system packages (ffmpeg, mpv, espeak-ng), sets up a Python 3.11 venv via [uv](https://docs.astral.sh/uv/), installs all dependencies, and downloads wakeword models.

Python 3.11 is required — Spleeter's TensorFlow dependency doesn't support 3.12+.

## Run

```bash
source .venv/bin/activate
python auto-kj/main.py
```

yt-dlp is automatically updated to the latest version on every startup via `uv`.

## Controls

### Voice (when no song is playing)

Say "Hey Karaoke" (or press spacebar), then:

| Say | Does |
|-----|------|
| "play Bohemian Rhapsody" | Search + queue the song |
| "skip" / "next" | Skip to next song |
| "pause" / "stop" | Pause playback |
| "resume" / "continue" | Resume |
| "what's next" / "show queue" | Read the queue aloud |
| "volume up" / "louder" | Turn it up |
| "volume down" / "quieter" | Turn it down |

### Keyboard

| Key | During playback | When idle |
|-----|----------------|-----------|
| Space | Pause + voice command | Voice command |
| Escape | Skip song | — |
| Up/Down | Volume | Volume |
| Q | — | Quit |

## How songs are found

1. Search YouTube for `"{song} karaoke"` — score results by keywords (karaoke, lyrics, sing along)
2. If a good karaoke version is found, download and play it directly (lyrics are baked into the video)
3. If not, download the original, extract audio with ffmpeg, separate vocals with Spleeter, fetch synced lyrics from LRCLIB

Everything is cached in `~/.auto-kj/cache/` with LRU eviction (default 10GB limit).

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOKJ_CACHE_DIR` | `~/.auto-kj/cache` | Where to store downloaded songs |
| `AUTOKJ_WHISPER_MODEL` | `small` | Whisper model size (tiny/base/small/medium) |
| `AUTOKJ_WAKEWORD_MODEL` | `hey_jarvis` | OpenWakeWord model name |

## Architecture

```
IDLE (wakeword listening)
  │── voice command → search/enqueue → IDLE
  │── queue not empty → PLAYING
  └── spacebar → LISTENING

PLAYING (song playing, mic = hardware passthrough)
  │── song ends → next in queue or IDLE
  │── spacebar → PAUSED + LISTENING
  └── escape → skip

PAUSED (wakeword listening)
  │── spacebar → LISTENING
  └── "resume" → PLAYING

LISTENING (whisper capturing, up to 5s)
  └── command parsed → act → return to previous state
```

Single shared PyAudio stream handles both wakeword detection and command recording to avoid ALSA device contention.

## Hardware setup tips

- Point the mic away from the speakers
- Use a cardioid mic to reject sound from behind
- Set gain conservatively — the reverb box handles effects
- Speakers should face the audience, not the mic

## Tests

```bash
python3 -m pytest tests/ -v
```

66 tests, all mocked for external dependencies (no mic/speakers/internet needed to run tests).
