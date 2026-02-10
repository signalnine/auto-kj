# auto-kj

Voice-controlled karaoke machine. Say a song name, it finds it on YouTube, strips the vocals if needed, and plays it on your TV. Sing through a USB mic with real-time software reverb.

## How it works

```
"Hey Karaoke, play Bohemian Rhapsody"
  -> searches YouTube for a karaoke version
  -> downloads and caches it
  -> plays fullscreen on TV via mpv
  -> you sing through the USB mic with reverb through the speakers
```

If no karaoke version exists, it downloads the original, runs Spleeter to strip vocals, and fetches synced lyrics from LRCLIB.

## Hardware

```
Mini PC (N100) --HDMI--> TV/Monitor with speakers
USB Mic -----> Mini PC (JACK audio engine)
```

Everything runs on a single mini PC. The USB mic is captured through JACK with real-time Schroeder reverb applied in software, mixed with karaoke playback, and output through HDMI to the TV speakers. No external audio hardware needed beyond the mic.

**What you need:**
- Mini PC (Intel N100 or similar) running Debian/Ubuntu
- TV or monitor with HDMI audio (or separate speakers on a second ALSA device)
- USB microphone

## Audio architecture

JACK provides low-latency audio routing and mixing. All audio sources are mixed to the HDMI output automatically.

```
USB Mic (hw:2) --> [zita-a2j] --> JACK capture
                                      |
                  +-------------------+-------------------+
                  |                                       |
            [downsample 48k->16k]              [gain + Schroeder reverb]
                  |                                       |
            wakeword / whisper                            v
                                                 system:playback  <-- mpv (--ao=jack)
                                                                  <-- TTS (JACK client)
```

| Segment | Latency |
|---------|---------|
| USB mic -> zita-a2j | ~5-10ms |
| JACK processing (1 period) | ~5ms |
| JACK -> HDMI output (2 periods) | ~11ms |
| **Total mic-to-speaker** | **~21-26ms** |

The reverb is a Schroeder design (4 comb + 2 allpass filters) running on 256-sample blocks at 48kHz. Mic monitoring is automatically muted during TTS to prevent feedback.

## Install

```bash
git clone <repo> && cd auto-kj
./install.sh
```

The installer handles: system packages (ffmpeg, mpv, espeak-ng, jackd2, zita-ajbridge), Python 3.11 via [uv](https://docs.astral.sh/uv/), all pip dependencies, wakeword model downloads, and data directories.

Python 3.11 is required (Spleeter's TensorFlow dependency doesn't support 3.12+).

### Post-install setup

1. **Wakeword model** (optional): Place a custom OpenWakeWord `.onnx` model at `~/.auto-kj/models/hey_karaoke.onnx`. If the model uses external tensor data, include the `.onnx.data` file alongside it. Without a custom model, the built-in OpenWakeWord models are used.

2. **Claude API** (optional): For AI-powered voice command interpretation (corrects Whisper transcription errors) and joke telling, set your API key:
   ```bash
   echo "ANTHROPIC_API_KEY=sk-ant-..." >> ~/.env
   ```
   Without this, voice commands fall back to regex parsing.

3. **Piper TTS** (optional): For higher-quality speech synthesis, install the [Piper](https://github.com/rhasspy/piper) binary and place a model at `~/.auto-kj/piper/en_US-lessac-medium.onnx`. Falls back to espeak-ng.

## Run

```bash
source .venv/bin/activate
python auto-kj/main.py
```

yt-dlp is automatically updated on every startup.

### Run as a systemd service

```bash
sudo cp auto-kj.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auto-kj
```

The service runs as your user, reads `~/.env` for environment variables, grabs a TTY for keyboard input, and restarts on failure. Logs via `journalctl -u auto-kj -f`.

## Controls

### Voice

Say "Hey Karaoke" (or press spacebar), then:

| Say | Does |
|-----|------|
| "play Bohemian Rhapsody" | Search + queue the song |
| "skip" / "next" | Skip current song |
| "pause" / "stop" | Pause playback |
| "resume" / "continue" | Resume playback |
| "what's next" / "show queue" | Read the queue aloud |
| "volume up" / "louder" | Increase volume |
| "volume down" / "quieter" | Decrease volume |
| "tell me a joke" | Tell a joke (via Claude API) |
| "cancel" / "nevermind" | Cancel voice command |

Voice commands are processed through Claude Haiku for transcription error correction (e.g., "play bow he and rap city" -> "play Bohemian Rhapsody"). Falls back to regex if the API is unavailable.

### Keyboard

| Key | During playback | When idle |
|-----|----------------|-----------|
| Space | Pause + listen for command | Listen for command |
| Escape | Skip song | -- |
| Up/Down | Volume | Volume |
| Q | Quit | Quit |

Keyboard input uses evdev (requires `input` group membership).

## Song pipeline

1. Search YouTube for `"<song> karaoke"` -- score results by keywords (karaoke, lyrics, sing along)
2. If a good karaoke version is found, download and play it directly (lyrics baked into the video)
3. If not, download the original video, extract audio with ffmpeg, separate vocals with Spleeter, fetch synced lyrics from LRCLIB

Everything is cached in `~/.auto-kj/cache/` (SQLite index with LRU eviction, default 10GB limit).

## Configuration

All settings via environment variables (or `~/.env` when running as a service):

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOKJ_CACHE_DIR` | `~/.auto-kj/cache` | Song cache directory |
| `AUTOKJ_CACHE_MAX_BYTES` | `10737418240` | Cache size limit (10GB) |
| `AUTOKJ_WHISPER_MODEL` | `small` | Whisper model size (tiny/base/small/medium) |
| `AUTOKJ_WAKEWORD_MODEL` | `~/.auto-kj/models/hey_karaoke.onnx` | Path to custom wakeword model |
| `AUTOKJ_JACK_DEVICE` | `hw:0,8` | ALSA device for JACK playback (HDMI output) |
| `AUTOKJ_JACK_MIC_DEVICE` | `hw:2` | ALSA device for USB mic (via zita-a2j) |
| `AUTOKJ_JACK_PERIOD` | `256` | JACK period size (frames) |
| `AUTOKJ_MIC_GAIN` | `1.2` | Mic gain multiplier |
| `AUTOKJ_REVERB_WET` | `0.1` | Reverb wet/dry mix (0.0 = dry, 1.0 = full reverb) |
| `AUTOKJ_MONITOR_ENABLED` | `1` | Enable mic monitoring (0 to disable) |
| `ANTHROPIC_API_KEY` | -- | Claude API key for command parsing and jokes |

Find your ALSA devices with `aplay -l` (playback) and `arecord -l` (capture).

## State machine

```
IDLE (wakeword listening, mic monitoring active)
  |-- voice command -> search/enqueue -> IDLE
  |-- queue not empty -> PLAYING
  +-- spacebar -> LISTENING

PLAYING (mpv playing, mic monitoring active)
  |-- song ends -> next in queue or IDLE
  |-- spacebar -> PAUSED + LISTENING
  +-- escape -> skip

PAUSED (wakeword listening, mic monitoring active)
  |-- spacebar -> LISTENING
  +-- "resume" -> PLAYING

LISTENING (Whisper recording, up to 5s)
  +-- command parsed -> act -> return to previous state
```

## Project structure

```
auto-kj/
  main.py          # Entry point, Karaoke orchestrator, Claude integration
  config.py        # Dataclass config with env var defaults
  state.py         # State machine (IDLE/PLAYING/PAUSED/LISTENING)
  audio.py         # JACK engine: mic capture, reverb, downsampling, TTS playback
  playback.py      # mpv subprocess control via IPC socket
  keyboard.py      # evdev keyboard handler
  queue_manager.py # Thread-safe song queue
  speak.py         # Standalone CLI tool for JACK TTS (python speak.py "hello")
  voice/
    wakeword.py    # OpenWakeWord listener
    transcribe.py  # Whisper speech-to-text
    commands.py    # Regex command parser (fallback)
    tts.py         # TTS worker (Piper/espeak-ng -> JACK)
  songs/
    search.py      # YouTube search with karaoke scoring
    download.py    # yt-dlp wrapper
    separate.py    # Spleeter vocal separation
    lyrics.py      # LRCLIB synced lyrics
    cache.py       # SQLite cache with LRU eviction
    pipeline.py    # Orchestrates search -> download -> separate -> cache -> queue
tests/             # 82 tests, all mocked (no hardware needed)
auto-kj.service    # systemd unit file
install.sh         # One-step installer
```

## Tests

```bash
python3 -m pytest tests/ -v
```

82 tests, all mocked for external dependencies (no mic, speakers, internet, or GPU needed). The test suite mocks JACK, evdev, mpv, spleeter, whisper, and openwakeword at the `sys.modules` level via `conftest.py`.

## Troubleshooting

**No sound from mic:** Check `AUTOKJ_JACK_MIC_DEVICE` matches your USB mic (`arecord -l`). Verify JACK connections with `jack_lsp -c` while the service is running.

**No sound from playback:** Check `AUTOKJ_JACK_DEVICE` matches your HDMI output (`aplay -l`). Try `speaker-test -D hw:0,8 -c 2` to verify the device works.

**Wakeword not detecting:** Increase `AUTOKJ_WAKEWORD_MODEL` threshold sensitivity, or check mic levels with the `[mic] peak=` log output in journalctl.

**Claude API errors:** Verify `ANTHROPIC_API_KEY` is set in `~/.env` and the key is valid. The system falls back to regex parsing gracefully.

**Service won't start:** Check `journalctl -u auto-kj -f` for errors. Common issues: wrong ALSA device names, missing group membership (audio/input), JACK can't open the audio device.

**Permission denied on keyboard:** Add your user to the `input` group: `sudo usermod -aG input $USER` then log out and back in.
