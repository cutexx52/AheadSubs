# 许可证与再分发

[English](licenses.md) | [简体中文](licenses.zh-CN.md)

审计日期：2026-11-18。范围：仓库依赖声明、Windows 打包锁定清单、CUDA 附加包、构建与运行时代码，以及选定的实际 wheel。这是工程审计清单，不是对所有二进制的合规认证或法律意见。

## 源码许可

项目自有代码采用 [MIT](../LICENSE)，经版权所有者确认。公开仓库本身不等于授予通用复用权，参见 [GitHub 许可说明](https://choosealicense.com/no-permission/)。项目许可证不能重新许可第三方库、模型权重或专有运行库。在履行各组件义务的前提下，本次检查未发现禁止项目自有源码采用宽松许可证开源的依赖。

## 需要注意的依赖

[版本化清单](dependency-licenses.json)记录了 [Windows 锁定文件](../packaging/windows/requirements.lock)所有条目及两个 CUDA 附加包的 PyPI 元数据。多数声明 MIT、BSD、Apache、PSF 等宽松条款。元数据只是证据，不能代替包内许可证或其内嵌原生库的许可证。

| 组件 | 发现 | 处理要求 |
| --- | --- | --- |
| pystray 0.19.5 | LGPLv3；wheel 包含 `COPYING` 和 `COPYING.LGPL` | 保留声明，提供适用源码，允许替换和修改该库。不能将该组件称为 MIT。[包信息](https://pypi.org/project/pystray/0.19.5/) |
| certifi / tqdm | MPL-2.0；tqdm 另有 MIT | 保留许可证，履行受覆盖文件及其修改的适用源码义务；不会自动把无关应用文件改成相同许可。[certifi](https://github.com/certifi/python-certifi)、[tqdm](https://github.com/tqdm/tqdm/blob/master/LICENCE) |
| FFmpeg 与 winpthreads | Windows 构建以 LGPL v3 或更新版本编译 FFmpeg 共享库，关闭外部编解码库自动探测。MSYS2 的 `libwinpthread` DLL 提供该构建所用的时钟和休眠函数。 | 二进制包含许可证、署名、工具链版本和替换说明。分发时在同一 Release 提供通过校验的 FFmpeg 和 winpthreads 源码及构建脚本。[FFmpeg 指南](https://ffmpeg.org/legal.html) · [MSYS2 软件包](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-libwinpthread?repo=ucrt64) |
| 旧 Windows 发布包中的 PyAV | PyAV 18.1.0 的 `avcodec` 报告 LGPL v3 或更新版本，同时提供 `libx264` 和 `libx265`。FFmpeg 将这两个库的开源版本列为 GPL 依赖。 | 新 Windows 包移除 PyAV，FFmpeg 提取音轨，faster-whisper 直接接收统一格式的 PCM。已公开的旧版仍需单独核对再分发许可。[PyAV 维护者讨论](https://github.com/PyAV-Org/PyAV/issues/2270) · [FFmpeg 许可证](https://github.com/FFmpeg/FFmpeg/blob/8dca1586f4/LICENSE.md) |
| CTranslate2 4.9.0 Windows wheel | 安装包补齐 CTranslate2 的 MIT 声明、oneDNN 3.1.1 声明，并从 DLL 的 SHA-256 匹配的 Intel OpenMP wheel 提取许可和第三方声明。上游构建关闭了 cuDNN，打包时移除重复的 DLL。 | 另行核对 Intel 运行库的再分发条件。CUDA 版保留 NVIDIA 运行时 wheel 及其许可证。[上游许可证](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/LICENSE) · [Windows 构建](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/python/tools/prepare_build_environment_windows.sh) |
| NVIDIA cuBLAS 12.8.4.1 / cuDNN 9.10.2.21 | 专有运行库条款，不是开源许可证 | 仅分发允许的文件，保留声明并满足下游条款。不能宣称整个 CUDA 安装包都是 MIT 或完全开源。[CUDA 12.8 条款](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html)、[cuDNN 9.10.2 条款](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html) |

实际检查的 wheel 包括 `av-18.1.0-cp311-abi3-win_amd64.whl`（SHA256 为 `ea1480b7a8d5405cb5f382b344731bf125fd2c1c6fae3964f6c48595628387ff`）、`pystray-0.19.5-py2.py3-none-any.whl` 和 `ctranslate2-4.9.0-cp311-cp311-win_amd64.whl`。Windows 运行时测试调用了 `avcodec_license()` 和 `avcodec_configuration()`，并以写模式通过 PyAV 的 `Codec` 查询确认上述两个编码器可用。其他编解码器和对应源码的完整性仍待审计。

安装包保留 Python 的 PSF 和第三方声明，也复制确切版本的自包含 [.NET](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT) 运行时包自带的许可证和第三方声明。[Inno Setup 7.1.1](https://github.com/jrsoftware/issrc/blob/is-7_1_1/license.txt)允许商用，但要求保留声明、准确标示来源，官网另有商业购买请求。保留已有声明。下载的 [CrispASR v0.8.54](https://github.com/CrispStrobe/CrispASR/blob/v0.8.54/LICENSE) 项目级许可为 MIT，保留压缩包中的第三方声明。安装包只包含播放器适配脚本。

## 模型权重与云端服务

- **NLLB 不能作为通用商用方案。** [Meta 原始模型](https://huggingface.co/facebook/nllb-200-distilled-600M)为 CC-BY-NC-4.0。当前配置的 [INT8 转换版](https://huggingface.co/Adom4600/nllb-200-distilled-600M-ct2-int8)没有模型卡，转换不能证明原有限制已被解除。在取得其他有效授权前按非商业模型对待；商业部署应选择许可适合的翻译模型或服务。
- [Whisper Small 转换版](https://huggingface.co/Systran/faster-whisper-small)标注 MIT；[Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)、[GGUF 转换版](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF)及 [FSMN-VAD](https://huggingface.co/funasr/fsmn-vad-onnx)标注 Apache-2.0。仍需核对实际下载的模型、对齐器版本并保留署名；运行时许可不等于模型许可。
- 安装 Qwen3-ASR 时会下载固定版本的[多语言 Whisper Tiny 转换版](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.bin)，用于本地语言检测。转换版标注 MIT，[OpenAI 的 Whisper 原始权重](https://github.com/openai/whisper#license)采用 MIT 许可证。Windows 安装程序不分发该模型。
- 语音识别及翻译模型在设置时下载。faster-whisper wheel 内含用于离线分段的小型 [Silero VAD v6 模型](https://github.com/SYSTRAN/faster-whisper/pull/1373)，安装包附有 [Silero 许可证](https://github.com/snakers4/silero-vad/blob/v6.0/LICENSE)。云服务条款、账号授权和媒体权利独立于源码许可证。

## 尚待完成的分发工作

旧 PyAV 发布附件、Intel 运行库条款、NVIDIA 可分发组件及下游条件仍需分别核对。模型下载流程需保留来源及许可证。当前 NLLB 下载器选择模型和 tokenizer 文件，转换仓库缺少模型卡。依赖或模型变更应在同一 PR 更新清单和中英文说明。
