# Status

[简体中文](../desktop.md#状态页)

Open **Status** in the AheadSubs sidebar. It refreshes immediately, every three seconds while visible, and on demand.

- **Service and sources** shows service readiness and counts active playback connections by PotPlayer, mpv, command line and other HTTP clients.
- **Local models and resources** lists the loaded speech recognition, translation and voice activity detection models, their devices, and available CPU, RAM, GPU and dedicated GPU memory readings for the service and its subprocesses.
- **Subtitle performance** shows RTF and end-to-end subtitle latency (P50, P95 and P99), with sample counts. An RTF below 1 means a new chunk took less time to process than the length of its audio. Latency runs from a playback update that needs new subtitles until a playback response first has usable subtitles.
- **Cloud usage** shows calls, failures, known usage and the estimated USD cost by provider, model and operation. Choose one of the current and seven preceding UTC weeks, starting Monday. Existing totals remain available when the service stops. The estimate covers this installation. Missing usage or rates and subscription calls are identified in the table.

Performance uses at most 1,024 samples per metric from the last 15 minutes, in memory. After a restart the page waits for new samples. Cloud totals are kept locally and old weeks expire when the service starts or records usage. Status metrics store no filenames, subtitle text, accounts, credentials, session identifiers or request bodies. See the [HTTP service](../server.md) for definitions and interfaces.
