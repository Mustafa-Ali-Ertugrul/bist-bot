# ruff: noqa: E402,F403
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bist_bot.dashboard import *
from bist_bot.dashboard import create_default_dashboard_app

if __name__ == "__main__":
    app = create_default_dashboard_app()
    from bist_bot.config.settings import settings

    app.run(
        host="0.0.0.0", port=settings.FLASK_PORT, debug=False, use_reloader=settings.FLASK_DEBUG
    )
