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
"""点歌翻唱（带确认）：找到音源后先报「来源/歌名/歌手」，你回「是」才开唱。

- 「不要伴奏 / 清唱」→ 只输出人声
- 「整首歌 / 整首 / 全曲」→ 整首翻唱（文件发送）
- 找到歌先确认，回「是」开始；回「换一个」换版本；回「取消」放弃
"""
import asyncio
import os
import re
import sys
import time
import traceback

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Record
from astrbot.api.star import Context, Star, register

sys.path.insert(0, TTS_ROOT + r"\scripts")
import sing_cover  # noqa: E402

MODEL = RVC_MODEL
DUR = 45
MAX_SECONDS = 5400
PENDING_TTL = 300  # 确认状态保留 5 分钟

NO_INST = re.compile(r"(?:不要|不带|去掉|去除|没有|无|去|别)\s*伴奏|清唱|纯人声|只要人声|无人声伴奏|不要音乐")
FULL = re.compile(r"整首歌|整首|整曲|全曲|完整版|从头到尾|全首")
FILLER = re.compile(r"^(?:一下|一首|歌曲|音乐)\s*")
VERB = re.compile(r"^(?:我想听|想听|来一首|唱一首|唱|翻唱|点歌)\s*")

YES = re.compile(r"^(?:是|对|对呀|对的|没错|好|好的|可以|行|开始|唱吧|确认|ok|okay|嗯嗯?|就是它)[!！。.，,\s]*$", re.I)
SWAP = re.compile(r"^(?:换一个|换一首|换一个版本|不是|不对|别的|另一个|再找)[!！。.，,\s]*$")
NO = re.compile(r"^(?:取消|算了|不用了?|不要了|不唱了)[!！。.，,\s]*$")

SONG_PATTERNS = [
    re.compile(r"^(?:唱|翻唱|点歌)\s*(.+)$"),
    re.compile(r"^(?:我想听|想听|来一首|唱一首)\s*(.+)$"),
]


@register("astrbot_plugin_sing_cover", "dsh", "点歌翻唱", "1.1.0")
class SingCover(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._pending = {}   # umo -> dict(song, vocals_only, full, path, meta, ts, tried)
        self._busy = {}
        logger.info(f"[sing_cover] 已加载 | 模型={MODEL} | 片段={DUR}s | 整首=文件 | 先确认后唱")

    # ---------- 解析 ----------
    @staticmethod
    def _parse(raw: str):
        raw = raw or ""
        vocals_only = bool(NO_INST.search(raw))
        full = bool(FULL.search(raw))
        song = FILLER.sub("", FULL.sub("", NO_INST.sub("", raw)))
        song = VERB.sub("", song)
        song = song.strip(" 《》<>\"'，,。.!！?？")
        return song, vocals_only, full

    def _pending_of(self, event):
        umo = event.unified_msg_origin
        item = self._pending.get(umo)
        if item and time.time() - item["ts"] > PENDING_TTL:
            self._pending.pop(umo, None)
            return None
        return item

    # ---------- 点歌（先确认） ----------
    @filter.regex(r"(?:唱|翻唱|点歌|我想听|想听|来一首|唱一首)")
    async def cmd_sing(self, event: AstrMessageEvent):
        event.set_extra("no_voice", True)
        text = event.get_message_str().strip()
        if YES.match(text) or SWAP.match(text) or NO.match(text):
            return  # 交给确认处理器
        song, vocals_only, full = self._parse(text)
        if not song:
            yield event.plain_result("告诉我歌名呗，比如：我想听知了")
            return
        if self._busy.get(event.unified_msg_origin):
            yield event.plain_result("刚有人在点歌，等我唱完这首🎤")
            return
        try:
            meta = await asyncio.to_thread(sing_cover.resolve_song_info, song)
        except Exception as e:
            logger.warning(f"[sing_cover] 找歌失败: {e}")
            yield event.plain_result(f"没找到《{song}》：{str(e)[:80]}")
            return
        self._pending[event.unified_msg_origin] = {
            "song": song, "vocals_only": vocals_only, "full": full,
            "path": meta["path"], "meta": meta, "ts": time.time(),
            "tried": {meta["path"]},
        }
        tag = "整首" if full else f"{DUR} 秒"
        mode = "清唱（去伴奏）" if vocals_only else "带伴奏"
        yield event.plain_result(
            f"找到音源：{meta.get('source','?')} · 《{meta.get('title','?')}》- {meta.get('artist') or '未知歌手'}"
            f"（{meta.get('quality','?')}）\n"
            f"计划：{tag} · {mode}\n"
            f"回复「是」开始翻唱；回「换一个」换版本；回「取消」放弃。"
        )

    # ---------- 确认 / 换一个 / 取消 ----------
    @filter.regex(r"^(?:是|对|对呀|对的|没错|好|好的|可以|行|开始|唱吧|确认|ok|okay|嗯嗯?|就是它|换一个|换一首|换一个版本|不是|不对|别的|另一个|再找|取消|算了|不用了?|不要了|不唱了)")
    async def confirm(self, event: AstrMessageEvent):
        event.set_extra("no_voice", True)
        text = event.get_message_str().strip()
        item = self._pending_of(event)
        if not item:
            return
        umo = event.unified_msg_origin
        if NO.match(text):
            self._pending.pop(umo, None)
            yield event.plain_result("好，这次不唱了。")
            return
        if SWAP.match(text):
            try:
                meta = await asyncio.to_thread(sing_cover.resolve_song_info, item["song"])
            except Exception as e:
                yield event.plain_result(f"换版本失败：{str(e)[:80]}")
                return
            if meta["path"] in item["tried"]:
                yield event.plain_result("暂时没搜到别的版本，回「是」就用这个，或者回「取消」。")
                return
            item.update({"path": meta["path"], "meta": meta, "ts": time.time()})
            item["tried"].add(meta["path"])
            yield event.plain_result(
                f"换到：{meta.get('source','?')} · 《{meta.get('title','?')}》- {meta.get('artist') or '未知歌手'}"
                f"（{meta.get('quality','?')}）\n回「是」开始，回「换一个」继续换，回「取消」放弃。"
            )
            return
        if not YES.match(text):
            return
        self._pending.pop(umo, None)
        async for r in self._do_cover(event, item):
            yield r

    # ---------- 执行翻唱 ----------
    async def _do_cover(self, event: AstrMessageEvent, item: dict):
        event.set_extra("no_voice", True)
        umo = event.unified_msg_origin
        if self._busy.get(umo):
            yield event.plain_result("刚有人在点歌，等我唱完这首🎤")
            return
        self._busy[umo] = True
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress(msg: str):
            loop.call_soon_threadsafe(queue.put_nowait, msg)

        async def runner():
            try:
                return await asyncio.to_thread(
                    sing_cover.run_cover, item["song"], MODEL, None,
                    0 if item["full"] else DUR, None, 0.45, 1.35,
                    progress, item["vocals_only"], 0.3, item["full"], item["path"],
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        kind = "清唱" if item["vocals_only"] else "翻唱"
        span = "整首" if item["full"] else f"{DUR} 秒"
        eta = "整首大约 30–50 分钟" if item["full"] else "大概 5–8 分钟"
        yield event.plain_result(f"好，开始唱《{item['song']}》的{kind}（{span}）🎵 {eta}")
        task = asyncio.create_task(runner())
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    break
                yield event.plain_result(f"🎤 {msg}…")
            out = await asyncio.wait_for(task, timeout=MAX_SECONDS)
            if out and os.path.isfile(out):
                if item["full"]:
                    yield event.chain_result([File(name=os.path.basename(out), file=out, url=out)])
                else:
                    yield event.chain_result([Record(file=out, url=out)])
            else:
                yield event.plain_result("唱完了但没拿到音频文件…")
        except Exception as e:
            logger.error(f"[sing_cover] 失败: {e}\n{traceback.format_exc()}")
            yield event.plain_result(f"这次没唱成：{str(e)[:120]}")
        finally:
            self._busy[umo] = False