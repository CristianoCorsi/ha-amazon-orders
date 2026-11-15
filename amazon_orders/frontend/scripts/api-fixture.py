"""Disposable synthetic API fixture for frontend smoke tests. No jobs, no Amazon traffic.
Run from frontend: uv run --project ../backend --no-sync python scripts/api-fixture.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend" / "src"))
from amazon_orders_ha.api import create_app
from amazon_orders_ha.auth_provider import DevAuthProvider
from amazon_orders_ha.config import Options, Settings
from amazon_orders_ha.dev import seed_database
from amazon_orders_ha.ha import HAEvents, MqttPublisher
from amazon_orders_ha.service import build_runtime
import uvicorn

scratch = Path(tempfile.mkdtemp(prefix="amazon-orders-ui-", dir=os.environ["TMPDIR"]))
settings = Settings(data_dir=scratch, options=Options(), frontend_dir=ROOT / "build")
rt = build_runtime(settings, auth=DevAuthProvider(), events=HAEvents(token=""), mqtt=MqttPublisher(settings.options))
seed_database(rt.db)
print(f"Synthetic fixture data: {scratch}", flush=True)
# background=False is deliberate: sync gates must never call Amazon in this fixture.
uvicorn.run(create_app(rt, background=False), host="127.0.0.1", port=18765, log_level="warning")
