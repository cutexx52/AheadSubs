# 推理与翻译后端

## 可选组合

| 阶段 | 选择 | 条件 |
| --- | --- | --- |
| 本地语音识别 | Qwen3-ASR 0.6B / 1.7B | Windows x64 CrispASR Vulkan 运行时，下载 Q4_K 权重和共享对齐模型。 |
| 本地语音识别 | faster-whisper Small | CTranslate2，可用 CPU 或受支持的 NVIDIA CUDA 环境。 |
| 本地文本翻译 | NLLB 600M INT8 | CTranslate2，可用 CPU 或 CUDA。默认 checkpoint 的基础权重采用 CC BY-NC 4.0。 |
| 云端文本翻译 | Qwen-MT Flash / Lite / Plus | 阿里云百炼 Base URL 与 API Key。仅向该 provider 发送待翻译的字幕文本。 |
| 云端文本翻译 | OpenAI 文本模型 | OpenAI API Key。仅向该 provider 发送待翻译的字幕文本。 |
| 云端语音识别 | 百炼 Qwen-Audio 3.1 / 3.0 ASR Flash | 与 Qwen-MT 共用百炼 Key 和区域。原生接口接收短 WAV，返回句级时间戳。 |
| 云端语音识别或直译 | OpenAI 音频 API | OpenAI API Key。识别或直译请求会发送音频片段，直译目标语言为英语。 |
| 自定义接口 | OpenAI 兼容 ASR / 文本接口 | ASR 需要返回带分段时间戳的 `verbose_json`。文本接口需支持 JSON 模式。 |

凭据通过环境变量或安装目录之外的本地文件提供。OpenAI 使用 `OPENAI_API_KEY`，Qwen-MT 使用 `DASHSCOPE_API_KEY`，兼容端点可分别使用 `RELAY_ASR_API_KEY` 和 `RELAY_LLM_API_KEY`。先在界面安装所需的模型。命令行示例。

```cmd
python -m subtitle_relay serve --asr local --whisper-model small --mt local --device cpu
python -m subtitle_relay serve --asr qwen --qwen-size 1.7b --mt local --device cuda
python -m subtitle_relay serve --asr qwen --qwen-size 0.6b --mt qwen-mt --qwen-mt-model qwen-mt-flash --qwen-mt-url https://dashscope.aliyuncs.com/compatible-mode/v1
python -m subtitle_relay serve --asr dashscope --dashscope-asr-model qwen-audio-3.1-asr-flash --mt qwen-mt --default-source ja
```

Qwen3-ASR 由服务管理一个共享的本地进程。CLI 的 `--device` 控制 CTranslate2 使用 CPU 或 CUDA。Qwen3-ASR 使用其自身的 Vulkan 运行时。[CrispASR](https://github.com/CrispStrobe/CrispASR) · [NLLB 模型卡](https://huggingface.co/facebook/nllb-200-distilled-600M) · [Qwen-MT 接口](https://www.alibabacloud.com/help/en/model-studio/qwen-mt-api)

百炼 ASR 原生接口可能不返回语种代码。与需要明确输入语言的 NLLB 搭配时，建议在首页选定源语言。[百炼短音频转录接口](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-http-api)

## 每小时估价

界面只显示区间。每小时指一小时视频。按 2026 年 11 月 17 日牌价，识别按实际发送 30–60 分钟音频作示例。Qwen-Audio 3.1 的公开日语短样本用量约为每秒 13.1 个输入 token 与 2 个输出 token。Qwen-MT 按每小时 300–900 条字幕、每条 47 输入与 12 输出 token 估算。GPT-4.1 mini 使用相同条数，每条约 120–400 输入和 12–20 输出 token，以覆盖指令及部分前文。美元按当日中间价 1 美元约 6.7132 元换算。百炼按配置中的北京或新加坡端点选价，未知区域与自定义模型留空。免费额度、重试、重处理、上下文及对白密度都可能改变实际账单。

全本地组合没有 API 用量费用。[百炼牌价](https://help.aliyun.com/zh/model-studio/model-pricing) · [OpenAI Whisper](https://developers.openai.com/api/docs/models/whisper-1) · [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) · [人民币汇率中间价](https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do)

## VAD 与时间轴

VAD 使用 CPU。默认 Silero，可选阿里开源 FunASR FSMN-VAD。第一次使用 FSMN 会下载固定版本的 ONNX 权重及归一化数据。源码环境可安装 `.[fsmn-vad]`。[FunASR FSMN-VAD ONNX](https://huggingface.co/funasr/fsmn-vad-onnx)

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `--chunk` | 8 秒 | 调度和持久化的分块长度 |
| `--before`、`--after` | 各 2 秒 | 在最长语音段之外，向两侧额外搜索停顿的时长 |
| `--backfill` | 4 秒 | 跳转后至少向前回补的时长 |
| `--min-silence-ms`、`--pad-ms` | 450 ms、80 ms | 优先采用的停顿长度与每侧留白 |
| `--min-speech` | 3 秒 | 合并短语音片段时的长度目标 |
| `--max-speech` | 12 秒 | 单次送入识别的最大语音段 |
| `--vad-model` | `silero` | 可选 `fsmn` |
| `--vad-threshold` | Silero 0.50 / FSMN 0.80 | 对应模型的语音概率阈值 |

改动前先固定同一音轨和时间段，比较漏检、误报和对白边界。阈值依模型而定。译文使用对白片段起止时间，处理静音也会记录已覆盖的区间。参见[识别与字幕调校](tuning.md)。

## 后端接口

接口定义在 `subtitle_relay/inference/providers.py`。音频输入是 16 kHz 单声道 WAV。

| 接口 | 契约 |
| --- | --- |
| `Recognizer.recognize(wav, source)` | 返回源语言代码和 `list[Cue]`。每条 `Cue` 的时间以传入音频起点为零。 |
| `Translator.translate(lines, source, target)` | 返回同样数量、同样顺序的译文。每个结果与对应原文共用时间戳。 |
| `SpeechTranslator.speech_translate(wav, source, target)` | 直接返回翻译后的 `list[Cue]`，起止时间仍相对输入音频。 |

实现新后端时，保留原文与时间的配对关系，返回可处理的错误，并将影响输出的模型或选项纳入服务的缓存身份。不要把密钥加入身份或日志。测试可用实现相同接口的替身，在没有模型和凭据的环境运行。

推理后端共用 `inference.errors.ProviderError`。有结构化错误码的兼容端点通过统一入口归一；自定义后端可抛出包含同一错误分类的 `ProviderError`。明确的拦截码或 `content_filter` 结束原因记为 `content_blocked`。缺少明确证据的空译文、请求错误或网络故障保留各自的失败分类。字幕检查保留原文与原因；拦截记录跳过同一缓存任务的自动重试。
