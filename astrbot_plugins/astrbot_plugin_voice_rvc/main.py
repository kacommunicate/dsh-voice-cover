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
"""把 AstrBot 的文字回复转成 RVC 语音一起发出去（Edge TTS → RVC API → 语音条）。"""
import asyncio
import os
import subprocess
import uuid

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain, Record
from astrbot.api.star import Context, Star, register

RVC_API = "http://127.0.0.1:7865"
SHARED = TTS_ROOT + r"\rvc-share"
FFMPEG = RVC_ROOT + r"\ffmpeg.exe"
MODEL = "m33.pth"
INDEX = RVC_ROOT + r"\models_ascii_all\m33.index"
INDEX_RATE = 0.3
PROTECT = 0.33
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
SOVITS_API = "http://127.0.0.1:3210"
SOVITS_REF = TTS_ROOT + r"\ref\ref.wav"
SOVITS_PROMPT = "你们男生才不会在说晚安之后就老老实实去睡觉。"
MAX_CHARS = 150
MIN_CHARS = 1


@register("astrbot_plugin_voice_rvc", "dsh", "RVC 语音回复", "1.0.0")
class VoiceRVC(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        os.makedirs(os.path.join(SHARED, "input"), exist_ok=True)
        os.makedirs(os.path.join(SHARED, "output"), exist_ok=True)
        self._model_loaded = False
        self._busy = False
        self._cleanup_outputs()
        logger.info(f"[voice_rvc] 已加载 | RVC={RVC_API} | 模型={MODEL} | index_rate={INDEX_RATE}")

    def _cleanup_outputs(self, keep: int = 40) -> None:
        """只保留最近 keep 个语音文件，避免无限堆积。"""
        try:
            outdir = os.path.join(SHARED, "output")
            files = sorted((os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith(".wav")),
                           key=os.path.getmtime, reverse=True)
            for old in files[keep:]:
                os.remove(old)
        except Exception as e:
            logger.debug(f"[voice_rvc] 清理旧语音失败: {e}")

    async def _ensure_model(self, session: aiohttp.ClientSession) -> None:
        if self._model_loaded:
            return
        async with session.post(f"{RVC_API}/run/infer_change_voice",
                                json={"data": [MODEL, PROTECT, PROTECT]}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"加载模型失败 HTTP {resp.status}")
        self._model_loaded = True

    async def _tts(self, text: str, path: str) -> None:
        """优先用 GPT-SoVITS（有情绪/语气），失败再退回 Edge TTS。"""
        for attempt in (1, 2):
            try:
                await self._tts_sovits(text, path)
                return
            except Exception as e:
                logger.warning(f"[voice_rvc] GPT-SoVITS 第{attempt}次失败({e})")
                await asyncio.sleep(1.5)
        logger.warning("[voice_rvc] GPT-SoVITS 两次都失败，退回 Edge TTS")
        await self._tts_edge(text, path)

    async def _tts_sovits(self, text: str, path: str) -> None:
        payload = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": SOVITS_REF,
            "prompt_text": SOVITS_PROMPT,
            "prompt_lang": "zh",
            "text_split_method": "cut0",
            "batch_size": 1,
            "media_type": "wav",
            "streaming_mode": False,
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 15,
            "repetition_penalty": 1.35,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{SOVITS_API}/tts", json=payload,
                                    timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"GPT-SoVITS HTTP {resp.status}: {(await resp.text())[:150]}")
                data = await resp.read()
        if len(data) < 2000:
            raise RuntimeError(f"GPT-SoVITS 返回过短 {len(data)} 字节")
        with open(path, "wb") as f:
            f.write(data)

    async def _tts_edge(self, text: str, path: str) -> None:
        import edge_tts
        mp3 = path + ".mp3"
        communicate = edge_tts.Communicate(text, TTS_VOICE)
        await communicate.save(mp3)
        await asyncio.to_thread(
            subprocess.run,
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", mp3,
             "-ar", "44100", "-ac", "1", path],
            check=True,
        )
        try:
            os.remove(mp3)
        except OSError:
            pass

    async def _convert(self, in_path: str) -> str:
        async with aiohttp.ClientSession() as session:
            await self._ensure_model(session)
            payload = {"data": [0, in_path, 0, None, "rmvpe", INDEX if INDEX_RATE > 0 else "",
                                "null", INDEX_RATE, 3, 0, 0.25, PROTECT]}
            async with session.post(f"{RVC_API}/run/infer_convert", json=payload,
                                    timeout=aiohttp.ClientTimeout(total=300)) as resp:
                body = await resp.json()
                if resp.status != 200 or body.get("error"):
                    raise RuntimeError(body.get("error") or f"HTTP {resp.status}")
                name = body["data"][1]["name"]
            out_path = os.path.join(SHARED, "output", f"reply_{uuid.uuid4().hex}.wav")
            async with session.get(f"{RVC_API}/file={name}") as r:
                if r.status != 200:
                    raise RuntimeError(f"下载失败 HTTP {r.status}")
                with open(out_path, "wb") as f:
                    f.write(await r.read())
            return out_path

    @filter.on_llm_response(priority=10)
    async def _hook_llm_response(self, event: AstrMessageEvent, resp):
        logger.info("[voice_rvc] on_llm_response 触发")
        await self.maybe_voice(event)

    @filter.on_agent_done(priority=10)
    async def _hook_agent_done(self, event: AstrMessageEvent, run_context, llm_response):
        logger.info("[voice_rvc] on_agent_done 触发")
        await self.maybe_voice(event)
    @filter.on_decorating_result(priority=10)
    async def maybe_voice(self, event: AstrMessageEvent):
        try:
            result = event.get_result()
            chain = getattr(result, "chain", None) or []
            logger.info(f"[voice_rvc] decorating 触发 | chain_len={len(chain)} types={[type(c).__name__ for c in chain]}")
            text = "".join(getattr(c, "text", "") for c in chain if isinstance(c, Plain)).strip()
            if not text or len(text) > MAX_CHARS:
                return
            # 跳过翻唱进度提示、命令回执这类系统消息，别把它们也转成语音
            if text.startswith(("🎤", "🎵", "📥", "🧠", "🎚")) or "我去学" in text:
                return
            if any(kw in text for kw in ("找到音源", "回复「是」", "换到：", "这次没唱成",
                                         "没找到", "开始唱", "整首大约", "好，这次不唱",
                                         "暂时没搜到")):
                return
            if event.get_extra("no_voice", False):
                return
            if self._busy:
                logger.info("[voice_rvc] 上一条还在转换，跳过本条语音")
                return
            if any(isinstance(c, Record) for c in chain):
                return
            self._busy = True
            in_path = os.path.join(SHARED, "input", "tts_input.wav")
            await self._tts(text, in_path)
            out_path = await self._convert(in_path)
            # 用户要求：发语音就不发文字。纯文字消息直接替换成语音；
            # 含图片等其它组件时只移除文字，保留其它内容
            if all(isinstance(c, Plain) for c in chain):
                chain.clear()
            else:
                chain[:] = [c for c in chain if not isinstance(c, Plain)]
            chain.append(Record(file=out_path, url=out_path))
            logger.info(f"[voice_rvc] 已追加语音：{out_path}（{len(text)} 字）")
        except Exception as e:
            logger.warning(f"[voice_rvc] 转语音失败，仅发文字：{e}")
        finally:
            self._busy = False