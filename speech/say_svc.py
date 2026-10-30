# -*- coding: utf-8 -*-
# ---------------------------------------------------------------
# 本文件来自 dsh-voice-cover 开源版，已移除密钥与音色模型。
# 路径 / 凭据请用环境变量覆盖，见仓库根目录 .env.example
# ---------------------------------------------------------------
import os as _os

TTS_ROOT = _os.environ.get("TTS_ROOT", r"F:\TTS")
RVC_ROOT = _os.environ.get("RVC_ROOT", r"F:\rvc")
MODELS_DIR = _os.environ.get("RVC_MODELS_DIR", _os.path.join(RVC_ROOT, "models_ascii_all"))
SHARED_DIR = _os.environ.get("VOICE_SHARED_DIR", r"F:\TTS\rvc-share")
OUT_DIR = _os.environ.get("COVER_OUT_DIR", r"F:\翻唱")
SNOWLUMA_API = _os.environ.get("SNOWLUMA_API", "http://127.0.0.1:3000")
SNOWLUMA_TOKEN = _os.environ.get("SNOWLUMA_TOKEN", "")
BOT_QQ = int(_os.environ.get("BOT_QQ", "10001"))
OWNER_QQ = int(_os.environ.get("OWNER_QQ", "10002"))
RVC_MODEL = _os.environ.get("RVC_MODEL", "m30")
SOVITS_API = _os.environ.get("SOVITS_API", "http://127.0.0.1:3210")
SOVITS_REF = _os.environ.get("SOVITS_REF", _os.path.join(TTS_ROOT, "ref", "ref.wav"))
SOVITS_PROMPT = _os.environ.get("SOVITS_PROMPT_TEXT", "")

# -*- coding: utf-8 -*-
r"""说话：调 GPT-SoVITS /tts（3210）。fp32 + 时长校验 + 重试。

背景（本机实测）：
- is_half=true 时 v2 模型会随机输出纯静音（-91 dB）→ 已改 fp32
- text_split_method=cut5 对短句会截断（只念第一个词）→ 改 cut0
- 偶尔会「失控」生成超长音频 → 用时长上限判定后重试
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

API = os.environ.get("SOVITS_API", "http://127.0.0.1:3210")
REF = os.environ.get("SOVITS_REF", TTS_ROOT + "\\ref\\ref.wav")
PROMPT = os.environ.get("SOVITS_PROMPT_TEXT", "你们男生才不会在说晚安之后就老老实实去睡觉。")
SPEED = float(os.environ.get("SOVITS_SPEED", "1.0"))
FFMPEG = os.environ.get("FFMPEG_BIN", RVC_ROOT + r"\ffmpeg.exe")
TEMPERATURE = float(os.environ.get("SOVITS_TEMPERATURE", "0.7"))
TOP_P = float(os.environ.get("SOVITS_TOP_P", "0.9"))
TOP_K = int(os.environ.get("SOVITS_TOP_K", "15"))
REP = float(os.environ.get("SOVITS_REP_PENALTY", "1.35"))
MIN_DB = float(os.environ.get("SOVITS_MIN_DB", "-45"))
SEC_PER_CHAR = float(os.environ.get("SOVITS_SEC_PER_CHAR", "0.22"))


def _tts_once(text: str, ref: str, prompt: str, out: str) -> None:
    payload = {
        "text": text, "text_lang": "zh", "ref_audio_path": ref,
        "prompt_text": prompt, "prompt_lang": "zh",
        "text_split_method": "cut0", "batch_size": 1,
        "media_type": "wav", "streaming_mode": False,
        "temperature": TEMPERATURE, "top_p": TOP_P, "top_k": TOP_K,
        "repetition_penalty": REP,
    }
    req = urllib.request.Request(f"{API}/tts", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as r:
        audio = r.read()
    with open(out, "wb") as f:
        f.write(audio)


def _probe(path: str) -> tuple[float, float]:
    """返回 (duration, mean_db)。"""
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace")
    log = (p.stderr or "") + (p.stdout or "")
    d = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", log)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", log)
    return dur, (float(m.group(1)) if m else 0.0)


def _stretch(path: str, speed: float) -> None:
    if abs(speed - 1.0) < 0.01:
        return
    tmp = path + ".spd.wav"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                    "-filter:a", f"atempo={speed}", tmp], check=True)
    os.replace(tmp, path)


def speak(text: str, ref: str, prompt: str, out: str, attempts: int = 4) -> tuple[float, float]:
    chars = len(re.sub(r"[，。！？、,.!?\s]", "", text))
    expect = max(1.2, chars * SEC_PER_CHAR)
    last = (0.0, -999.0)
    for i in range(1, attempts + 1):
        _tts_once(text, ref, prompt, out)
        dur, db = _probe(out)
        last = (dur, db)
        ok = db > MIN_DB and 0.55 * expect <= dur <= 2.0 * expect
        if ok:
            return last
        print(f"  [retry {i}/{attempts}] dur={dur:.2f}s(expect~{expect:.2f}) mean={db:.1f}dB", file=sys.stderr)
    raise RuntimeError(f"连续 {attempts} 次生成不合格（最后一次 {last[0]:.2f}s {last[1]:.1f}dB）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", default=REF)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--speed", type=float, default=SPEED)
    a = ap.parse_args()
    if not os.path.isfile(a.ref):
        print("参考音不存在：", a.ref)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    dur, db = speak(a.text, a.ref, a.prompt, a.out)
    _stretch(a.out, a.speed)
    print(f"OK out={a.out} dur={dur:.2f}s mean={db:.1f}dB speed={a.speed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())