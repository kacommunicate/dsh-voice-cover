# dsh-voice-cover · 说话 & 点歌翻唱工具链

把 **文字变语音**（GPT-SoVITS + RVC 换音色）和 **QQ 点歌翻唱**（找音源 → 分离 → 换音色 → 混音）两套流程整理成可复用脚本 + AstrBot 插件。

> 本仓库**不含任何音色模型（.pth/.index）、参考音频、API Key、QQ 账号或数据库**。
> 你需要自备音频模型并遵守相应授权。

## 组成

```
speech/                          说话链路
  say_svc.py                     文字 → GPT-SoVITS /tts → wav
  send_wav.py                    wav → 响度标准化 → SILK → QQ 语音条
  snowluma_api.py                SnowLuma OneBot HTTP 客户端
shared/
  rvc_api.py                     RVC Gradio 兼容 API（/run/infer_change_voice、/run/infer_convert）
cover/                           翻唱链路
  sing_cover.py                  点歌核心：找音源 → 选段 → demucs 分离 → 变调 → RVC → 混音
  sing_song.py                   命令行版：一首歌 → 翻唱成品
astrbot_plugins/
  astrbot_plugin_voice_rvc/      每条回复自动转语音条
  astrbot_plugin_sing_cover/     点歌 → 先报音源 → 你确认 → 出翻唱
```

## 数据流

### 说话

```
QQ 消息 → AstrBot(LLM) 出文字
  → astrbot_plugin_voice_rvc 拦截
  → GPT-SoVITS /tts（参考音克隆，带语气）
  → rvc_api /run/infer_convert（换音色）
  → pysilk 转 SILK → QQ 语音条（只发语音，不发文字）
```

### 翻唱

```
「我想听XX」/「整首XX」/「不要伴奏」
  → astrbot_plugin_sing_cover 解析
  → 找音源：本地曲库 → 在线音源(320k, 原唱优先) → 备用链
  → 回一条文字确认（来源/歌名/歌手/音质）
  → 你回「是」
  → 响度选高潮窗口（片段 55s / 整首全曲）
  → demucs 分离（有缓存则跳过）
  → 10 分位基频判男女 → 变调（男声 +12，女声 0）
  → RVC 换音色（跨性别：protect .25 / index .50 / rms .50）
  → 混音（人声 1.35 / 伴奏 0.45）或纯人声
  → 45s 语音条 或 整首文件
```

## 环境要求

| 组件 | 用途 | 说明 |
|---|---|---|
| Python 3.10+ | 脚本 | 建议 TTS / RVC 各一个 venv |
| GPT-SoVITS v2 | 说话合成 | 自带 api_v2.py，监听 3210 |
| RVC | 换音色 | infer.cli，需自备 .pth / .index |
| demucs | 人声分离 | pip install demucs，建议 htdemucs_ft |
| ffmpeg | 转码/混音 | 需在 PATH 或配置 FFMPEG_BIN |
| pysilk | SILK 编码 | 发 QQ 语音条用 |
| AstrBot >= 4.29.3 | 机器人 | 两个插件放 data/plugins/ |
| SnowLuma / NapCat | QQ 协议 | 提供 OneBot v11 HTTP API |

## 快速开始

```bash
git clone <this-repo>
cp .env.example .env      # 填自己的路径与凭据
```

### 1. 起 RVC API（两条链路共用）

```bash
python shared/rvc_api.py          # 默认 127.0.0.1:7865
```

### 2. 说话

```bash
python speech/say_svc.py --text "你好呀" --out out.wav
python speech/send_wav.py --to <你的QQ> --file out.wav
```

### 3. 翻唱

```bash
python cover/sing_song.py "song.mp3" --model <模型名> --dur 45
```

或走 AstrBot：把两个插件放到 data/plugins，并在插件配置里填 RVC API 地址。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| TTS_ROOT | F:\TTS | 工作根目录 |
| RVC_ROOT | F:\rvc | RVC 主程序目录 |
| RVC_MODELS_DIR | <RVC_ROOT>/models_ascii_all | 模型目录（**请用纯英文路径**，否则 faiss 可能读不到索引） |
| VOICE_SHARED_DIR | <TTS_ROOT>/rvc-share | 语音临时目录 |
| COVER_OUT_DIR | F:\翻唱 | 翻唱成品目录（按歌名分子目录） |
| SNOWLUMA_API | http://127.0.0.1:3000 | OneBot HTTP 地址 |
| SNOWLUMA_TOKEN | 空 | OneBot access token |
| BOT_QQ / OWNER_QQ | 10001 / 10002 | 机器人 / 主人 QQ |
| RVC_MODEL | m30 | 默认音色模型名（不含 .pth） |
| SOVITS_API | http://127.0.0.1:3210 | GPT-SoVITS 地址 |
| SOVITS_REF | <TTS_ROOT>/ref/ref.wav | 说话参考音 |
| SOVITS_PROMPT_TEXT | 空 | 参考音对应文本 |

## 踩过的坑

1. **中文路径 + faiss**：RVC 索引放在中文目录时 faiss 打不开且不报错，务必用纯英文目录
2. **RVC fp16**：部分显卡（如 GTX 1650）半精度会随机输出静音，改 fp32
3. **GPT-SoVITS 切句**：cut5 会把短句截断，短文本用 cut0
4. **QQ 语音条**：必须用 pysilk 编成 SILK_V3 再以 file:// 路径发送，base64 方式 QQ 播不出来
5. **男女声变调**：中位基频会被谐波骗高，要用 10 分位；否则男声只加 3 个半音，听着还是男声
6. **AstrBot 插件白名单**：plugin_set 必须包含插件，且比对的是 @register 名字而非目录名
7. **系统消息别转语音**：确认卡片/进度提示若也走 TTS+RVC，会把发送流程卡住，需显式跳过

## 免责声明

- 不含任何音色模型、参考音频与密钥；模型需自行训练或取得授权
- 翻唱涉及原曲版权，请仅作个人学习与自用
