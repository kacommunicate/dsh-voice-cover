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
r"""翻唱流水线：歌曲 → 分离人声/伴奏 → RVC 换音色 → 后处理 → 混音。

用法：
  python sing_song.py "F:\歌.mp3"                     # 整首
  python sing_song.py "F:\歌.mp3" --start 20 --dur 30 # 只做 20-50 秒
  python sing_song.py "F:\歌.mp3" --model siyu --pitch 0
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = TTS_ROOT + r""
SING = os.path.join(ROOT, "sing")
OUT = os.path.join(SING, "out")
FFMPEG = RVC_ROOT + r"\ffmpeg.exe"
DEMUCS = r"F:\BasicPitch\venv\Scripts\demucs.exe"
RVC_PY = RVC_ROOT + r"\.venv\Scripts\python.exe"
WEIGHTS = RVC_ROOT + r"\assets\weights"
MODELS_ASCII = RVC_ROOT + r"\models_ascii_all"
RVC_ROOT = RVC_ROOT + r""


def run(cmd, desc, timeout=7200, cwd=None):
    print(f"\n== {desc}")
    print("   " + " ".join(str(c) for c in cmd[:8]) + (" ..." if len(cmd) > 8 else ""))
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       errors="replace", timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        print("   失败：" + ((r.stderr or r.stdout or "")[-600:]))
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("--model", default="m30", help="模型名（优先在 models_ascii_all 里找）")
    ap.add_argument("--pitch", type=int, default=0, help="半音：男声原唱转女声用 12，女声原唱用 0")
    ap.add_argument("--index-rate", type=float, default=0.0, help="特征索引强度，0=不用索引（本机实测 0 最干净）")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=0.0, help="0 = 整首")
    ap.add_argument("--inst-volume", type=float, default=0.45)
    ap.add_argument("--vocal-volume", type=float, default=1.35)
    a = ap.parse_args()

    song = os.path.abspath(a.song)
    if not os.path.isfile(song):
        print("找不到文件：", song)
        return 2
    if a.model.endswith(".pth") or os.path.sep in a.model:
        model = a.model
    else:
        model = os.path.join(MODELS_ASCII, a.model + ".pth")
        if not os.path.isfile(model):
            model = os.path.join(WEIGHTS, a.model + ".pth")
    if not os.path.isfile(model):
        print("找不到模型：", model)
        print("可用（英文目录）：" + ", ".join(sorted(p.stem for p in __import__("pathlib").Path(MODELS_ASCII).glob("*.pth"))))
        return 2
    index_path = os.path.splitext(model)[0] + ".index"
    if a.index_rate > 0 and not os.path.isfile(index_path):
        print(f"提示：{index_path} 不存在，index-rate 视为 0")
        a.index_rate = 0.0

    name = os.path.splitext(os.path.basename(song))[0]
    work = os.path.join(SING, f"work_{name}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    src = os.path.join(work, "src.wav")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if a.start > 0:
        cmd += ["-ss", str(a.start)]
    if a.dur > 0:
        cmd += ["-t", str(a.dur)]
    cmd += ["-i", song, "-ar", "44100", "-ac", "2", src]
    if run(cmd, "抽取音频") != 0:
        return 1

    if run([DEMUCS, "-n", "htdemucs", "--two-stems=vocals", "-o", work, src],
           "分离人声 / 伴奏（CPU）") != 0:
        return 1
    stem = os.path.join(work, "htdemucs", "src")
    vocals, inst = os.path.join(stem, "vocals.wav"), os.path.join(stem, "no_vocals.wav")
    if not (os.path.isfile(vocals) and os.path.isfile(inst)):
        print("分离产物缺失：", stem)
        return 1

    conv = os.path.join(work, "conv.wav")
    rvc_cmd = [RVC_PY, "-m", "infer.cli", "--model", model, "--input", vocals, "--output", conv,
               "--pitch", a.pitch, "--f0-method", "rmvpe",
               "--index-rate", a.index_rate, "--protect", "0.4",
               "--rms-mix-rate", "0.95", "--overwrite"]
    if a.index_rate > 0:
        rvc_cmd += ["--index", index_path]
    if run(rvc_cmd,
           f"RVC 换音色：{os.path.basename(model)}（音高 {a.pitch:+d}, index {a.index_rate}）",
           cwd=RVC_ROOT, timeout=3600) != 0:
        return 1

    post = os.path.join(work, "conv_post.wav")
    if run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", conv,
            "-af", "highshelf=f=8000:g=-2,afftdn=nf=-32,loudnorm=I=-16:TP=-1.5",
            "-ar", "44100", "-ac", "1", post], "人声后处理") != 0:
        return 1

    out = os.path.join(OUT, f"{name}_{a.model}.wav")
    if run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", post, "-i", inst,
            "-filter_complex",
            f"[0:a]volume={a.vocal_volume}[v];[1:a]volume={a.inst_volume}[i];"
            f"[v][i]amix=inputs=2:duration=longest,loudnorm=I=-13:TP=-1.0[o]",
            "-map", "[o]", "-ar", "44100", "-ac", "2", out], "混音") != 0:
        return 1

    print(f"\n完成：{out}")
    print(f"RESULT_PATH={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())