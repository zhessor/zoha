# Install

You need Windows 10 or 11 and Python 3.12 or newer.

```powershell
git clone https://github.com/zhessor/zoha.git
cd zoha
.\setup.ps1
```

`setup.ps1` creates a virtual environment, installs the packages, offers the GPU extras if you have an NVIDIA card, and starts the setup wizard. The wizard asks your name, city and which brain to use, then writes `.env`.

Start the desktop app:

```powershell
.\venv\Scripts\python.exe gui.py
```

Text-only mode: `python main.py --text`.

## For developers

```powershell
pip install -e .[dev]
python -m pytest
```
