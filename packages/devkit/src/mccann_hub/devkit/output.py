"""Keep cooperative plugin prints out of CLI and stdio protocol output."""

import io
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from threading import RLock

_OUTPUT_LOCK = RLock()


class BoundedOutput(io.StringIO):
    def write(self, text: str) -> int:
        remaining = max(0, 16384 - self.tell())
        super().write(text[:remaining])
        return len(text)


@contextmanager
def capture_output() -> Iterator[BoundedOutput]:
    # Python stream redirection is process-global; serialize cooperative handlers.
    with _OUTPUT_LOCK:
        output = BoundedOutput()
        with redirect_stdout(output), redirect_stderr(output):
            yield output
