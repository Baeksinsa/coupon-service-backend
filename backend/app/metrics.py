"""인스턴스 로컬 카운터.

백엔드 2대 환경에서는 인스턴스마다 값이 따로 쌓인다.
전체 집계는 CloudWatch/ALB 지표와 DB COUNT 를 기준으로 삼고,
이 카운터는 분산이 실제로 되고 있는지 확인하는 보조 증거로 쓴다.
"""
import threading
import time
from collections import defaultdict


class Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, int] = defaultdict(int)
        self.started_at = time.time()

    def inc(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._values[key] += n

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()
            self.started_at = time.time()


counters = Counters()
