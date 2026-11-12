"""Live ffmpeg progress without buffering diagnostics or blocking the UI."""
from __future__ import annotations

from collections.abc import Callable
import queue
import subprocess
import tempfile
import threading

Progress = Callable[[str, float | None], None]


def run_media(command: list[str], duration: float | None = None,
              progress: Progress | None = None, stage: str = "Processing video") -> subprocess.CompletedProcess:
    if progress is None:
        return subprocess.run(command, capture_output=True, text=True)
    progress(stage, 0.0 if duration else None)
    command = [command[0], '-progress', 'pipe:1', '-nostats', *command[1:]]
    messages = queue.Queue()
    values = {}
    fraction = 0.0 if duration else None
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True,
                              stdin=subprocess.DEVNULL) as process:
            def read_output():
                try:
                    for line in process.stdout:
                        messages.put(line.strip())
                finally:
                    messages.put(None)
            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            while True:
                try:
                    line = messages.get(timeout=1)
                except queue.Empty:
                    # A heartbeat keeps elapsed-time reporting live even when
                    # ffmpeg is opening a large file or finalizing its output.
                    progress(stage, fraction)
                    continue
                if line is None:
                    break
                key, _, value = line.partition('=')
                values[key] = value
                if key == 'progress':
                    if duration:
                        try:
                            seconds = int(values.get('out_time_us', '0')) / 1_000_000
                            fraction = max(fraction or 0.0, min(.999, seconds / duration))
                        except ValueError:
                            pass
                    progress(stage, fraction)
            code = process.wait()
            reader.join()
            process.stdout.close()
        errors.seek(0, 2)
        size = errors.tell()
        errors.seek(max(0, size - 8000))
        diagnostics = errors.read().decode('utf-8', errors='replace')
    if code == 0:
        progress(stage, 1.0)
    # The frame counter is used for exact duration after encoding.
    output = f"frame={values.get('frame', '0')}\n"
    return subprocess.CompletedProcess(command, code, output, diagnostics)
