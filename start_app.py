import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "streamlit_app.py"],
    shell=True
)

print("Uygulama baslatildi!")
print("Tarayiciyi ac ve http://localhost:8501 adresine git")
