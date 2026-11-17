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
| FFmpeg command-line bundle | Build script selects LGPL shared binaries and retains top-level notices and upstream source/build links | Verify the actual build configuration and supply corresponding source/build material and notices under the applicable LGPL version. A binary checksum or upstream link alone is not a complete compliance proof. [FFmpeg guidance](https://ffmpeg.org/legal.html) |
| PyAV 18.1.0 Windows wheel | PyAV is BSD-3-Clause, but its bundled `avcodec` and `avutil` DLL strings state LGPL version 3 or later | Audit these separately from the command-line FFmpeg bundle. Their source/build and notice obligations remain. [Exact wheel metadata](https://pypi.org/pypi/av/18.1.0/json) |
| CTranslate2 4.9.0 Windows wheel | Metadata reports MIT, but the inspected wheel contains no filename with LICENSE/COPYING/NOTICE | Add the exact upstream license and relevant native-component notices to redistribution materials. pip preserving metadata does not fill missing files. [Upstream](https://github.com/OpenNMT/CTranslate2/blob/v4.9.0/LICENSE) |
| NVIDIA cuBLAS 12.8.4.1 / cuDNN 9.10.2.21 | Proprietary runtime terms, not open-source licenses | Redistribute only permitted files with applicable notices and consistent downstream terms. Do not claim the CUDA package is wholly MIT or wholly open source. [CUDA 12.8 terms](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html), [cuDNN 9.10.2 terms](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/eula.html) |

Wheel inspection: `av-18.1.0-cp311-abi3-win_amd64.whl`, SHA256 `ea1480b7a8d5405cb5f382b344731bf125fd2c1c6fae3964f6c48595628387ff`; `pystray-0.19.5-py2.py3-none-any.whl`; `ctranslate2-4.9.0-cp311-cp311-win_amd64.whl`. DLL license strings were read without executing them. This did not enumerate every codec or validate corresponding source completeness.

Python carries PSF licensing plus third-party notices; the packager copies Python's license. Self-contained [.NET](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT), Windows runtime components and their notices must also be checked in the final archive. [Inno Setup 7.1.1](https://github.com/jrsoftware/issrc/blob/is-7_1_1/license.txt) permits commercial use subject to its notice/origin conditions; its website also requests commercial purchases. Preserve its existing notices. Downloaded [CrispASR v0.8.54](https://github.com/CrispStrobe/CrispASR/blob/v0.8.54/LICENSE) is MIT at project level; retain the archive's third-party notices too. Player integration does not grant rights to redistribute PotPlayer or mpv; neither player is included by this packager.

## Model weights and cloud services

- **NLLB is not a general commercial-use option.** [Meta's original model](https://huggingface.co/facebook/nllb-200-distilled-600M) is CC-BY-NC-4.0. The configured [INT8 conversion](https://huggingface.co/Adom4600/nllb-200-distilled-600M-ct2-int8) currently has no model card; conversion does not establish permission to remove the original restriction. Treat it as noncommercial pending a valid alternative grant. Commercial deployments should choose an appropriately licensed translation model or service.
- [Whisper Small conversion](https://huggingface.co/Systran/faster-whisper-small) reports MIT; [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), its [GGUF conversion](https://huggingface.co/cstr/qwen3-asr-1.7b-GGUF) and [FSMN-VAD](https://huggingface.co/funasr/fsmn-vad-onnx) report Apache-2.0. Verify the exact downloaded model/aligner revision and retain attribution; a runtime's license does not license its weights.
- Models are downloaded separately, not bundled by the current Windows build. This separation does not waive model usage restrictions. Cloud service terms, account authorization and media rights remain separate from the source license.

## Remaining release work

Before declaring binary redistribution compliance complete: collect exact-version notices (including missing wheel and native runtime notices), provide corresponding LGPL source/build materials and replacement instructions, verify NVIDIA redistributables/terms in the actual CUDA package, and retain model provenance/licenses in download flows. The NLLB downloader currently selects model/tokenizer files without license files; its conversion repository also lacks a model card. These are documented gaps, not fixed by this audit. Audit both package variants and downloaded runtimes before making a blanket commercial-use claim. Dependency/model changes must update this inventory and both language pages in their PR.
