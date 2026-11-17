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
| FFmpeg 命令行包 | 构建脚本选择 LGPL shared 包，保留顶层声明与上游源码、构建链接 | 核对实际构建配置，按适用 LGPL 版本提供对应源码、构建材料和声明。校验和或上游链接本身不是完整合规证明。[FFmpeg 指南](https://ffmpeg.org/legal.html) |
| PyAV 18.1.0 Windows wheel | BSD-3-Clause 元数据适用于 PyAV 源码。内嵌 `avcodec` 报告 LGPL v3 或更新版本，同时提供 `libx264` 和 `libx265` 编码器。 | 与命令行 FFmpeg 分开核实下游再分发条款和对应源码。FFmpeg 将这两个库的开源版本列为 GPL 依赖。[PyAV 维护者讨论](https://github.com/PyAV-Org/PyAV/issues/2270) · [FFmpeg 许可证](https://github.com/FFmpeg/FFmpeg/blob/8dca1586f4/LICENSE.md) |
| CTranslate2 4.9.0 Windows wheel | 元数据为 MIT，但检查的 wheel 没有文件名包含 LICENSE/COPYING/NOTICE 的文件 | 在分发材料中补齐确切上游版本许可证及相关原生组件声明。pip 保留元数据不能弥补缺失文件。[上游](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/LICENSE) |
| NVIDIA cuBLAS 12.8.4.1 / cuDNN 9.10.2.21 | 专有运行库条款，不是开源许可证 | 仅分发允许的文件，保留声明并满足下游条款。不能宣称整个 CUDA 安装包都是 MIT 或完全开源。[CUDA 12.8 条款](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html)、[cuDNN 9.10.2 条款](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html) |

实际检查的 wheel 包括 `av-18.1.0-cp311-abi3-win_amd64.whl`（SHA256 为 `ea1480b7a8d5405cb5f382b344731bf125fd2c1c6fae3964f6c48595628387ff`）、`pystray-0.19.5-py2.py3-none-any.whl` 和 `ctranslate2-4.9.0-cp311-cp311-win_amd64.whl`。Windows 运行时测试调用了 `avcodec_license()` 和 `avcodec_configuration()`，并以写模式通过 PyAV 的 `Codec` 查询确认上述两个编码器可用。其他编解码器和对应源码的完整性仍待审计。

Python 使用 PSF 及第三方许可，打包器会复制 Python 许可证。独立部署的 [.NET](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT)、Windows 运行库组件及其声明也需在最终包内检查。[Inno Setup 7.1.1](https://github.com/jrsoftware/issrc/blob/is-7_1_1/license.txt)允许商用，但要求保留声明、不得虚假标示来源；官网另有商业购买请求。保留已有声明。下载的 [CrispASR v0.8.54](https://github.com/CrispStrobe/CrispASR/blob/v0.8.54/LICENSE)项目级许可为 MIT，压缩包中的第三方声明也需保留。播放器适配不授予 PotPlayer 或 mpv 的分发权；当前打包器不包含这两个播放器。

## 模型权重与云端服务

- **NLLB 不能作为通用商用方案。** [Meta 原始模型](https://huggingface.co/facebook/nllb-200-distilled-600M)为 CC-BY-NC-4.0。当前配置的 [INT8 转换版](https://huggingface.co/Adom4600/nllb-200-distilled-600M-ct2-int8)没有模型卡，转换不能证明原有限制已被解除。在取得其他有效授权前按非商业模型对待；商业部署应选择许可适合的翻译模型或服务。
- [Whisper Small 转换版](https://huggingface.co/Systran/faster-whisper-small)标注 MIT；[Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)、[GGUF 转换版](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF)及 [FSMN-VAD](https://huggingface.co/funasr/fsmn-vad-onnx)标注 Apache-2.0。仍需核对实际下载的模型、对齐器版本并保留署名；运行时许可不等于模型许可。
- 模型单独下载，当前 Windows 构建不内置权重；分开下载不会免除模型使用限制。云服务条款、账号授权和媒体权利也独立于源码许可证。

## 尚待完成的分发工作

在宣称二进制再分发全面合规前：汇总确切版本声明（含缺失的 wheel 和原生运行库声明），提供对应 LGPL 源码、构建材料与替换方法，核对实际 CUDA 包内 NVIDIA 可分发文件及条款，并在下载流程中保留模型来源和许可证。当前 NLLB 下载器选择模型与 tokenizer 文件，不含许可文件，转换仓库也缺少模型卡。这些是已记录但本次审计未修复的缺口。对两种安装包及后续下载的运行时完成审计前，不应作笼统商用承诺。依赖或模型变更应在同一 PR 更新清单和中英文说明。
