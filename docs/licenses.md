# Licenses and redistribution

[English](licenses.md) | [简体中文](licenses.zh-CN.md)

Audit date: 2026-11-18. Scope: repository dependency declarations, the Windows packaging lock, CUDA add-ons, build/runtime code and selected actual wheels. This is an engineering inventory, not certification of every binary or a legal opinion.

## Source licensing

Original project code uses [MIT](../LICENSE), confirmed by the copyright owner. Public visibility alone does not grant general reuse rights; see [GitHub's licensing guidance](https://choosealicense.com/no-permission/). A project license cannot relicense third-party libraries, model weights or proprietary runtimes. No reviewed dependency categorically prevents releasing the project's own source under a permissive license, provided applicable component obligations are met.

## Dependencies that need attention

The [versioned inventory](dependency-licenses.json) records PyPI metadata for every entry in [the Windows lock](../packaging/windows/requirements.lock) and both CUDA additions. Most report MIT, BSD, Apache, PSF or similar permissive terms. Metadata is evidence, not a substitute for packaged license files or the licenses of bundled native libraries.

| Component | Finding | Required handling |
| --- | --- | --- |
| pystray 0.19.5 | LGPLv3; its wheel contains both `COPYING` and `COPYING.LGPL` | Preserve notices, provide applicable source and allow replacement/modification of the library. Do not describe this component as MIT. [Package](https://pypi.org/project/pystray/0.19.5/) |
| certifi / tqdm | MPL-2.0; tqdm also uses MIT | Preserve their licenses; meet applicable source obligations for covered files and modifications. They do not automatically relicense unrelated application files. [certifi](https://github.com/certifi/python-certifi), [tqdm](https://github.com/tqdm/tqdm/blob/master/LICENCE) |
| FFmpeg and winpthreads | Windows builds compile FFmpeg in shared mode under LGPL v3 or later with external codec auto-detection disabled. The MSYS2 `libwinpthread` DLL implements the clock and sleep functions used by this build. | The binary package includes licenses, credits, toolchain versions and replacement instructions. Keep the checksummed FFmpeg and winpthreads source and build recipe in the same release. [FFmpeg guidance](https://ffmpeg.org/legal.html) · [MSYS2 package](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-libwinpthread?repo=ucrt64) |
| PyAV in older Windows releases | PyAV 18.1.0 reported LGPL v3 or later for `avcodec` and exposed the `libx264` and `libx265` encoders, which FFmpeg lists as GPL dependencies under their open-source terms. | The new Windows package removes PyAV. FFmpeg extracts audio and faster-whisper receives normalized PCM directly. Older releases require their own redistribution review. [PyAV maintainer discussion](https://github.com/PyAV-Org/PyAV/issues/2270) · [FFmpeg license](https://github.com/FFmpeg/FFmpeg/blob/8dca1586f4/LICENSE.md) |
| CTranslate2 4.9.0 Windows wheel | Package adds the missing CTranslate2 MIT and oneDNN 3.1.1 notices and takes Intel OpenMP terms and third-party notices from the Intel wheel whose DLL matches by SHA-256. The upstream build disables cuDNN, so packaging removes its redundant copy. | Account separately for the Intel runtime redistribution conditions. The CUDA variant keeps the NVIDIA runtime wheels and their licenses. [Upstream license](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/LICENSE) · [Windows build](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/python/tools/prepare_build_environment_windows.sh) |
| NVIDIA cuBLAS 12.8.4.1 / cuDNN 9.10.2.21 | Proprietary runtime terms, not open-source licenses | Redistribute only permitted files with applicable notices and consistent downstream terms. Do not claim the CUDA package is wholly MIT or wholly open source. [CUDA 12.8 terms](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html), [cuDNN 9.10.2 terms](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html) |

Wheel inspection covered `av-18.1.0-cp311-abi3-win_amd64.whl` (SHA256 `ea1480b7a8d5405cb5f382b344731bf125fd2c1c6fae3964f6c48595628387ff`), `pystray-0.19.5-py2.py3-none-any.whl`, and `ctranslate2-4.9.0-cp311-cp311-win_amd64.whl`. The Windows runtime check queried `avcodec_license()` and `avcodec_configuration()` and opened both named encoders in write mode through PyAV's `Codec` lookup. Other codecs and corresponding-source completeness remain to be audited.

The package preserves Python's PSF and third-party notices and copies the license and supplied third-party notices from each exact self-contained [.NET](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT) runtime pack. [Inno Setup 7.1.1](https://github.com/jrsoftware/issrc/blob/is-7_1_1/license.txt) permits commercial use subject to its notice and origin conditions. Its website also requests commercial purchases. Preserve its existing notices. Downloaded [CrispASR v0.8.54](https://github.com/CrispStrobe/CrispASR/blob/v0.8.54/LICENSE) is MIT at project level. Retain the archive's third-party notices. The installer bundles player adapters only.

## Model weights and cloud services

- **NLLB is not a general commercial-use option.** [Meta's original model](https://huggingface.co/facebook/nllb-200-distilled-600M) is CC-BY-NC-4.0. The configured [INT8 conversion](https://huggingface.co/Adom4600/nllb-200-distilled-600M-ct2-int8) currently has no model card; conversion does not establish permission to remove the original restriction. Treat it as noncommercial pending a valid alternative grant. Commercial deployments should choose an appropriately licensed translation model or service.
- [Whisper Small conversion](https://huggingface.co/Systran/faster-whisper-small) reports MIT; [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), its [GGUF conversion](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF) and [FSMN-VAD](https://huggingface.co/funasr/fsmn-vad-onnx) report Apache-2.0. Verify the exact downloaded model/aligner revision and retain attribution; a runtime's license does not license its weights.
- Qwen3-ASR setup downloads the pinned [multilingual Whisper Tiny conversion](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.bin) for local language detection. The conversion reports MIT and [OpenAI's original Whisper weights](https://github.com/openai/whisper#license) are MIT-licensed. The Windows installers do not redistribute the detector.
- Speech recognition and translation models are downloaded during setup. The faster-whisper wheel includes a small [Silero VAD v6 model](https://github.com/SYSTRAN/faster-whisper/pull/1373) for offline segmentation. The package includes the [Silero license](https://github.com/snakers4/silero-vad/blob/v6.0/LICENSE). Cloud service terms, account authorization and media rights remain separate from the source license.

## Remaining release work

Review the previous PyAV-based assets, Intel runtime terms, NVIDIA redistributables and downstream conditions separately. Model download flows still need to preserve provenance and licenses. The NLLB downloader selects model and tokenizer files, and its conversion repository lacks a model card. Dependency or model changes must update this inventory and both language pages in their PR.
