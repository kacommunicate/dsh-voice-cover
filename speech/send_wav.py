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
r"""发语音：wav → 响度标准化 → SILK（16k）→ 以 file:// 路径发 QQ 语音条。

用法：
  python send_wav.py --to OWNER_QQ --file out.wav
  python send_wav.py --group 123456789 --file out.wav
需要 pysilk（用 AstrBot 的 venv：F:\AstrBot\venv\Scripts\python.exe）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

API = os.environ.get("SNOWLUMA_API", "http://127.0.0.1:3000")
TOKEN = os.environ.get("SNOWLUMA_TOKEN", "")
FFMPEG = os.environ.get("FFMPEG_BIN", RVC_ROOT + r"\ffmpeg.exe")
LOUDNORM = os.environ.get("VOICE_LOUDNORM", "loudnorm=I=-15:TP=-1.5:LRA=11")


def call(action, payload, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/{action}", data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def wav_to_silk(src: str) -> str:
    import pysilk

    tmpdir = tempfile.mkdtemp(prefix="silk_")
    pcm_wav = os.path.join(tmpdir, "in16k.wav")
    silk_path = os.path.join(tmpdir, "out.silk")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
                    "-ar", "16000", "-ac", "1", "-af", LOUDNORM,
                    "-c:a", "pcm_s16le", pcm_wav], check=True)
    with open(pcm_wav, "rb") as fi, open(silk_path, "wb") as fo:
        pysilk.encode(fi, fo, 16000, 24000, tencent=True)
    return silk_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to")
    ap.add_argument("--group")
    ap.add_argument("--file", required=True, help="wav 文件，或已经是 .silk")
    a = ap.parse_args()

    path = os.path.abspath(a.file)
    if not os.path.isfile(path):
        print("找不到文件：", path)
        return 2
    if not path.lower().endswith(".silk"):
        path = wav_to_silk(path)
    uri = "file:///" + path.replace("\\", "/")
    seg = [{"type": "record", "data": {"file": uri}}]

    if a.group:
        res = call("send_group_msg", {"group_id": int(a.group), "message": seg}, timeout=180)
    elif a.to:
        res = call("send_private_msg", {"user_id": int(a.to), "message": seg}, timeout=180)
    else:
        print("要指定 --to 或 --group")
        return 2
    print("OK" if res.get("status") in ("ok", "async") else "FAIL", res)
    return 0 if res.get("status") in ("ok", "async") else 1


if __name__ == "__main__":
    sys.exit(main())