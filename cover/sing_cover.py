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
r"""点歌翻唱核心：解析歌名 → 找歌 → 选高潮片段 → 分离 → RVC 换音色 → 混音。

可作为模块调用：run_cover("知了", model="m30") -> 输出 wav 路径
也可命令行：python sing_cover.py "知了" --model m30 --dur 45
"""
import json
import os
import re
import shutil
import subprocess
import sys
import uuid

ROOT = TTS_ROOT + r""
SING = os.path.join(ROOT, "sing")
SRC = os.path.join(SING, "src")
OUT = r"F:\翻唱"
FFMPEG = RVC_ROOT + r"\ffmpeg.exe"
FFPROBE = RVC_ROOT + r"\ffprobe.exe"
DEMUCS = r"F:\BasicPitch\venv\Scripts\demucs.exe"
DEMUCS_MODEL = "htdemucs_ft"
RVC_PY = RVC_ROOT + r"\.venv\Scripts\python.exe"
RVC_ROOT = RVC_ROOT + r""
MODELS = MODELS_DIR
LAST_META = {}
LOCAL_LIB = [r"F:\sheetsage2-webui\谱子", r"E:\CloudMusic"]
YTDLP = [sys.executable, "-m", "yt_dlp"]


def safe_name(text: str) -> str:
    """把歌名变成合法目录名。"""
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", (text or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned[:60] or "未命名"


def song_dir(song: str) -> str:
    path = os.path.join(OUT, safe_name(song))
    os.makedirs(path, exist_ok=True)
    return path


def stamp() -> str:
    import time
    return time.strftime("%Y%m%d-%H%M")


def stems_dir(song: str) -> str:
    r"""分离结果缓存目录：F:\翻唱\<歌名>\分离"""
    path = os.path.join(song_dir(song), "分离")
    os.makedirs(path, exist_ok=True)
    return path


def cached_stems(song: str, key: str):
    """返回 (vocals, no_vocals) 若缓存存在，否则 None。"""
    d = os.path.join(OUT, safe_name(song), "分离")
    v = os.path.join(d, f"{key}_vocals.wav")
    i = os.path.join(d, f"{key}_no_vocals.wav")
    if os.path.isfile(v) and os.path.isfile(i):
        return v, i
    return None


def store_stems(song: str, key: str, vocals: str, inst: str) -> None:
    d = stems_dir(song)
    try:
        shutil.copy2(vocals, os.path.join(d, f"{key}_vocals.wav"))
        shutil.copy2(inst, os.path.join(d, f"{key}_no_vocals.wav"))
        print(f"[分离缓存] 已保存到 {d}/{key}_*.wav", flush=True)
    except Exception as e:
        print(f"[分离缓存] 保存失败: {e}", flush=True)


def _run(cmd, desc="", timeout=3600, cwd=None):
    if desc:
        print(f"[{desc}]", flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       errors="replace", timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"{desc} 失败: {((r.stderr or r.stdout) or '')[-400:]}")
    return r


def _set_meta(source, title, artist, quality=""):
    global LAST_META
    LAST_META = {"source": source, "title": title or "", "artist": artist or "", "quality": quality}
    return LAST_META


def _split_local_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    for sep in ["-", "_", "–"]:
        if sep in stem:
            a, b = stem.split(sep, 1)
            return a.strip(), b.strip()
    return stem, ""


def find_local(name: str):
    """在本地曲库里模糊匹配歌名。"""
    key = re.sub(r"[\s《》<>]+", "", name).lower()
    best = None
    for root in LOCAL_LIB:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith((".mp3", ".flac", ".wav", ".m4a")):
                    continue
                stem = re.sub(r"[\s《》<>]+", "", os.path.splitext(fn)[0]).lower()
                if key and key in stem:
                    full_path = os.path.join(dirpath, fn)
                    t, ar = _split_local_name(full_path)
                    _set_meta("本地曲库", t, ar, "本地")
                    return full_path
                if stem and stem in key and best is None:
                    best = os.path.join(dirpath, fn)
    return best


BILI_BAD = ["串烧", "合集", "翻唱", "伴奏", "纯音乐", "remix", "dj", "剪辑", "加速", "慢速", "cover", "教学", "教程", "合唱", "对唱"]
BILI_GOOD = ["原唱", "无损", "官方", "完整", "动态歌词", "hi-res", "音质", "歌词", "女声", "女版", "独唱"]


def bili_search(name: str, limit: int = 8):
    """用 yt-dlp 的 bilisearch 搜 B 站，返回 [(bvid, title), ...]。"""
    r = subprocess.run(YTDLP + ["--no-playlist", "--flat-playlist", "--print",
                                "%(id)s\t%(title)s", f"bilisearch{limit}:{name}"],
                       capture_output=True, text=True, errors="replace", timeout=180)
    rows = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("BV"):
            rows.append((parts[0], parts[1]))
    return rows


def _score(title: str, name: str) -> int:
    t = title.lower()
    s = 0
    if name.lower() in t:
        s += 3
    s += 2 * sum(1 for kw in BILI_GOOD if kw in t)
    s -= 3 * sum(1 for kw in BILI_BAD if kw in t)
    return s


def find_bilibili(name: str):
    """B 站搜歌 → 按标题打分挑一个视频 → 下载音频。"""
    os.makedirs(SRC, exist_ok=True)
    rows = bili_search(name)
    if not rows:
        raise RuntimeError(f"B 站没搜到「{name}」")
    print("[B站候选] " + " | ".join(f"{t[:24]}" for _, t in rows[:5]), flush=True)
    rows.sort(key=lambda kv: _score(kv[1], name), reverse=True)
    bvid = rows[0][0]
    out_tpl = os.path.join(SRC, "%(id)s.%(ext)s")
    _run(YTDLP + ["--no-playlist", "-f", "bestaudio/best", "-x", "--audio-format", "wav",
                  "--ffmpeg-location", RVC_ROOT + r"", "-o", out_tpl,
                  f"https://www.bilibili.com/video/{bvid}"], f"下载 B 站 {bvid}", timeout=900)
    path = os.path.join(SRC, f"{bvid}.wav")
    if not os.path.isfile(path):
        raise RuntimeError("下载后没找到音频文件")
    return path


HAITANG_API = "https://musicserver.haitangw.cc/v1/music/resolve-url"
DEFAULT_LEVEL = "exhigh"   # standard=128k / exhigh=320k / lossless=无损


def haitang_resolve(source: str, rid: str, level: str = DEFAULT_LEVEL) -> str:
    """海棠 musicserver：POST 拿直链（成功返回 201，code=0）。"""
    import json as _json
    import urllib.request
    body = _json.dumps({"source": source, "rid": str(rid), "level": level}).encode()
    req = urllib.request.Request(HAITANG_API, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        payload = _json.loads(r.read().decode("utf-8", "replace"))
    if payload.get("code") != 0:
        raise RuntimeError(f"{source}:{rid} 解析失败 {payload.get('message')}")
    return payload["data"]["url"]


def haitang_download(url: str, out_path: str) -> int:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        with open(out_path, "wb") as f:
            shutil.copyfileobj(r, f)
    return os.path.getsize(out_path)


def find_haitang(name: str, level: str = DEFAULT_LEVEL):
    """原唱优先：网易云/酷我搜索 → 按分数+原唱歌手排序 → 海棠解析直链下载。"""
    os.makedirs(SRC, exist_ok=True)
    canon = canonical_artist(name)
    candidates = []
    for song in netease_search(name):
        artists = "/".join(a.get("name", "") for a in (song.get("artists") or []))
        candidates.append({"source": "wy", "rid": str(song.get("id")),
                           "title": song.get("name") or "", "artist": artists})
    try:
        for rid, nm, ar in kuwo_search(name):
            candidates.append({"source": "kw", "rid": rid, "title": nm, "artist": ar})
    except Exception as e:
        print(f"[酷我搜索失败] {str(e)[:60]}", flush=True)
    if not candidates:
        raise RuntimeError(f"没搜到「{name}」")
    for c in candidates:
        c["score"] = _title_score(c["title"], name, c["artist"], canon)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    print("[候选] " + " | ".join(f"{c['source']}:{c['title'][:12]}" for c in candidates[:4]), flush=True)
    for c in candidates:
        try:
            url = haitang_resolve(c["source"], c["rid"], level)
            out = os.path.join(SRC, f"ht_{c['source']}_{c['rid']}.mp3")
            size = haitang_download(url, out)
            if size > 300_000:
                src_name = {"wy": "网易云", "kw": "酷我", "tx": "QQ音乐", "kg": "酷狗"}.get(c["source"], c["source"])
                _set_meta(src_name, c["title"], c["artist"], level)
                print(f"[海棠命中] {src_name} {c['title']} - {c['artist']} ({size/1048576:.1f}MB)", flush=True)
                return out
        except Exception as e:
            print(f"[跳过 {c['source']}:{c['rid']}] {str(e)[:70]}", flush=True)
    raise RuntimeError("海棠接口没取到可用音源")


def kuwo_search(name: str, limit: int = 8):
    """酷我公开搜索，返回 [(rid, 歌名, 歌手), ...]。"""
    import urllib.parse
    import urllib.request
    q = urllib.parse.quote(name)
    url = (f"http://search.kuwo.cn/r.s?all={q}&ft=music&itemset=web_2013&client=kt"
           f"&pn=0&rn={limit}&rformat=json&encoding=utf8")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    ids = re.findall(r"'DC_TARGETID':'(\d+)'", raw)
    names = re.findall(r"'SONGNAME':'(.*?)'", raw)
    artists = re.findall(r"'ARTIST':'(.*?)'", raw)
    rows = []
    for i, rid in enumerate(ids):
        nm = names[i] if i < len(names) else ""
        ar = artists[i] if i < len(artists) else ""
        rows.append((rid, nm, ar))
    return rows


def find_kuwo(name: str):
    """酷我搜索 + 海棠接口取直链下载（比网易云公开外链稳）。"""
    import urllib.request
    os.makedirs(SRC, exist_ok=True)
    rows = kuwo_search(name)
    if not rows:
        raise RuntimeError(f"酷我没搜到「{name}」")
    canon = canonical_artist(name)
    if canon:
        print(f"[原唱参考] {canon}", flush=True)
    rows.sort(key=lambda r: _title_score(r[1], name, r[2], canon), reverse=True)
    if canon:
        hit = [r for r in rows if r[2] and (r[2] in canon or canon in r[2])]
        if not hit:
            raise RuntimeError(f"酷我没有原唱（{canon}），改用网易云")
        rows = hit
    print("[酷我候选] " + " | ".join(f"{r[1][:14]}" for r in rows[:4]), flush=True)
    for rid, nm, ar in rows:
        url = f"https://musicapi.haitangw.net/music/kw.php?type=mp3&id={rid}&level=standard"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                if "audio" not in (r.headers.get("Content-Type") or ""):
                    continue
                out = os.path.join(SRC, f"kw_{rid}.mp3")
                with open(out, "wb") as f:
                    shutil.copyfileobj(r, f)
            if os.path.getsize(out) > 300_000:
                _set_meta("酷我", nm, ar, "standard")
                print(f"[酷我命中] {nm} - {ar}", flush=True)
                return out
        except Exception as e:
            print(f"[跳过 {rid}] {str(e)[:60]}", flush=True)
    raise RuntimeError("酷我候选都拿不到音频")


def _title_score(title: str, name: str, artists: str = "", canonical: str = "") -> int:
    """统一打分：原唱/女声/高潮加分，合唱/翻唱/现场/伴奏减分。"""
    t = (title or "").lower()
    score = 0
    if name and name.lower() in t:
        score += 3
    if "/" in (artists or "") or "/" in t:
        score -= 4  # 多歌手=合唱
    else:
        score += 3  # 单人
    GOOD = {"原唱": 3, "官方": 2, "女声": 1, "女版": 2, "女生版": 2, "独唱": 2,
            "高潮": 1, "副歌": 1, "片段": 1, "无损": 1, "完整": 1}
    BAD = {"男版": -4, "男声": -4, "合唱": -4, "对唱": -4, "粤语版": -3, "翻唱版": -2, "live": -3, "现场": -3,
           "轻快版": -1, "抖音": -2, "慢摇": -2, "抖音版": -3,
           "伴奏": -3, "纯音乐": -3, "dj": -3, "remix": -2, "串烧": -4, "合集": -3,
           "片段版": -1, "加速": -2, "慢速": -2}
    for kw, v in GOOD.items():
        if kw in t:
            score += v
    for kw, v in BAD.items():
        if kw in t and not (kw == "片段版" and "高潮" in t):
            score += v
    # 与网易云认定的原唱歌手一致 → 大幅加权（这是「原唱优先」的关键）
    if canonical and artists:
        if artists in canonical or canonical in artists:
            score += 5
    return score


def canonical_artist(name: str) -> str:
    """用网易云搜索结果第一条的歌手当作「原唱歌手」参考。"""
    try:
        songs = netease_search(name, 3)
        if songs:
            return "/".join(a.get("name", "") for a in (songs[0].get("artists") or []))
    except Exception:
        pass
    return ""


def netease_search(name: str, limit: int = 8):
    import urllib.parse
    import urllib.request
    data = urllib.parse.urlencode({"s": name, "limit": str(limit), "type": "1", "offset": "0"}).encode()
    req = urllib.request.Request(
        "http://music.163.com/api/search/get/web", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "http://music.163.com", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        import json
        j = json.loads(r.read().decode("utf-8", "replace"))
    return (j.get("result") or {}).get("songs") or []


def find_netease(name: str, prefer_artist: str = ""):
    """网易云搜索 + 公开外链下载（不需要登录，能拿到 128k mp3）。"""
    import urllib.request
    os.makedirs(SRC, exist_ok=True)
    songs = netease_search(name)
    if not songs:
        raise RuntimeError(f"网易云没搜到「{name}」")
    canon = "/".join(a.get("name", "") for a in ((songs[0].get("artists") if songs else []) or []))

    def _score(song):
        artists = " / ".join(a.get("name", "") for a in (song.get("artists") or []))
        return _title_score(song.get("name") or "", name, artists, canon)

    songs = sorted(songs, key=_score, reverse=True)
    if prefer_artist:
        first = [x for x in songs
                 if any(a.get("name", "") in prefer_artist or prefer_artist in a.get("name", "")
                        for a in (x.get("artists") or []))]
        others = [x for x in songs if x not in first]
        songs = first + others
    print("[网易云候选] " + " | ".join(f"{s.get('name','')[:16]}" for s in songs[:4]), flush=True)
    for s in songs:
        sid = s.get("id")
        if not sid:
            continue
        url = f"https://music.163.com/song/media/outer/url?id={sid}.mp3"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                       "Referer": "https://music.163.com/"})
            with urllib.request.urlopen(req, timeout=40) as r:
                if "audio" not in (r.headers.get("Content-Type") or ""):
                    continue
                out = os.path.join(SRC, f"wy_{sid}.mp3")
                with open(out, "wb") as f:
                    shutil.copyfileobj(r, f)
            if os.path.getsize(out) > 200_000:
                artists = "/".join(a.get("name", "") for a in (s.get("artists") or []))
                _set_meta("网易云", s.get("name", ""), artists, "外链")
                print(f"[网易云命中] {s.get('name')} - {artists}", flush=True)
                return out
        except Exception as e:
            print(f"[跳过 {sid}] {str(e)[:60]}", flush=True)
            continue
    raise RuntimeError("网易云的候选都拿不到音频")


def resolve_song(name: str) -> str:
    p = find_local(name)
    if p:
        print(f"[本地命中] {p}", flush=True)
        return p
    try:
        return find_haitang(name)
    except Exception as e:
        print(f"[海棠失败] {e}", flush=True)
    canon = canonical_artist(name)
    if canon:
        print(f"[原唱参考] {canon}", flush=True)
    try:
        return find_kuwo(name)
    except Exception as e:
        print(f"[酷我失败] {e}", flush=True)
    try:
        return find_netease(name, canon)
    except Exception as e:
        print(f"[网易云失败] {e}", flush=True)
    print("[改用 B 站]", flush=True)
    return find_bilibili(name)


F0_PY = TTS_ROOT + r"\venv-seedvc\Scripts\python.exe"
TARGET_F0 = 220.0


def estimate_f0(path: str) -> float:
    """估人声基频：取 yin 结果的 10 分位，避开八度上跳（男声常被误判成两倍频）。"""
    code = ("import sys, numpy as np, librosa;"
            "y, sr = librosa.load(sys.argv[1], sr=16000, mono=True);"
            "f = librosa.yin(y, fmin=60, fmax=500, sr=sr);"
            "f = f[np.isfinite(f)];"
            "print(float(np.percentile(f, 10)) if f.size else 0.0)")
    r = subprocess.run([F0_PY, "-c", code, path], capture_output=True, text=True,
                       errors="replace", timeout=180)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def median_f0(path: str) -> float:
    return estimate_f0(path)


def auto_pitch(vocals: str) -> int:
    import math
    if pitch_override is not None:
        return int(pitch_override)
    f0 = estimate_f0(vocals)
    if f0 <= 0:
        print("[音高] 检测失败，按 0 处理", flush=True)
        return 0
    if f0 >= 150:
        semi = 0  # 女声（10 分位 >=150Hz）
    else:
        semi = int(round(12 * math.log2(TARGET_F0 / f0)))
        semi = max(0, min(12, semi))
    print(f"[音高] 基频(10分位)={f0:.0f}Hz -> 偏移 {semi:+d} 半音", flush=True)
    return semi


pitch_override = None


def resolve_song_info(name: str) -> dict:
    """找歌并返回 {path, source, title, artist, quality}。"""
    path = resolve_song(name)
    meta = dict(LAST_META)
    meta["path"] = path
    meta.setdefault("title", os.path.splitext(os.path.basename(path))[0])
    meta.setdefault("source", "未知")
    return meta


def pick_segment(vocals: str, dur: float) -> float:
    """按人声能量挑一个 dur 秒的高潮片段，返回相对起点。"""
    total = duration(vocals) or 0.0
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", vocals, "-af",
                        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                        "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    vals = re.findall(r"RMS_level=(-?[\d.]+|-inf)", (r.stdout or "") + (r.stderr or ""))
    nums = [float(v) if v != "-inf" else -120.0 for v in vals]
    if not nums or total <= 0:
        return 0.0
    win = 8
    grid = [sum(nums[i:i + win]) / len(nums[i:i + win]) for i in range(0, len(nums), win)]
    if not grid:
        return 0.0
    sec_per_cell = total / len(grid)
    need = max(1, int(dur / sec_per_cell))
    best_i, best_e = 0, -1e9
    for i in range(0, max(1, len(grid) - need + 1)):
        e = sum(grid[i:i + need])
        if e > best_e:
            best_e, best_i = e, i
    return max(0.0, best_i * sec_per_cell - 0.5)


def pick_song_window(path: str, dur: float) -> float:
    """在整首歌上按响度找高潮段，返回起点秒数。"""
    total = duration(path) or 0.0
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path, "-af",
                        "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                        "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    vals = re.findall(r"RMS_level=(-?[\d.]+|-inf)", (r.stdout or "") + (r.stderr or ""))
    nums = [float(v) if v != "-inf" else -120.0 for v in vals]
    if not nums or total <= 0:
        return 0.0
    win = 10
    grid = [sum(nums[i:i + win]) / len(nums[i:i + win]) for i in range(0, len(nums), win)]
    if not grid:
        return 0.0
    sec_per_cell = total / len(grid)          # ← 关键修正：按实际帧数换算
    need = max(1, int(dur / sec_per_cell))
    best_i, best_e = 0, -1e9
    for i in range(0, max(1, len(grid) - need + 1)):
        e = sum(grid[i:i + need])
        if e > best_e:
            best_e, best_i = e, i
    return max(0.0, best_i * sec_per_cell - 2.0)


def duration(path: str) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def rvc_params_for(pitch: int, index_rate: float):
    """按变调幅度微调 RVC 参数：大跨度（男→女）时多保护辅音、稍微加强索引。"""
    big = abs(pitch) >= 8
    if big:
        # 跨性别：索引加强压制原性别残留、protect 降低让模型音色进来、rms 降到 0.5 去掉原声胸腔感
        return 0.25, min(0.6, max(index_rate, 0.5)), 0.5
    return 0.33, index_rate, 0.95


def run_cover(song: str, model: str = "m30", pitch=None, dur: float = 45.0,
              start: float = None, inst_vol: float = 0.45, vocal_vol: float = 1.35,
              progress=None, vocals_only: bool = False, index_rate: float = 0.3,
              full: bool = False, src_override: str = "",
              pitch_force: int | None = None) -> str:
    if full:
        return run_full_cover(song, model, pitch, vocals_only, index_rate,
                              inst_vol, vocal_vol, progress, src_override)
    os.makedirs(OUT, exist_ok=True)
    src_path = src_override or resolve_song(song)
    sid = uuid.uuid4().hex[:8]
    work = os.path.join(SING, f"cover_{sid}")
    os.makedirs(work, exist_ok=True)
    if progress:
        progress("解析音频")

    full = duration(src_path)
    global pitch_override
    pitch_override = pitch_force
    explicit_pitch = pitch

    # 先分离整首（demucs 需要完整人声来挑高潮），再截片段成本高；
    # 折中：截一个 90 秒的大窗口做分离，窗口起点未知时先粗分离前 90 秒
    if start is not None:
        seg_start = max(0.0, start - 5.0)
        seg_len = min(dur + 15.0, max(1.0, full - seg_start))
    else:
        seg_start = pick_song_window(src_path, dur)
        # 夹紧：高潮起点不能太靠后，否则切出来的片段过短会让 demucs 崩
        seg_start = max(0.0, min(seg_start, max(0.0, full - dur - 5.0)))
        seg_len = min(dur + 10.0, max(1.0, full - seg_start))
        if seg_len < 5.0:
            raise RuntimeError(f"歌曲太短或选段失败（总长 {full:.1f}s，起点 {seg_start:.1f}s）")
        print(f"[窗口] 起点 {seg_start:.1f}s 长度 {seg_len:.1f}s（原曲 {full:.1f}s）", flush=True)
    clip = os.path.join(work, "clip.wav")
    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", seg_start, "-t", seg_len,
          "-i", src_path, "-ar", "44100", "-ac", "2", clip], "截取片段" if progress is None else "截取片段")

    clip_dur = duration(clip)
    if clip_dur < 3.0:
        raise RuntimeError(f"截出的片段过短（{clip_dur:.2f}s），检查歌曲长度或起点")
    cache_key = f"片段_{int(seg_start)}s_{int(seg_len)}s_{DEMUCS_MODEL}"
    cached = cached_stems(song, cache_key)
    stem = os.path.join(work, DEMUCS_MODEL, "clip")
    vocals = os.path.join(stem, "vocals.wav")
    inst = os.path.join(stem, "no_vocals.wav")
    if cached:
        if progress:
            progress("复用已分离的人声/伴奏")
        os.makedirs(stem, exist_ok=True)
        shutil.copy2(cached[0], vocals)
        shutil.copy2(cached[1], inst)
        print("[复用分离] 命中缓存，跳过 demucs", flush=True)
    else:
        if progress:
            progress("分离人声/伴奏")
        _run([DEMUCS, "-n", DEMUCS_MODEL, "--two-stems=vocals", "--shifts", "1",
              "--overlap", "0.5", "-o", work, clip], "demucs")
        if not (os.path.isfile(vocals) and os.path.isfile(inst)):
            raise RuntimeError("demucs 没产出文件")
        store_stems(song, cache_key, vocals, inst)

    clip_len = duration(clip)
    if start is None:
        off = pick_segment(vocals, dur)
    else:
        off = max(0.0, start - seg_start)
    if off + dur > clip_len:
        off = max(0.0, clip_len - dur - 0.5)
    print(f"[选段] 起点 {off:.1f}s，长度 {dur:.0f}s（片段总长 {clip_len:.1f}s）", flush=True)

    # 男女声自动变调：按原唱中位基频把音域搬到目标女声区间
    pitch = explicit_pitch if explicit_pitch is not None else auto_pitch(vocals)
    if progress:
        progress(f"换音色（{model}）")
    conv = os.path.join(work, "conv.wav")
    pth = os.path.join(MODELS, model + ".pth")
    idx = os.path.join(MODELS, model + ".index")
    protect, idx_rate, rms_mix = rvc_params_for(pitch, index_rate)
    print(f"[RVC参数] pitch={pitch:+d} protect={protect} index={idx_rate} rms={rms_mix}", flush=True)
    cmd = [RVC_PY, "-m", "infer.cli", "--model", pth, "--input", vocals, "--output", conv,
           "--pitch", pitch, "--f0-method", "rmvpe", "--index-rate", idx_rate,
           "--protect", protect, "--rms-mix-rate", rms_mix, "--overwrite"]
    if idx_rate > 0 and os.path.isfile(idx):
        cmd += ["--index", idx]
    _run(cmd, "RVC", timeout=3600, cwd=RVC_ROOT)

    if progress:
        progress("混音" if not vocals_only else "整理人声")
    vcut = os.path.join(work, "v_cut.wav")
    icut = os.path.join(work, "i_cut.wav")
    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", off, "-t", dur, "-i", conv,
          "-af", "highshelf=f=8000:g=-2,afftdn=nf=-32,loudnorm=I=-16:TP=-1.5",
          "-ar", "44100", "-ac", "1", vcut], "人声后处理")

    outdir = song_dir(song)
    tag = "纯人声" if vocals_only else "带伴奏"
    out = os.path.join(outdir, f"片段_{tag}_{model}_{stamp()}_{sid}.wav")
    if vocals_only:
        # 用户要求不要伴奏：只输出换过音色的人声
        _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", vcut,
              "-af", "loudnorm=I=-14:TP=-1.0", "-ar", "44100", "-ac", "1", out], "纯人声输出")
        shutil.rmtree(work, ignore_errors=True)
        print(f"[完成-无人声伴奏] {out}", flush=True)
        return out

    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", off, "-t", dur, "-i", inst,
          "-ar", "44100", "-ac", "2", icut], "伴奏截取")
    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", vcut, "-i", icut,
          "-filter_complex",
          f"[0:a]volume={vocal_vol}[v];[1:a]volume={inst_vol}[i];"
          f"[v][i]amix=inputs=2:duration=longest,loudnorm=I=-13:TP=-1.0[o]",
          "-map", "[o]", "-ar", "44100", "-ac", "2", out], "混音输出")
    if not os.path.isfile(out) or os.path.getsize(out) < 100_000:
        raise RuntimeError(f"混音输出异常（{os.path.getsize(out) if os.path.isfile(out) else 0} 字节）")
    shutil.rmtree(work, ignore_errors=True)
    print(f"[完成] {out}", flush=True)
    return out


DEMUCS_MODEL_FULL = "htdemucs_ft"   # 整首也用 ft（质量优先，速度慢）


def run_full_cover(song: str, model: str = "m30", pitch=None, vocals_only: bool = False,
                   index_rate: float = 0.3, inst_vol: float = 0.45,
                   vocal_vol: float = 1.35, progress=None, src_override: str = "") -> str:
    """整首歌翻唱：不做截断，整首分离 → 换音色 → 混音（或纯人声）。"""
    os.makedirs(OUT, exist_ok=True)
    src_path = src_override or resolve_song(song)
    sid = uuid.uuid4().hex[:8]
    work = os.path.join(SING, f"full_{sid}")
    os.makedirs(work, exist_ok=True)
    if progress:
        progress("整首：转码")
    src_wav = os.path.join(work, "src.wav")
    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src_path,
          "-ar", "44100", "-ac", "2", src_wav], "转码")
    if progress:
        progress("整首：分离人声/伴奏（约 5-10 分钟）")
    cache_key = f"整首_{DEMUCS_MODEL_FULL}"
    cached = cached_stems(song, cache_key)
    stem = os.path.join(work, DEMUCS_MODEL_FULL, "src")
    vocals = os.path.join(stem, "vocals.wav")
    inst = os.path.join(stem, "no_vocals.wav")
    if cached:
        if progress:
            progress("复用已分离的人声/伴奏")
        os.makedirs(stem, exist_ok=True)
        shutil.copy2(cached[0], vocals)
        shutil.copy2(cached[1], inst)
        print("[复用分离] 整首命中缓存，跳过 demucs", flush=True)
    else:
        _run([DEMUCS, "-n", DEMUCS_MODEL_FULL, "--two-stems=vocals", "-o", work, src_wav],
             "demucs-full", timeout=7200)
        if not (os.path.isfile(vocals) and os.path.isfile(inst)):
            raise RuntimeError("demucs 没产出文件")
        store_stems(song, cache_key, vocals, inst)

    if pitch is None:
        pitch = auto_pitch(vocals)
    if progress:
        progress(f"整首：换音色（约 8-15 分钟）")
    conv = os.path.join(work, "conv.wav")
    pth = os.path.join(MODELS, model + ".pth")
    idx = os.path.join(MODELS, model + ".index")
    protect, idx_rate, rms_mix = rvc_params_for(pitch, index_rate)
    print(f"[RVC参数] pitch={pitch:+d} protect={protect} index={idx_rate} rms={rms_mix}", flush=True)
    cmd = [RVC_PY, "-m", "infer.cli", "--model", pth, "--input", vocals, "--output", conv,
           "--pitch", pitch, "--f0-method", "rmvpe", "--index-rate", idx_rate,
           "--protect", protect, "--rms-mix-rate", rms_mix, "--overwrite"]
    if idx_rate > 0 and os.path.isfile(idx):
        cmd += ["--index", idx]
    _run(cmd, "RVC-full", timeout=7200, cwd=RVC_ROOT)

    if progress:
        progress("整首：混音")
    vpost = os.path.join(work, "v_post.wav")
    _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", conv,
          "-af", "highshelf=f=8000:g=-2,afftdn=nf=-32,loudnorm=I=-16:TP=-1.5",
          "-ar", "44100", "-ac", "1", vpost], "人声后处理")
    outdir = song_dir(song)
    tag = "纯人声" if vocals_only else "带伴奏"
    out = os.path.join(outdir, f"整首_{tag}_{model}_{stamp()}_{sid}.wav")
    if vocals_only:
        _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", vpost,
              "-af", "loudnorm=I=-14:TP=-1.0", "-ar", "44100", "-ac", "1", out], "整首纯人声")
    else:
        _run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", vpost, "-i", inst,
              "-filter_complex",
              f"[0:a]volume={vocal_vol}[v];[1:a]volume={inst_vol}[i];"
              f"[v][i]amix=inputs=2:duration=longest,loudnorm=I=-13:TP=-1.0[o]",
              "-map", "[o]", "-ar", "44100", "-ac", "2", out], "整首混音")
    if not os.path.isfile(out) or os.path.getsize(out) < 200_000:
        raise RuntimeError("整首输出异常")
    shutil.rmtree(work, ignore_errors=True)
    print(f"[整首完成] {out}", flush=True)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("--model", default="m30")
    ap.add_argument("--pitch", type=int, default=None)
    ap.add_argument("--dur", type=float, default=45)
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--vocals-only", action="store_true", help="不要伴奏，只输出换过音色的人声")
    a = ap.parse_args()
    print(run_cover(a.song, a.model, a.pitch, a.dur, a.start, vocals_only=a.vocals_only))


if __name__ == "__main__":
    main()