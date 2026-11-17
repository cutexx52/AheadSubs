# Windows setup presets

[简体中文](../desktop.md)

## Subtitle inspection

Open **Subtitle inspection** to search by file name or path and filter by primary source language. History groups records by their stored path and opens the newest version by default. You can switch to an older version. Moving a file creates a new entry. Older records with only a file name stay separate until a playback with the same cache settings records their path.

Coverage is the share of the selected version's media duration that has been processed, including silence. It is unknown when duration is unavailable. The primary source language comes from recognition results when the provider supplies it. The listed subtitle languages reflect the available target subtitles across versions of the file.

**Regenerate** creates a fresh version using the selected version's audio track and languages and the running service's models. The service processes one chunk at a time while playback sessions are idle. Previous versions stay available. You can open or save an SRT for the selected version, including partial results.

## Setup presets

Open **Setup presets** on the translation home page. The control starts collapsed. Once you select a preset, **Download now** fetches the missing models. **Manage models** opens the library with the required downloads marked. When the preset is ready, select **Apply preset**. The audio language, subtitle language, and bilingual setting carry over. Manual model combinations appear as **Custom**.

| Preset | Speech recognition | Translation |
| --- | --- | --- |
| Local · CPU | Whisper Small on CPU | NLLB on CPU |
| Local · Entry GPU | Qwen3-ASR 0.6B on Vulkan | NLLB on CPU |
| Local · High-performance GPU | Qwen3-ASR 1.7B on Vulkan | NLLB on NVIDIA CUDA |
| Recommended · Local speech + cloud translation | Qwen3-ASR 1.7B on Vulkan | Qwen-MT Flash with a Bailian API key |

The GPU presets check for a Vulkan device. The high-performance preset also checks for an NVIDIA CUDA device and its runtime libraries. The recommended preset checks whether the saved Bailian credential is readable and the service URL is supported. Save a missing key in the Bailian configuration and return to the home page to check again. The provider verifies the credential when a request is sent. If a download fails, retry to reuse any models that finished downloading.

**Local models** groups speech recognition, translation, and voice activity detection. Whisper and NLLB have separate CPU/CUDA selectors. Use the main **Save and apply** action to apply device changes. Existing configurations use their previous device setting until a per-model setting is saved. Stop the subtitle service or switch models before uninstalling a model in use. Uninstalling Whisper or NLLB removes its repository from the shared Hugging Face cache. Uninstalling one Qwen3-ASR model keeps the shared aligner and Vulkan runtime. Silero is bundled, and FSMN is prepared when selected in Advanced settings.
