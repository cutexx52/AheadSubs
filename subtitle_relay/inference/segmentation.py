"""Plan nonoverlapping ASR spans from speech and quiet boundaries."""

from struct import unpack_from


SAMPLE_RATE = 16000


def _energy_cut(pcm, earliest, latest):
    # No VAD gap fits. Search the last 1.5 seconds for a quieter crossing.
    first = max(earliest, latest - SAMPLE_RATE * 3 // 2)
    half_window = SAMPLE_RATE // 100
    last = len(pcm) // 2

    def energy(cut):
        start = max(0, cut - half_window)
        end = min(last, cut + half_window)
        samples = unpack_from(f"<{end - start}h", pcm, 2 * start)
        return sum(value * value for value in samples) / len(samples)

    candidates = range(latest, first - 1, -half_window)
    return min(candidates, key=energy)


def plan_spans(pcm, ranges, *, minimum, maximum, preferred_pause, padding):
    """Return chronological half-open sample ranges, preserving all detected speech."""
    total = len(pcm) // 2
    intervals = []
    for left, right in sorted((max(0, left), min(total, right)) for left, right in ranges):
        if right <= left:
            continue
        if intervals and left <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], right))
        else:
            intervals.append((left, right))
    if not intervals:
        return []

    minimum = min(minimum, maximum)
    result = []
    index = 0
    start = max(0, intervals[0][0] - padding)
    while index < len(intervals):
        limit = min(total, start + maximum)
        fallback = None
        selected = None
        for candidate in range(index, len(intervals)):
            _, speech_end = intervals[candidate]
            if speech_end > limit:
                break
            if candidate + 1 == len(intervals):
                selected = (min(limit, speech_end + padding), candidate + 1, 0)
                break

            next_speech = intervals[candidate + 1][0]
            gap = next_speech - speech_end
            midpoint = speech_end + gap // 2
            end = min(limit, speech_end + padding, midpoint)
            next_start = max(midpoint, next_speech - padding)
            boundary = (end, candidate + 1, next_start)
            long_enough = end - start >= minimum
            if gap >= max(preferred_pause, minimum) or (long_enough and gap >= preferred_pause):
                selected = boundary
                break
            # Prefer the longest real pause after the minimum. Even an earlier
            # pause wins over cutting through speech when there is no better one.
            rank = (long_enough, gap, end)
            if fallback is None or rank > fallback[0]:
                fallback = (rank, boundary)

        if selected is None and fallback is not None:
            selected = fallback[1]
        if selected is None:
            end = _energy_cut(pcm, min(limit, start + minimum), limit)
            selected = (end, index, end)

        end, index, next_start = selected
        result.append((start, end))
        start = next_start
    return result
