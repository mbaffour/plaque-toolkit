"""Background workers so the UI thread never blocks on a 12-24 MP detection/batch run."""
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)


def exit_message(exc):
    """The text a SystemExit carries. The engines stop with ``raise SystemExit("reason")``
    (they are command-line tools first), so the reason is in ``code``; a bare exit status
    gets a sentence instead of an empty dialog."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    if code in (None, 0):
        return "The engine stopped before finishing and gave no reason."
    return "The engine stopped before finishing (exit status %s)." % (code,)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        # CT-R1 F2: the engines reject bad input with SystemExit, which is a BaseException,
        # not an Exception. It used to escape this method on the pool thread: the app then
        # either crashed (segfault) or sat for ever with Run disabled and no message. Every
        # way the job can end now reaches the GUI as `finished` or `error`; only
        # KeyboardInterrupt (Ctrl+C on a console launch) is left alone.
        try:
            result = self.fn(*self.args, **self.kwargs)
        except KeyboardInterrupt:
            raise
        except SystemExit as e:
            self._emit_error(exit_message(e))
            return
        except BaseException as e:               # noqa: BLE001 -- must never kill the app
            self._emit_error(f"{e}\n\n{traceback.format_exc()}")
            return
        try:
            self.signals.finished.emit(result)
        except RuntimeError:                     # the window was closed while we worked
            pass

    def _emit_error(self, text):
        try:
            self.signals.error.emit(text)
        except RuntimeError:                     # the window was closed while we worked
            pass
