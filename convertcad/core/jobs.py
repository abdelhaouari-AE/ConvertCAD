"""
jobs.py — run conversions in a SEPARATE PROCESS.

Why a process and not a thread?
  * PyMuPDF is not thread-safe: the interface keeps rendering the preview
    while a conversion runs, which would be unsafe in the same process.
  * Cancelling is instant and clean: the process can be terminated.
  * A crash inside a native library on a malformed PDF cannot take the
    interface down with it.
  * The interface stays perfectly fluid (no shared interpreter lock).

The child process imports only convertcad.core (never Qt). Messages come
back through a multiprocessing queue as tuples:
    ("progress", message, fraction)
    ("file", index, ConversionReport)          # batch mode, per file
    ("done", ConversionReport | summary dict)
    ("error", message)

Works with PyInstaller as long as main.py calls multiprocessing.freeze_support().
"""

import multiprocessing as mp
import queue
import time
import traceback
from typing import List, Optional

_CTX = mp.get_context("spawn")        # same behaviour on Windows/macOS/Linux


# ---------------------------------------------------------------------------
# Child-process entry points (module-level so they can be pickled)
# ---------------------------------------------------------------------------
def _child_convert(args: dict, q, cancel_event) -> None:
    try:
        from .pipeline import Options, convert
        opt = Options.from_dict(args["options"])

        def progress(msg, frac):
            q.put(("progress", msg, frac))

        rep = convert(args["pdf"], args["dxf"], opt, progress,
                      should_cancel=cancel_event.is_set)
        q.put(("done", rep))
    except Exception:                                      # pragma: no cover
        q.put(("error", traceback.format_exc()))


def _child_batch(args: dict, q, cancel_event) -> None:
    try:
        from .pipeline import Options, convert_folder
        opt = Options.from_dict(args["options"])

        def progress(msg, frac):
            q.put(("progress", msg, frac))

        def per_file(index, rep):
            q.put(("file", index, rep))

        summary = convert_folder(args["input_dir"], args["output_dir"], opt,
                                 progress=progress,
                                 should_cancel=cancel_event.is_set,
                                 per_file=per_file,
                                 recursive=args.get("recursive", False),
                                 files=args.get("files"))
        summary["reports"] = []            # already streamed one by one
        q.put(("done", summary))
    except Exception:                                      # pragma: no cover
        q.put(("error", traceback.format_exc()))


# ---------------------------------------------------------------------------
# Parent-side runner (no Qt here: the interface polls it with a QTimer)
# ---------------------------------------------------------------------------
class JobRunner:
    """Starts one job at a time and relays its messages."""

    def __init__(self):
        self._proc: Optional[mp.Process] = None
        self._queue = None
        self._cancel = None
        self._cancel_time = 0.0
        self.finished = True
        self.kind = ""

    # ---- start -------------------------------------------------------------
    def _start(self, target, args: dict, kind: str) -> None:
        if self.is_running():
            raise RuntimeError("A job is already running.")
        self._queue = _CTX.Queue()
        self._cancel = _CTX.Event()
        self._proc = _CTX.Process(target=target,
                                  args=(args, self._queue, self._cancel),
                                  daemon=True)
        self.kind = kind
        self.finished = False
        self._cancel_time = 0.0
        self._proc.start()

    def start_convert(self, pdf: str, dxf: str, options: dict) -> None:
        self._start(_child_convert, {"pdf": pdf, "dxf": dxf,
                                     "options": options}, "convert")

    def start_batch(self, input_dir: str, output_dir: str, options: dict,
                    files: Optional[List[str]] = None,
                    recursive: bool = False) -> None:
        self._start(_child_batch, {"input_dir": input_dir,
                                   "output_dir": output_dir,
                                   "options": options, "files": files,
                                   "recursive": recursive}, "batch")

    # ---- control -----------------------------------------------------------
    def is_running(self) -> bool:
        return self._proc is not None and not self.finished

    def cancel(self, grace_s: float = 2.5) -> None:
        """Ask politely; poll() terminates the process after `grace_s`."""
        if self._cancel is not None and not self.finished:
            self._cancel.set()
            self._cancel_time = time.time() + grace_s

    def poll(self, max_items: int = 200) -> list:
        """Non-blocking: return the messages received since the last call.
        Emits a synthetic ("cancelled",) or ("error", ...) if the process
        ended without reporting (terminated or crashed)."""
        out = []
        if self._queue is None:
            return out
        for _ in range(max_items):
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            except Exception:                              # pragma: no cover
                break
            out.append(msg)
            if msg[0] in ("done", "error"):
                self._finish()
                return out
        if self.finished or self._proc is None:
            return out
        if self._cancel_time and time.time() > self._cancel_time \
                and self._proc.is_alive():
            self._proc.terminate()                         # hard stop
            self._proc.join(2)
            out.append(("cancelled",))
            self._finish()
        elif not self._proc.is_alive():
            # the child died; give the queue one last chance to deliver
            time.sleep(0.05)
            try:
                while True:
                    msg = self._queue.get_nowait()
                    out.append(msg)
                    if msg[0] in ("done", "error"):
                        self._finish()
                        return out
            except Exception:
                pass
            code = self._proc.exitcode
            out.append(("cancelled",) if self._cancel_time else
                       ("error", f"The conversion process stopped "
                                 f"unexpectedly (exit code {code})."))
            self._finish()
        return out

    def _finish(self) -> None:
        self.finished = True
        if self._proc is not None:
            self._proc.join(1)

    def shutdown(self) -> None:
        """Called when the application closes."""
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(2)
        self.finished = True
