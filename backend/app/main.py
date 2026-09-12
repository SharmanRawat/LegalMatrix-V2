from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import inspections, auth, dashboard, search
from app.config import ALLOWED_ORIGINS
from app.core.rule_engine import rule_engine
from app.database.models import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_default_admin()
    yield


def _seed_default_admin(data_dir=None):
    """Create a demo admin account if no users exist yet."""
    from app.repositories import users as user_repo
    if not user_repo.list_users():
        user_repo.create_user("admin", "System Administrator", "ADMIN", "admin@123")
        print("[Startup] Seeded default admin account: admin / admin@123  (CHANGE IN PRODUCTION)", flush=True)


app = FastAPI(
    title="LegalMatrix - Legal Metrology Inspection Platform",
    description="AI-assisted compliance checking for packaged commodities",
    version="1.1.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(inspections.router, prefix="/api", tags=["Inspections"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(search.router, prefix="/api", tags=["Search"])


@app.get("/")
async def root():
    return {"message": "LegalMatrix API is running", "version": "1.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/rules")
async def get_rules():
    return {
        "version": rule_engine.version,
        "declarations": rule_engine.get_required_declarations(),
        "effective_date": rule_engine.rules.get("effective_date"),
    }