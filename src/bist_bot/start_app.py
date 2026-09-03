import subprocess  # nosec B404: fixed local entrypoint launch below.
import sys

# nosec B603: fixed argv (current interpreter + repo main.py), no shell.
subprocess.run([sys.executable, "main.py"])  # nosec B603
