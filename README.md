# MCQ Helper

Background tool for Windows. It takes a screenshot when you press a hotkey, sends it to the local Ollama vision model (`gemma4:e4b`), and shows the answer in a small popup. LaTeX expressions are rendered as images in the popup.

## Install on a new PC

1. **Install Python 3.10 or newer** from <https://www.python.org/downloads/>.
   On the first installer screen, tick **"Add python.exe to PATH"**. Keep the default options, which include tcl/tk.
2. **Install Ollama** from <https://ollama.com/download>, or run `winget install Ollama.Ollama`.
3. **Get this folder** onto the PC: `git clone https://github.com/nabeelali0707/micheal.git`, or on GitHub click **Code → Download ZIP** and unzip it.
4. **Double-click `setup.bat`.** It checks Python, tkinter and Ollama, installs the Python packages (`keyboard`, `pillow`, `matplotlib`) and offers to download `gemma4:e4b`. Fix anything it marks with `[X]`, then run it again.
5. **Double-click `start.bat`.** A message in the bottom-right corner says it is running.

The model needs about 6 GB of free RAM (or VRAM). On a weak laptop, the first answer can take a minute or more.

## Troubleshooting

- **Nothing happens after `start.bat`:** double-click `debug.bat`. It runs the program with a console window so you can see the error, and prints the end of `mcq_helper.log`.
- **"MCQ Helper is already running":** a copy is already in the background. Press `Ctrl+Shift+Q` to stop it, then start again.
- **"Missing Python package":** run `setup.bat`.
- **Hotkeys don't work in one particular app:** that app is probably running as Administrator. Right-click `start.bat` → *Run as administrator*.
- **"Ollama is not installed" / "server not running":** install Ollama, or open the Ollama app once, then try again.
- **`python` opens the Microsoft Store:** Python isn't really installed. Do step 1, and turn off the Store aliases under *Settings → Apps → Advanced app settings → App execution aliases*.

## Run

Double-click `start.bat`, or run `pythonw mcq_helper.py`. The program runs in the background and loads the model at startup. If the model is missing, it downloads automatically.

| Hotkey | Action |
| --- | --- |
| `Ctrl+Shift+X` | Take a screenshot and show the answer popup (top-right corner) |
| `Ctrl+Shift+/` | Show the live progress popup |
| `Ctrl+Shift+'` | Show the latest answer popup |
| `Ctrl+Shift+H` | Hide the answer, progress, and notification popups |
| `Ctrl+Shift+Z` | Legacy hide shortcut |
| `Ctrl+Shift+Q` | Quit |

A small notification in the bottom-right corner tells you what the program is doing:

- On start: "MCQ Helper is running in the background", with the hotkey list
- While the model loads or downloads: loading message or download progress, then "Model ready"
- After `Ctrl+Shift+X`: "Screenshot taken · Thinking… 5s", with a live timer until the answer appears
- On `Ctrl+Shift+Q`: "MCQ Helper stopped"

Logs and errors are written to `mcq_helper.log`. If the program crashes, a message box shows the error.

## Config

Settings are at the top of `mcq_helper.py`: `MODEL`, hotkeys, `MAX_IMAGE_SIDE`, `POPUP_WIDTH` and the system prompt.

To start it automatically with Windows, press `Win+R`, type `shell:startup`, and put a shortcut to `start.bat` in that folder.
