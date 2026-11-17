# Recognition and translation providers

[English](providers.md) | [简体中文](providers.zh-CN.md)

Choose speech recognition and text translation independently. Fully local processing needs model downloads but no API key. A local recognizer with a cloud translator uploads text; cloud recognition uploads audio segments. The [README](../README.md) gives minimal setup routes.

## Available combinations

| Stage | Option | Requirements |
| --- | --- | --- |
| Local recognition | Qwen3-ASR 0.6B / 1.7B | Windows x64 CrispASR Vulkan runtime, Q4_K weights and shared alignment model |
| Local recognition | faster-whisper Small | CTranslate2 on CPU or supported NVIDIA CUDA |
| Local translation | NLLB 600M INT8 | CTranslate2 CPU/CUDA; base weights of the default checkpoint use CC BY-NC 4.0 |
| Cloud text | Qwen-MT Flash / Lite / Plus | Alibaba Cloud regional URL and key; receives subtitle text |
| Cloud text | OpenAI text models | OpenAI API key; receives subtitle text |
| Cloud text | ChatGPT subscription | Official OAuth connection for eligible subscription allowance/credits; models come from the signed-in account |
| Cloud text | MiniMax M3.1 Flash | M Plan or pay-as-you-go key determines billing |
| Cloud recognition | Alibaba Qwen-Audio 3.1 / 3.0 ASR Flash | Shares Qwen-MT key/region; native API receives short WAV and returns sentence timestamps |
| Cloud recognition/direct translation | OpenAI audio API | OpenAI key; uploads audio segments; direct translation targets English |
| Custom | OpenAI-compatible ASR/text APIs | ASR must return timestamped `verbose_json`; text must support JSON mode |

Save credentials in the desktop or supply environment variables / files outside the installation: `OPENAI_API_KEY`, `DASHSCOPE_API_KEY`, `RELAY_ASR_API_KEY`, `RELAY_LLM_API_KEY`. Install local models before using them.

```cmd
python -m subtitle_relay serve --asr local --whisper-model small --mt local --device cpu
python -m subtitle_relay serve --asr qwen --qwen-size 1.7b --mt local --device cuda
python -m subtitle_relay serve --asr qwen --qwen-size 0.6b --mt qwen-mt --qwen-mt-model qwen-mt-flash --qwen-mt-url https://dashscope.aliyuncs.com/compatible-mode/v1
python -m subtitle_relay serve --asr dashscope --dashscope-asr-model qwen-audio-3.1-asr-flash --mt qwen-mt --default-source ja
```

The third command is hybrid; the fourth uses cloud recognition and translation with `DASHSCOPE_API_KEY`. Set the regional endpoint appropriate to your key; do not put keys in commands or Git. Qwen3-ASR runs in a shared service-managed process using its own Vulkan runtime; `--device` sets the CTranslate2 fallback device; `--asr-device` overrides it for local Whisper and `--mt-device` for NLLB. [CrispASR](https://github.com/CrispStrobe/CrispASR) · [NLLB model card](https://huggingface.co/facebook/nllb-200-distilled-600M) · [Qwen-MT API](https://www.alibabacloud.com/help/en/model-studio/qwen-mt-api).

Alibaba ASR may omit language codes. When pairing it with NLLB, which needs an explicit input language, select the source language. [Short-audio API](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-http-api).

## Subscriptions and authorization

**ChatGPT:** Cloud models → ChatGPT subscription · OAuth (云端模型 → ChatGPT 订阅 · OAuth). Choose Continue with ChatGPT (使用 ChatGPT 继续), sign in/authorize in the browser, then choose account/model and Use for translation → Save and apply (用于翻译 → 保存并应用). OpenAI receives subtitle text and enabled text context; speech recognition remains the separately selected model. Manage ChatGPT usage (管理 ChatGPT 用量) opens allowance management; reauthorize when necessary. CLI: `--mt chatgpt --chatgpt-account <account-id> --chatgpt-model <model-id>`, with IDs from the desktop bridge. [Official integration guide](https://developers.openai.com/siwc/token-sharing-open-source).

**MiniMax:** Cloud models → MiniMax · API Key, direct entry or key file; alternatively set `MINIMAX_API_KEY`. CLI: `--mt minimax`, optionally `--minimax-key-file`. General third-party setup documents M Plan keys; its OAuth guide targets OpenClaw. [Third-party configuration](https://platform.minimax.io/docs/m-plan/other-tools.md) · [OpenClaw guide](https://platform.minimax.io/docs/m-plan/openclaw.md).

Other subscriptions are not interchangeable API credentials. Claude subscription authorization is for Anthropic products; Gemini CLI OAuth and Qwen Code login target their respective clients. GitHub Copilot offers third-party SDK login with coding-oriented documentation. [Claude terms](https://code.claude.com/docs/en/legal-and-compliance) · [Gemini FAQ](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/faq.md) · [Qwen authentication](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/auth.md) · [Copilot SDK](https://docs.github.com/en/copilot/how-tos/copilot-sdk/setup/github-oauth).

Alibaba and Zhipu Coding Plan endpoints are for coding use. Alibaba's general API is built in; Zhipu's general interface can use compatible endpoints. Kimi Code offers development-tool keys; Kimi's open platform has separate usage-based APIs. [Alibaba FAQ](https://help.aliyun.com/zh/model-studio/coding-plan-faq) · [Zhipu endpoints](https://zcode.z.ai/cn/docs/configuration) · [Kimi Code](https://www.kimi.com/code/docs/).

## Hourly estimates

The UI shows ranges per hour of video, not quotes. The recorded 2026-11-17 assumptions are: 30–60 minutes of submitted audio; Qwen-Audio 3.1 on a public Japanese sample about 13.1 input and 2 output tokens per second; Qwen-MT 300–900 cues/hour, 47 input and 12 output tokens/cue; GPT-4.1 mini the same cue count, 120–400 input and 12–20 output tokens/cue including instructions/context. USD conversion used about CNY 6.7132. Alibaba estimates follow the configured Beijing/Singapore region; unknown regions/custom models are blank. Free allowances, retries, reprocessing, context and dialogue density change actual bills.

Fully local processing has no API usage charge. Check current provider prices before use: [Alibaba](https://help.aliyun.com/zh/model-studio/model-pricing) · [Whisper](https://developers.openai.com/api/docs/models/whisper-1) · [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) · [Exchange-rate source](https://www.safe.gov.cn/AppStructured/hlw/RMBQuery.do).

## VAD and timeline

VAD runs on CPU. Silero is default; FunASR FSMN-VAD is optional and downloads pinned ONNX weights/normalization data on first use. Source installs use `.[fsmn-vad]`. [FSMN model](https://huggingface.co/funasr/fsmn-vad-onnx).

| Option | Default | Meaning |
| --- | --- | --- |
| `--chunk` | 8 s | Scheduling/persistence chunk |
| `--before`, `--after` | 2 s each | Additional pause search beyond the longest speech segment |
| `--backfill` | 4 s | Minimum seek backfill |
| `--min-silence-ms`, `--pad-ms` | 450 ms, 80 ms | Preferred pause and per-side padding |
| `--min-speech` | 3 s | Short-segment merging target |
| `--max-speech` | 12 s | Maximum recognition segment |
| `--vad-model` | `silero` | Alternative: `fsmn` |
| `--vad-threshold` | Silero 0.50 / FSMN 0.80 | Model-specific speech threshold |

Compare missed speech, false detections and boundaries on the same track/time range. Thresholds are model-specific. Translations retain dialogue timestamps; silence also counts as processed coverage. See [tuning](tuning.md).

<a id="后端接口"></a>

## Provider interfaces

Defined in `subtitle_relay/inference/providers.py`. Input is 16 kHz mono WAV.

| Interface | Contract |
| --- | --- |
| `Recognizer.recognize(wav, source)` | Returns source-language code and `list[Cue]`; times are relative to input audio start. |
| `Translator.translate(lines, source, target)` | Same number/order of translations; each retains its source timestamps. |
| `SpeechTranslator.speech_translate(wav, source, target)` | Translated `list[Cue]` with input-relative times. |

Keep text/time pairing, return actionable errors, and include output-affecting models/options in cache identity, never keys. Test with substitutes implementing these interfaces without models/credentials.

Providers share `inference.errors.ProviderError`. Normalize structured endpoint errors at the boundary. Explicit moderation codes or `content_filter` completion map to `content_blocked`; empty output, request errors and network failures without that evidence retain their own categories. Inspection preserves original text/reason; blocked cache tasks skip automatic retries.
