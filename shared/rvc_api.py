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
r"""RVC 本地 Gradio 兼容 API（供 astrbot_plugin_rvc 调用）。

实现 RVC-WebUI 的两个接口：
  POST /run/infer_change_voice  {"data":[model, protect, protect]}
  POST /run/infer_convert       {"data":[sid, in_path, transpose, f0_file, f0_method,
                                         index_path, "null", index_rate, filter_radius,
                                         resample, rms_mix_rate, protect]}
  GET  /file=<name>             下载结果
底层调 F:\rvc\.venv 的 infer.cli。
"""
import os
import subprocess
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

MODELS = MODELS_DIR
LEGACY = RVC_ROOT + r"\assets\weights"
OUTDIR = TTS_ROOT + r"\rvc_api_out"
RVC_PY = RVC_ROOT + r"\.venv\Scripts\python.exe"
RVC_ROOT = RVC_ROOT + r""
os.makedirs(OUTDIR, exist_ok=True)

app = FastAPI()
state = {"model": os.path.join(MODELS, "m30.pth")}


def resolve_model(name: str) -> str:
    if not name:
        return state["model"]
    name = os.path.basename(name)
    for cand in (os.path.join(MODELS, name),
                 os.path.join(LEGACY, name),
                 os.path.join(MODELS, os.path.splitext(name)[0] + ".pth")):
        if os.path.isfile(cand):
            return cand
    return state["model"]


@app.post("/run/infer_change_voice")
async def infer_change_voice(req: Request):
    body = await req.json()
    data = body.get("data") or []
    name = data[0] if data else ""
    state["model"] = resolve_model(name)
    return JSONResponse({"data": [], "error": None})


@app.post("/run/infer_convert")
async def infer_convert(req: Request):
    body = await req.json()
    data = body.get("data") or []
    try:
        in_path = data[1]
        transpose = int(data[2] or 0)
        f0_method = data[4] or "rmvpe"
        index_path = data[5] or ""
        index_rate = float(data[7] or 0)
        rms_mix = float(data[10] or 0.25)
        protect = float(data[11] or 0.33)
    except Exception as e:
        return JSONResponse({"data": None, "error": f"参数解析失败: {e}"})

    if not os.path.isfile(in_path):
        return JSONResponse({"data": None, "error": f"输入文件不存在: {in_path}"})

    out_name = f"rvc_{uuid.uuid4().hex}.wav"
    out_path = os.path.join(OUTDIR, out_name)
    cmd = [RVC_PY, "-m", "infer.cli", "--model", state["model"], "--input", in_path,
           "--output", out_path, "--pitch", str(transpose), "--f0-method", f0_method,
           "--index-rate", str(index_rate), "--protect", str(protect),
           "--rms-mix-rate", str(rms_mix), "--overwrite"]
    if index_rate > 0 and os.path.isfile(index_path):
        cmd += ["--index", index_path]
    r = subprocess.run(cmd, cwd=RVC_ROOT, capture_output=True, text=True, errors="replace", timeout=1800)
    if r.returncode != 0 or not os.path.isfile(out_path):
        return JSONResponse({"data": None, "error": (r.stderr or r.stdout or "")[-400:]})
    return JSONResponse({"data": [None, {"name": out_name, "path": out_path}]})


@app.get("/file={name}")
async def get_file(name: str):
    path = os.path.join(OUTDIR, os.path.basename(name))
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


@app.get("/")
async def root():
    return {"status": "ok", "model": state["model"], "models_dir": MODELS}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7865, log_level="info")