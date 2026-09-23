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
    """Create the configured admin account if no users exist, or rotate its
    password at boot when the operator explicitly set
    LEGALMATRIX_ADMIN_PASSWORD (credential rotation for shared demos).

    The password itself is never printed — logs carry the username only.
    """
    from pathlib import Path

    from app import config as cfg
    from app.repositories import users as user_repo

    admin_username, admin_password, password_explicit = cfg.get_admin_credentials()
    data_dir = cfg.get_data_dir() if data_dir is None else Path(data_dir)
    db_path = str(data_dir / "legalmatrix.db")

    existing = user_repo.get_user_by_username(admin_username, db_path=db_path)
    if existing is None:
        user_repo.create_user(
            admin_username, "System Administrator", "ADMIN", admin_password,
            db_path=db_path,
        )
        print(
            f"[Startup] Seeded admin account: {admin_username} "
            "(set LEGALMATRIX_ADMIN_PASSWORD to change it)",
            flush=True,
        )
    elif password_explicit and not user_repo.verify_password(
        admin_password, existing["password_hash"], existing["salt"]
    ):
        user_repo.update_password(admin_username, admin_password, db_path=db_path)
        print(f"[Startup] Rotated password for admin account: {admin_username}", flush=True)

    if cfg.AUTH_SECRET_IS_DEFAULT:
        print(
            "[Startup] WARNING: LEGALMATRIX_AUTH_SECRET is the insecure default — "
            "set a random value before any shared demo/deployment.",
            flush=True,
        )


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