import os


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sample.settings')

from bazis.core.app import app  # noqa: F401


if __name__ == "__main__":
    app.uvicorn_start()
