import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from scripts.seed_demo import seed, setup_schema
from src.config.settings import SEED_DEMO
from src.domain.scenario import CONFIG
from src.middlewares.errors import catch_errors
from src.middlewares.request_id import request_id
from src.routes import cases, redactions as redaction_routes, runs, session, system
from src.services.redactions import recover_pending_safe


@asynccontextmanager
async def lifespan(_app):
    setup_schema()
    if SEED_DEMO:
        try:
            seed()
        except Exception:
            logging.getLogger(__name__).exception("Demo seed failed")
    recover_pending_safe()
    yield


app = FastAPI(title=CONFIG["title"], lifespan=lifespan)
app.middleware("http")(catch_errors)
app.middleware("http")(request_id)
for group in (system, session, cases, runs, redaction_routes):
    app.include_router(group.router)
