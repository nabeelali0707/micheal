"""
MCQ Helper - background screenshot -> Ollama vision model -> answer popup.

Hotkeys
  Ctrl+Shift+X : take a screenshot, send it to the model, show the answer popup
  Ctrl+Shift+/ : show the progress popup
  Ctrl+Shift+' : show the latest answer
  Ctrl+Shift+H : hide every popup
  Ctrl+Shift+Z : legacy hide hotkey
  Ctrl+Shift+Q : quit the program

Run with  pythonw mcq_helper.py  (or start.bat) so no console window appears.
Logs go to mcq_helper.log next to this file.
"""

import base64
import ctypes
import io
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "mcq_helper.log")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("mcq")


def fatal(msg):
    """Log and show a Windows message box (pythonw has no console)."""
    log.error(msg)
    try:
        ctypes.windll.user32.MessageBoxW(None, msg, "MCQ Helper", 0x10)
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)


def _excepthook(exc_type, exc, tb):
    fatal("MCQ Helper crashed:\n\n" + "".join(
        traceback.format_exception(exc_type, exc, tb))[-1500:])


sys.excepthook = _excepthook

try:
    import tkinter as tk
except ImportError:
    fatal("tkinter is missing.\n\nReinstall Python from python.org and keep "
          "'tcl/tk and IDLE' ticked in the installer options.")

try:
    import keyboard
    from PIL import Image, ImageGrab, ImageTk
except ImportError as e:
    fatal(f"Missing Python package: {e.name}\n\nRun setup.bat (or: "
          f"python -m pip install -r requirements.txt) and start again.")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

# ----------------------------------------------------------------- settings
MODEL = "gemma4:e4b"
OLLAMA_URL = "http://127.0.0.1:11434"
HOTKEY_CAPTURE = "ctrl+shift+x"
HOTKEY_PROGRESS = "ctrl+shift+/"
HOTKEY_LATEST = "ctrl+shift+'"
HOTKEY_HIDE = "ctrl+shift+h"
HOTKEY_HIDE_LEGACY = "ctrl+shift+z"
HOTKEY_QUIT = "ctrl+shift+q"
MAX_IMAGE_SIDE = 1920        # downscale big screenshots to save tokens/time
REQUEST_TIMEOUT = 600        # seconds to wait for the model
POPUP_WIDTH = 460

SYSTEM_PROMPT = (
    "You are an expert in computer organization & architecture and x86 assembly "
    "language (Kip Irvine, MASM, 32-bit/64-bit Intel registers, flags, addressing "
    "modes, instructions like MOV/ADD/SUB/INC/DEC/LOOP/JMP/Jcc/CMP/TEST/PUSH/POP/"
    "CALL/RET/MUL/IMUL/DIV/IDIV/SHL/SHR/SAR/ROL/ROR, directives like PROC/ENDP/"
    "DWORD/BYTE/OFFSET/PTR/TYPE/LENGTHOF/SIZEOF, memory, pipelining, caches, etc.).\n"
    "The image is a screenshot containing one or more multiple-choice questions. "
    "For EVERY question visible in the image, reply in exactly this format and "
    "nothing else:\n\n"
    "Q<number>: <option letter>) <option text, short>\n"
    "<explanation in at most 2 short lines>\n\n"
    "Trace any register/flag values carefully before answering. "
    "Do not repeat the question. Do not add an introduction or conclusion.\n"
    "Render mathematics with valid LaTeX delimiters: use $...$ for inline "
    "math and $$...$$ for display math."
)
USER_PROMPT = "Answer the MCQs in this screenshot."

# Make screenshots use real pixels on scaled (125%/150%) displays.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ------------------------------------------------------------------ ollama
def _http(path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ollama_running():
    try:
        _http("/api/version", timeout=3)
        return True
    except Exception:
        return False


def find_ollama():
    """ollama.exe on PATH, or in its default install folder."""
    exe = shutil.which("ollama")
    if exe:
        return exe
    default = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                           "Programs", "Ollama", "ollama.exe")
    return default if os.path.isfile(default) else None


def ensure_ollama_server():
    """Start `ollama serve` hidden if no server is reachable."""
    if ollama_running():
        return True
    exe = find_ollama()
    if not exe:
        log.error("ollama executable not found")
        return False
    log.info("starting ollama serve")
    subprocess.Popen(
        [exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(60):
        time.sleep(1)
        if ollama_running():
            return True
    log.error("ollama server did not come up")
    return False


def model_installed():
    try:
        names = [m.get("name", "") for m in _http("/api/tags").get("models", [])]
    except Exception:
        return False
    return any(n == MODEL or n.split(":")[0] == MODEL for n in names)


def pull_model(on_progress=None):
    """Download the model via Ollama's /api/pull, reporting progress text."""
    log.info("model %s not installed, downloading", MODEL)
    req = urllib.request.Request(
        OLLAMA_URL + "/api/pull",
        data=json.dumps({"model": MODEL, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_logged = -10
    with urllib.request.urlopen(req, timeout=300) as resp:
        for line in resp:
            if not line.strip():
                continue
            msg = json.loads(line.decode())
            if "error" in msg:
                raise RuntimeError(f"Model download failed: {msg['error']}")
            status = msg.get("status", "")
            total, done = msg.get("total"), msg.get("completed")
            if total and done is not None:
                pct = int(done * 100 / total)
                text = f"{status} {pct}% ({done / 1e9:.2f}/{total / 1e9:.2f} GB)"
                if pct >= last_logged + 10:
                    log.info("pull: %s", text)
                    last_logged = pct
            else:
                text = status
                log.info("pull: %s", status)
            if on_progress:
                on_progress(text)
    if not model_installed():
        raise RuntimeError("Model download finished but the model is not listed.")
    log.info("model %s downloaded", MODEL)


def preload_model():
    """Load the model into memory and keep it there so answers come faster."""
    try:
        _http(
            "/api/generate",
            {"model": MODEL, "prompt": "", "keep_alive": -1},
            timeout=REQUEST_TIMEOUT,
        )
        log.info("model %s loaded", MODEL)
    except Exception as e:
        log.error("preload failed: %s", e)


def ask_model(png_b64):
    payload = {
        "model": MODEL,
        "stream": False,
        "keep_alive": -1,
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [png_b64]},
        ],
    }
    try:
        resp = _http("/api/chat", payload, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        if "think" in body.lower():          # older/other models reject `think`
            payload.pop("think")
            resp = _http("/api/chat", payload, timeout=REQUEST_TIMEOUT)
        else:
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
    text = resp.get("message", {}).get("content", "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # just in case
    return text.strip() or "(model returned an empty answer)"


# -------------------------------------------------------------- screenshot
def take_screenshot_b64():
    img = ImageGrab.grab()  # primary monitor
    w, h = img.size
    scale = MAX_IMAGE_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------------- popup
_LATEX_RE = re.compile(r"(\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)


def render_latex(text):
    """Return a Tk-compatible image for one LaTeX expression."""
    if plt is None:
        return None
    expression = text.strip()
    if expression.startswith("$$") and expression.endswith("$$"):
        expression = expression[2:-2]
        display = True
    elif expression.startswith(r"\[") and expression.endswith(r"\]"):
        expression = expression[2:-2]
        display = True
    elif expression.startswith("$") and expression.endswith("$"):
        expression = expression[1:-1]
        display = False
    elif expression.startswith(r"\(") and expression.endswith(r"\)"):
        expression = expression[2:-2]
        display = False
    else:
        return None
    fig = plt.figure(figsize=(5.2, 0.55 if not display else 0.9), dpi=120)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.02, 0.5, "$" + expression + "$",
            fontsize=13 if not display else 15,
            va="center", ha="left", color="#e8eaed")
    bio = io.BytesIO()
    fig.savefig(bio, format="png", transparent=True,
                bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    bio.seek(0)
    return ImageTk.PhotoImage(Image.open(bio).convert("RGBA"))


class Popup:
    """Borderless always-on-top card with scrollable text and LaTeX images."""

    BG = "#111418"
    FG = "#e8eaed"
    ACCENT = "#4fc3f7"

    def __init__(self, root, title="Answer"):
        self.root = root
        self.photos = []
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.96)
        self.win.configure(bg=self.ACCENT)

        inner = tk.Frame(self.win, bg=self.BG, padx=14, pady=10)
        inner.pack(padx=1, pady=1, fill="both", expand=True)
        self.title = tk.Label(
            inner, bg=self.BG, fg=self.ACCENT, anchor="w",
            font=("Segoe UI Semibold", 10), text=title,
        )
        self.title.pack(fill="x")

        body = tk.Frame(inner, bg=self.BG)
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.body = tk.Text(
            body, bg=self.BG, fg=self.FG, insertbackground=self.FG,
            font=("Segoe UI", 10), wrap="word", width=60, height=12,
            relief="flat", borderwidth=0, padx=4, pady=2,
            highlightthickness=0,
        )
        scrollbar = tk.Scrollbar(body, orient="vertical", command=self.body.yview)
        self.body.configure(yscrollcommand=scrollbar.set)
        self.body.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.body.configure(cursor="arrow")
        self.body.tag_configure("question", foreground="#4fc3f7",
                                font=("Segoe UI Semibold", 10))
        self.body.tag_configure("fallback", foreground="#e8eaed",
                                font=("Segoe UI", 10))

        self.hint = tk.Label(
            inner, bg=self.BG, fg="#80868b", anchor="e",
            font=("Segoe UI", 8), text="Ctrl+Shift+H to hide",
        )
        self.hint.pack(fill="x", pady=(6, 0))

    def show(self, title, text):
        self.title.config(text=title)
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.photos = []

        parts = _LATEX_RE.split(text or "(no answer)")
        for part in parts:
            if not part:
                continue
            if _LATEX_RE.fullmatch(part):
                photo = render_latex(part)
                if photo is not None:
                    self.photos.append(photo)
                    self.body.image_create("end", image=photo)
                    self.body.insert("end", "\n")
                else:
                    self.body.insert("end", part, "fallback")
            else:
                for line in part.splitlines(True):
                    tag = "question" if re.match(r"^Q\d+:", line) else "fallback"
                    self.body.insert("end", line, tag)

        self.body.configure(state="disabled")
        self.body.yview_moveto(0)
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        req_h = min(max(self.body.winfo_reqheight() + 66, 170),
                    sh - 80)
        self.win.geometry(f"{POPUP_WIDTH}x{req_h}+{sw - POPUP_WIDTH - 20}+20")
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

    def hide(self):
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.state() != "withdrawn"


class Toast:
    """Small status notification in the bottom-right corner."""

    BG = "#1b1f24"
    FG = "#e8eaed"
    ACCENT = "#81c995"

    def __init__(self, root):
        self.root = root
        self._hide_job = None
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.92)
        self.win.configure(bg=self.ACCENT)
        self.label = tk.Label(
            self.win, bg=self.BG, fg=self.FG, justify="left", anchor="w",
            font=("Segoe UI", 9), padx=12, pady=8, wraplength=320,
        )
        self.label.pack(padx=(4, 0), pady=0, fill="both")  # green bar on left

    def show(self, text, duration_ms=None):
        """Show `text`; auto-hide after duration_ms (None = stay)."""
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self.label.config(text=text)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"+{sw - w - 20}+{sh - h - 70}")  # above taskbar
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        if duration_ms:
            self._hide_job = self.root.after(duration_ms, self.hide)

    def hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.state() != "withdrawn"


# -------------------------------------------------------------------- app
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = (
            lambda *exc: log.error("tk callback error:\n%s",
                                   "".join(traceback.format_exception(*exc))))
        self.popup = Popup(self.root)
        self.progress_popup = Popup(self.root, "Progress")
        self.toast = Toast(self.root)
        self.thinking_since = None
        self._last_pull_toast = 0.0
        self.events = queue.Queue()
        self.busy = threading.Lock()
        self.init_lock = threading.Lock()
        self.ready = False
        self.pull_status = None  # text while the model is downloading
        self.progress_status = "Starting..."
        self.latest_answer = None

    # called from the keyboard hook thread -> just enqueue
    def on_capture(self):
        self.events.put(("capture", None))

    def on_progress(self):
        self.events.put(("show_progress", None))

    def on_latest(self):
        self.events.put(("show_latest", None))

    def on_hide(self):
        self.events.put(("hide", None))

    def on_quit(self):
        self.events.put(("quit", None))

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "capture":
                    self.start_capture()
                elif kind == "show_progress":
                    self.progress_popup.show("Progress", self.progress_status)
                elif kind == "show_latest":
                    if self.latest_answer is None:
                        self.popup.show("Latest answer",
                                        "No answer yet. Press Ctrl+Shift+X.")
                    else:
                        self.popup.show("Latest answer", self.latest_answer)
                elif kind == "hide":
                    self.popup.hide()
                    self.progress_popup.hide()
                    self.toast.hide()
                elif kind in ("answer", "error"):
                    self.thinking_since = None
                    self.toast.hide()
                    if kind == "answer":
                        self.latest_answer = data
                        self.progress_status = "Complete - answer ready"
                        self.popup.show("Answer", data)
                    else:
                        self.progress_status = "Error - " + data
                        self.popup.show("Error", data)
                elif kind == "progress":
                    self.progress_status = data
                elif kind == "toast":
                    text, duration = data
                    if self.thinking_since is None:  # don't hide the timer
                        self.toast.show(text, duration)
                elif kind == "quit":
                    self.shutdown()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def start_capture(self):
        if not self.busy.acquire(blocking=False):
            log.info("busy, ignoring hotkey")
            return  # the thinking timer is already on screen
        # Hide our own windows so they are not in the screenshot.
        was_visible = (self.popup.visible or self.progress_popup.visible
                       or self.toast.visible)
        self.popup.hide()
        self.progress_popup.hide()
        self.toast.hide()
        self.root.update()
        delay = 150 if was_visible else 0
        self.root.after(delay, self._grab_and_ask)

    def _grab_and_ask(self):
        try:
            img_b64 = take_screenshot_b64()
        except Exception as e:
            log.exception("screenshot failed")
            self.busy.release()
            self.events.put(("error", f"Screenshot failed: {e}"))
            return
        self.progress_status = "Screenshot captured - asking " + MODEL
        self.events.put(("progress", self.progress_status))
        self.thinking_since = time.time()
        self._tick_thinking()
        threading.Thread(target=self._worker, args=(img_b64,), daemon=True).start()

    def _tick_thinking(self):
        """Update the 'thinking' toast once a second until the answer arrives."""
        if self.thinking_since is None:
            return
        secs = int(time.time() - self.thinking_since)
        dots = "." * (secs % 3 + 1)
        status = f"Thinking{dots}  {secs}s"
        self.progress_status = status
        self.events.put(("progress", status))
        self.toast.show(f"\U0001F4F8  Screenshot taken\n{status}")
        self.root.after(1000, self._tick_thinking)

    def _worker(self, img_b64):
        try:
            if self.pull_status is not None:
                self.events.put((
                    "error",
                    f"Model is still downloading:\n{self.pull_status}\n\n"
                    "Press Ctrl+Shift+X again when it finishes.",
                ))
                return
            if not self.ready:
                self.startup_checks()
            t0 = time.time()
            answer = ask_model(img_b64)
            log.info("answer in %.1fs:\n%s", time.time() - t0, answer)
            self.events.put(("answer", answer))
        except Exception as e:
            log.exception("model request failed")
            self.events.put(("error", str(e)))
        finally:
            self.busy.release()

    def startup_checks(self):
        with self.init_lock:  # only one thread starts the server / downloads
            if self.ready:
                return
            self.events.put(("progress", "Starting Ollama server"))
            if not ensure_ollama_server():
                if not find_ollama():
                    raise RuntimeError(
                        "Ollama is not installed.\n"
                        "Install it from https://ollama.com/download")
                raise RuntimeError(
                    "Ollama server is not running and could not be started.")
            if not model_installed():
                self.pull_status = "starting download..."
                self.events.put(("progress", "Downloading " + MODEL))
                try:
                    pull_model(self._set_pull_status)
                finally:
                    self.pull_status = None
            self.ready = True

    def _set_pull_status(self, text):
        self.pull_status = text
        self.events.put(("progress", text))
        now = time.time()
        if now - self._last_pull_toast >= 1:  # at most one update per second
            self._last_pull_toast = now
            self.toast_async(f"⬇  Downloading model\n{text}")

    def toast_async(self, text, duration_ms=None):
        """Show a toast from any thread."""
        self.events.put(("toast", (text, duration_ms)))

    def background_init(self):
        try:
            self.events.put(("progress", "Checking Ollama and " + MODEL))
            if not self.ready and ollama_running() and not model_installed():
                self.toast_async("⬇  Model not found, starting download...")
            self.startup_checks()
            self.events.put(("progress", "Loading " + MODEL))
            self.toast_async("⏳  Loading model into memory...")
            preload_model()
            self.events.put(("progress", "Ready - " + MODEL))
            self.toast_async("✅  Model ready. Press Ctrl+Shift+X", 3000)
        except Exception as e:
            log.error("startup: %s", e)
            self.toast_async(f"⚠  Startup problem:\n{e}", 6000)

    def shutdown(self):
        log.info("quitting")
        keyboard.unhook_all()
        self.thinking_since = None
        self.popup.hide()
        self.progress_popup.hide()
        self.toast.show("MCQ Helper stopped")
        self.root.after(1200, self.root.destroy)

    def run(self):
        keyboard.add_hotkey(HOTKEY_CAPTURE, self.on_capture, suppress=False)
        keyboard.add_hotkey(HOTKEY_PROGRESS, self.on_progress, suppress=False)
        keyboard.add_hotkey(HOTKEY_LATEST, self.on_latest, suppress=False)
        keyboard.add_hotkey(HOTKEY_HIDE, self.on_hide, suppress=False)
        keyboard.add_hotkey(HOTKEY_HIDE_LEGACY, self.on_hide, suppress=False)
        keyboard.add_hotkey(HOTKEY_QUIT, self.on_quit, suppress=False)
        # Start loading after the startup toast so its hotkey list stays readable.
        self.root.after(
            4000,
            lambda: threading.Thread(target=self.background_init, daemon=True).start(),
        )
        log.info("running; model=%s; hotkeys capture=%s progress=%s "
                 "latest=%s hide=%s quit=%s",
                 MODEL, HOTKEY_CAPTURE, HOTKEY_PROGRESS, HOTKEY_LATEST,
                 HOTKEY_HIDE, HOTKEY_QUIT)
        self.toast.show(
            "✅  MCQ Helper is running in the background\n"
            "X answer  •  / progress  •  ' latest  •  H hide  •  Q quit",
            4000,
        )
        self.root.after(50, self.poll)
        self.root.mainloop()


def single_instance():
    """Prevent two copies from running (both would answer the hotkey)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\MCQHelperMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if not single_instance():
        log.info("another instance is already running, exiting")
        ctypes.windll.user32.MessageBoxW(
            None,
            "MCQ Helper is already running in the background.\n\n"
            "Ctrl+Shift+X = answer, Ctrl+Shift+/ = progress,\n"
            "Ctrl+Shift+' = latest answer, Ctrl+Shift+H = hide,\n"
            "Ctrl+Shift+Q = quit.\n"
            "(Quit it first if you want to restart it.)",
            "MCQ Helper", 0x40)
        sys.exit(0)
    App().run()
