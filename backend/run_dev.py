"""Geliştirme sunucusu: önce veritabanı migration'larını uygular, sonra API'yi başlatır.

Kullanım: python run_dev.py   (backend/.venv içinden; çalışma dizini önemsiz)
"""

from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "alembic"))
    command.upgrade(cfg, "head")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, app_dir=str(HERE), reload=False)
