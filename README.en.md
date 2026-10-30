# dsh-voice-cover · Make your pet *speak* and *sing* on QQ

AstrBot plugins + scripts that give your **大肥鱼 (DafeiYu / "Big Fat Fish")** a real voice on QQ:
it replies with **voice messages** instead of plain text, and it can **cover any song** you ask for —
just say “I want to hear <song>”.

> This repository ships **no voice models (.pth/.index), no reference audio, no API keys and no QQ accounts**.
> Bring your own models and respect their licenses.

---

## What it does

| Capability | How you use it | What happens |
|---|---|---|
| **Speak** | just chat with the bot | every reply becomes a voice message (GPT-SoVITS clone → RVC timbre → SILK) |
| **Sing (clip)** | “我想听 知了” / “唱一首 知了” | finds the song, separates vocals, converts timbre, returns a 45 s voice message |
| **Sing (full)** | “我想听整首歌 知了” | same pipeline on the whole track, delivered as a file |
| **Instrumental-free** | add “不要伴奏 / 清唱” | outputs the converted vocal only |

Before any singing starts the bot **reports the source it found** (platform · title · artist · quality)
and waits for your “yes”, so you never burn 8 minutes on a wrong cover version.

---

## Architecture

```
QQ  ──► SnowLuma / NapCat (OneBot v11)
          │
          ▼
       AstrBot 4.x
          ├── astrbot_plugin_voice_rvc    every reply → voice
          └── astrbot_plugin_sing_cover   song request → cover
                     │
        ┌────────────┴─────────────┐
        ▼                          ▼
  GPT-SoVITS :3210          RVC API :7865 (shared/rvc_api.py)
  (voice cloning,           (Gradio-compatible wrapper
   expressive prosody)       around RVC infer.cli)
                                   │
                          demucs (vocal separation)
                                   │
                             ffmpeg (mix / loudnorm)
```

### Speak path

```
LLM text → GPT-SoVITS /tts (reference-audio clone) → RVC convert → pysilk SILK → QQ voice message
```

### Sing path

```
"我想听 X" → resolve song (local library → online source, original-artist first)
          → confirm with the user
          → loudness-based chorus window (55 s) or whole track
          → demucs separation (cached per song/window)
          → gender detection from 10th-percentile F0 → pitch (+12 for male sources, 0 for female)
          → RVC conversion (cross-gender: protect .25 / index .50 / rms .50)
          → mix (vocal 1.35 / instrumental 0.45) or vocal-only
          → 45 s voice message, or full-file delivery
```

---

## Requirements

| Component | Purpose | Notes |
|---|---|---|
| Python 3.10+ | scripts | one venv for TTS, one for RVC is simplest |
| GPT-SoVITS v2 | speech synthesis | ships `api_v2.py`, listens on 3210 |
| RVC | timbre conversion | `infer.cli`, needs your own `.pth` / `.index` |
| demucs | vocal separation | `pip install demucs`; `htdemucs_ft` recommended |
| ffmpeg | transcode / mix | on PATH or set `FFMPEG_BIN` |
| pysilk | SILK encoding | required for QQ voice messages |
| AstrBot ≥ 4.29.3 | bot framework | drop both plugins into `data/plugins/` |
| SnowLuma / NapCat | QQ protocol | provides a OneBot v11 HTTP API |

---

## Quick start

```bash
git clone https://github.com/kacommunicate/dsh-voice-cover.git
cp .env.example .env        # fill in your paths and credentials
```

### 1. Start the RVC API (used by both paths)

```bash
python shared/rvc_api.py            # 127.0.0.1:7865
```

### 2. Speak

```bash
python speech/say_svc.py --text "hello there" --out out.wav
python speech/send_wav.py --to <your-qq> --file out.wav
```

### 3. Sing

```bash
python cover/sing_song.py "song.mp3" --model <model-name> --dur 45
```

Or through AstrBot: copy the two plugin folders into `data/plugins/`,
add their names to `plugin_set` in `data/cmd_config.json`, and set the RVC API URL in the plugin config.

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `TTS_ROOT` | `F:\TTS` | working root |
| `RVC_ROOT` | `F:\rvc` | RVC installation |
| `RVC_MODELS_DIR` | `<RVC_ROOT>/models_ascii_all` | model directory — **keep it ASCII-only**, faiss silently fails on non-ASCII paths |
| `VOICE_SHARED_DIR` | `<TTS_ROOT>/rvc-share` | temporary voice files |
| `COVER_OUT_DIR` | `F:\翻唱` | cover output (one folder per song) |
| `SNOWLUMA_API` | `http://127.0.0.1:3000` | OneBot HTTP endpoint |
| `SNOWLUMA_TOKEN` | empty | OneBot access token |
| `BOT_QQ` / `OWNER_QQ` | 10001 / 10002 | bot / owner QQ numbers |
| `RVC_MODEL` | `m30` | default voice model name (no `.pth`) |
| `SOVITS_API` | `http://127.0.0.1:3210` | GPT-SoVITS endpoint |
| `SOVITS_REF` | `<TTS_ROOT>/ref/ref.wav` | reference audio for speech |
| `SOVITS_PROMPT_TEXT` | empty | transcript of the reference audio |

---

## Gotchas we already hit

1. **Non-ASCII paths + faiss** — RVC fails to load its index from Chinese-named folders *without any error*; use an ASCII path.
2. **RVC fp16** — on some GPUs (e.g. GTX 1650) half precision randomly emits silence; use fp32.
3. **GPT-SoVITS text splitting** — `cut5` truncates short sentences; use `cut0` for short text.
4. **QQ voice messages** — encode with `pysilk` to `#!SILK_V3` and send via a `file://` path; base64 records are unplayable in QQ.
5. **Gender pitch shift** — the *median* F0 is fooled by harmonics (a male voice reads as 190 Hz → only +3 semitones). Use the **10th percentile**.
6. **AstrBot plugin whitelist** — `plugin_set` must contain the plugin, and it matches the `@register` **name**, not the folder name.
7. **Do not voice-convert system messages** — confirmation cards and progress hints must skip TTS+RVC, otherwise they block the send pipeline.

---

## License / disclaimer

- No voice models, reference audio or credentials are included; train or license your own.
- Covering songs involves original copyrights — use for personal study only.
