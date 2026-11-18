"""Share identical ASR requests when overlapping context needs the same audio."""
from collections import OrderedDict
from concurrent.futures import Future
from hashlib import sha256
from threading import Lock


class RecognitionCache:
    def __init__(self, recognizer, limit=128):
        self.recognizer = recognizer
        self.limit = limit
        self.lock = Lock()
        self.results = OrderedDict()

    def clear_completed(self):
        with self.lock:
            for key in tuple(self.results):
                if self.results[key].done():
                    self.results.pop(key)

    def recognize(self, reference, wav, source):
        key = (reference, source, sha256(wav).digest())
        with self.lock:
            existing = self.results.get(key)
            if existing is None:
                future = self.results[key] = Future()
            else:
                self.results.move_to_end(key)
        if existing is not None:
            return existing.result()
        try:
            result = self.recognizer.recognize(wav, source)
        except BaseException as exc:
            future.set_exception(exc)
            with self.lock:
                self.results.pop(key, None)
            raise
        future.set_result(result)
        with self.lock:
            excess = len(self.results) - self.limit
            if excess > 0:
                for previous in list(self.results):
                    if self.results[previous].done():
                        self.results.pop(previous)
                        excess -= 1
                        if not excess:
                            break
        return result
