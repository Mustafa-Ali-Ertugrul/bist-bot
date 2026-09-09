"""Streamlit deprecation placeholder.

The legacy Streamlit web UI has been retired in favor of the pixel-exact
Stitch UI served natively on the Flask API dashboard (port 5000).
Access the web console at: http://localhost:5000/ui/dashboard
"""

import sys

if __name__ == "__main__":
    print(
        "INFO: Legacy Streamlit UI is deprecated and retired.\n"
        "Please use the new Stitch UI at http://localhost:5000/ui/dashboard\n"
        "Start the application with: python dashboard.py"
    )
    sys.exit(0)
