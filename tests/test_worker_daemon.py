from threading import Event

from cloudfileflow.worker import WorkerResult
from cloudfileflow.worker_daemon import run_loop


class StopAfterOneRunner:
    def __init__(self, stop: Event) -> None:
        self.stop = stop
        self.calls = 0

    def run_once(self) -> WorkerResult | None:
        self.calls += 1
        self.stop.set()
        return None


class RecoveringRunner:
    def __init__(self, stop: Event) -> None:
        self.stop = stop
        self.calls = 0

    def run_once(self) -> WorkerResult | None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic loop failure")
        self.stop.set()
        return None


def test_loop_stops_without_polling_after_signal() -> None:
    stop = Event()
    runner = StopAfterOneRunner(stop)

    run_loop(runner, stop, 0.1)

    assert runner.calls == 1


def test_loop_recovers_from_unexpected_iteration_failure() -> None:
    stop = Event()
    runner = RecoveringRunner(stop)

    run_loop(runner, stop, 0.001)

    assert runner.calls == 2
