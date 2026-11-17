# Status

[简体中文](../desktop.md#状态页)

Open **Status** in the AheadSubs sidebar. It refreshes immediately, every three seconds while visible, and on demand.

- **Service and sources** shows readiness, active playback connections, and in-progress text requests by PotPlayer, mpv, command line, MCP, and other HTTP clients.
- **Local models and resources** lists the loaded speech recognition, translation and voice activity detection models, their devices, and available CPU, RAM, GPU and dedicated GPU memory readings for the service and its subprocesses.
- **Subtitle performance** shows RTF and end-to-end subtitle latency (P50, P95 and P99), with sample counts. An RTF below 1 means a new chunk took less time to process than the length of its audio. Latency runs from a playback update that needs new subtitles until a playback response first has usable subtitles.
- **Cloud usage** shows calls, failures, known usage and the estimated USD cost by provider, model and operation. Choose one of the current and seven preceding UTC weeks, starting Monday. Existing totals remain available when the service stops. The estimate covers this installation. Missing usage or rates and subscription calls are identified in the table.

Performance uses at most 1,024 samples per metric from the last 15 minutes, in memory. After a restart the page waits for new samples. Cloud totals are kept locally and old weeks expire when the service starts or records usage. Status metrics store no filenames, subtitle text, accounts, credentials, session identifiers or request bodies. See the [HTTP service](../server.md) for definitions and interfaces.

The desktop polls while the page and window are visible. If the service is down, the desktop bridge reads existing weekly totals from the default cache without starting the service. An externally managed local endpoint reports its model load state as unknown. GPU and dedicated memory readings depend on the Windows driver and available counters. CPU is shown as a percentage of all logical CPUs.

Latency samples track waits for fresh subtitles within the same playback chunk. An already available cue, a seek or file change that abandons the wait, and time between the response and display in the player are outside this measurement. RTF divides the time spent on a successful new chunk by its actual audio duration, clipped to its owned window.

Cloud estimates use observed tokens or audio length and public USD list prices for supported models. Calls are counted at the model request boundary, with automatic transport retries grouped into the same call. Actual billing can differ because of retries, free quotas, taxes, rounding or pricing plans. ChatGPT and MiniMax M Plan subscription usage is counted without a per-call dollar estimate. Compatible endpoints with unknown rates show counts and known usage.
