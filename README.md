# auto-kj

![auto-kj](auto-kj.png)

Voice-controlled karaoke machine. Say a song name, it finds it on YouTube, strips the vocals if needed, and plays it on your TV. Sing through a USB mic with hardware or software reverb monitoring.

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
USB Mic -----> Mic Amp (optional) -----> Mini PC (JACK audio engine)
```

Two monitoring modes are supported, controlled by `AUTOKJ_MONITOR_MODE`:

- **`hardware`** (default): USB mic goes through an external mic amp that handles monitoring and reverb. JACK only captures audio for wakeword/whisper.
- **`software`**: JACK applies gain and Schroeder reverb in software, routing the processed mic signal to the speakers. No external amp needed.

**What you need:**
- Mini PC (Intel N100 or similar) running Debian/Ubuntu
- TV or monitor with HDMI audio (or separate speakers on a second ALSA device)
- USB microphone
- Mic amp with monitoring/reverb (hardware mode), or nothing extra (software mode)

## Audio architecture

JACK provides low-latency audio routing and mixing. All audio sources are mixed to the HDMI output automatically.

**Hardware mode** (default) — mic amp handles monitoring:
```
USB Mic --> Mic Amp (monitoring/reverb) --> speakers
        \-> JACK capture (-C flag) --> [downsample 48k->16k] --> wakeword / whisper

system:playback  <-- mpv (--ao=jack)
                 <-- TTS (JACK client)
```

**Software mode** — JACK handles monitoring:
```
USB Mic (hw:2) --> JACK capture (-C flag)
                         |
       +-----------------+-----------------+
       |                                   |
 [downsample 48k->16k]          [gain + Schroeder reverb]
       |                                   |
 wakeword / whisper                        v
                                   system:playback  <-- mpv (--ao=jack)
                                                    <-- TTS (JACK client)
```

JACK captures the mic directly via its `-C` (capture device) flag, eliminating the need for a separate zita-a2j bridge process.

| Segment | Latency (software mode) |
|---------|---------|
| JACK processing (1 period @ 128) | ~2.7ms |
| JACK -> HDMI output (2 periods) | ~5.3ms |
| **Total mic-to-speaker** | **~8-13ms** |

In software mode, the reverb is a Schroeder design (4 comb + 2 allpass filters) running on 128-sample blocks at 48kHz, implemented with scipy.signal.lfilter for C-optimized performance. Mic monitoring is automatically muted during TTS to prevent feedback.

## Install

```bash
git clone <repo> && cd auto-kj
./install.sh
```

The installer handles: system packages (ffmpeg, mpv, espeak-ng, jackd2), Python 3.11 via [uv](https://docs.astral.sh/uv/), all pip dependencies, wakeword model downloads, and data directories.

Python 3.11 is required (Spleeter's TensorFlow dependency doesn't support 3.12+).

### Post-install setup

1. **Wakeword model**: The custom "Hey Karaoke" model is bundled in `models/` and installed automatically by `install.sh` to `~/.auto-kj/models/`. To use a different model, replace the files there or set `AUTOKJ_WAKEWORD_MODEL`.

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
| `AUTOKJ_JACK_MIC_DEVICE` | `hw:2` | ALSA device for USB mic (JACK `-C` capture) |
| `AUTOKJ_JACK_PERIOD` | `128` | JACK period size (frames) |
| `AUTOKJ_MONITOR_MODE` | `hardware` | Monitor mode: `hardware` (external amp) or `software` (JACK reverb) |
| `AUTOKJ_MIC_GAIN` | `2.0` | Mic gain multiplier (software mode only) |
| `AUTOKJ_REVERB_WET` | `0.1` | Reverb wet/dry mix, 0.0-1.0 (software mode only) |
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
tests/             # 88 tests, all mocked (no hardware needed)
auto-kj.service    # systemd unit file
install.sh         # One-step installer
```

## Tests

```bash
python3 -m pytest tests/ -v
```

88 tests, all mocked for external dependencies (no mic, speakers, internet, or GPU needed). The test suite mocks JACK, evdev, mpv, spleeter, whisper, and openwakeword at the `sys.modules` level via `conftest.py`.

## Troubleshooting

**No sound from mic:** Check `AUTOKJ_JACK_MIC_DEVICE` matches your USB mic (`arecord -l`). Verify JACK connections with `jack_lsp -c` while the service is running.

**No sound from playback:** Check `AUTOKJ_JACK_DEVICE` matches your HDMI output (`aplay -l`). Try `speaker-test -D hw:0,8 -c 2` to verify the device works.

**Wakeword not detecting:** Increase `AUTOKJ_WAKEWORD_MODEL` threshold sensitivity, or check mic levels with the `[mic] peak=` log output in journalctl.

**Claude API errors:** Verify `ANTHROPIC_API_KEY` is set in `~/.env` and the key is valid. The system falls back to regex parsing gracefully.

**Service won't start:** Check `journalctl -u auto-kj -f` for errors. Common issues: wrong ALSA device names, missing group membership (audio/input), JACK can't open the audio device.

**Permission denied on keyboard:** Add your user to the `input` group: `sudo usermod -aG input $USER` then log out and back in.
