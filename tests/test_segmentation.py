import unittest
from struct import pack

from aheadsubs.inference.audio import Segmentation, Segmenter, make_wav
from aheadsubs.inference.segmentation import SAMPLE_RATE, plan_spans


def samples(seconds):
    return round(seconds * SAMPLE_RATE)


def waveform(seconds, amplitude=1200):
    return pack("<h", amplitude) * samples(seconds)


def plan(pcm, speech, padding=0):
    return plan_spans(pcm, [(samples(a), samples(b)) for a, b in speech],
                      minimum=samples(3), maximum=samples(12),
                      preferred_pause=samples(0.45), padding=samples(padding))


class SegmentationPlannerTest(unittest.TestCase):
    def test_preferred_pause_waits_for_minimum_and_keeps_padding_separate(self):
        speech = [(1, 2), (2.6, 4.9), (5.5, 9.8), (10.4, 15)]
        self.assertEqual(plan(waveform(18), speech, padding=0.08), [
            (samples(0.92), samples(4.98)),
            (samples(5.42), samples(9.88)),
            (samples(10.32), samples(15.08)),
        ])

    def test_longest_subthreshold_pause_before_limit_beats_nearer_short_pause(self):
        speech = [(0, 3.5), (3.61, 6), (6.29, 9), (9.09, 15)]
        self.assertEqual(plan(waveform(16), speech), [(0, samples(6)), (samples(6.29), samples(15))])

    def test_padding_divides_a_tiny_gap_without_duplicating_samples(self):
        speech = [(0, 4), (4.09, 15)]
        left, right = plan(waveform(16), speech, padding=0.08)
        self.assertEqual((left[1], right[0]), (samples(4.045), samples(4.045)))

    def test_continuous_speech_uses_contiguous_bounded_fallback(self):
        self.assertEqual(plan(waveform(24.5), [(0, 24.5)], padding=0.08), [
            (0, samples(12)), (samples(12), samples(24)), (samples(24), samples(24.5)),
        ])

    def test_energy_fallback_prefers_quieter_audio_when_detector_stays_active(self):
        pcm = waveform(11.6) + waveform(0.28, amplitude=200) + waveform(4.12)
        left, right = plan(pcm, [(0, 16)])
        self.assertLessEqual(samples(11.6), left[1])
        self.assertLess(left[1], samples(11.9))
        self.assertEqual(left[1], right[0])

    def test_short_isolated_speech_is_not_discarded(self):
        self.assertEqual(plan(waveform(25), [(1, 1.6), (20, 20.6)]), [
            (samples(1), samples(1.6)), (samples(20), samples(20.6)),
        ])
        self.assertEqual(plan(waveform(25), []), [])

    def test_focus_changes_priority_only(self):
        segmenter = Segmenter(Segmentation(max_speech=3, enabled=False))
        audio = make_wav(waveform(8))
        chronological = segmenter.spans(audio)
        prioritized = segmenter.spans(audio, focus=5)
        self.assertEqual([offset for offset, _ in chronological], [0, 3, 6])
        self.assertEqual(prioritized[0], chronological[1])
        self.assertEqual(sorted(prioritized), chronological)
