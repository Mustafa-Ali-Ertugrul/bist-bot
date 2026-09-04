"""Production WSGI entry point for the Flask API."""

from bist_bot.dashboard import create_default_dashboard_app

app = create_default_dashboard_app()
