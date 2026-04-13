from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_settings import router as admin_settings_router
from app.api.auth import router as auth_router
from app.api.auth_oauth import router as auth_oauth_router
from app.api.candidates import router as candidates_router
from app.api.estaff import router as estaff_router
from app.api.favorites import router as favorites_router
from app.api.history import router as history_router
from app.api.llm import router as llm_router
from app.api.hh import router as hh_router
from app.api.reference import router as reference_router
from app.api.search import router as search_router
from app.api.telegram import router as telegram_router
from app.api.templates import router as templates_router
from app.config import settings
from app.services.encryption import validate_encryption_key_for_environment


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_encryption_key_for_environment()
    yield


app = FastAPI(title="HR Service API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

v1 = APIRouter(prefix="/v1")
v1.include_router(auth_router)
v1.include_router(admin_settings_router)
v1.include_router(auth_oauth_router)
v1.include_router(hh_router)
v1.include_router(reference_router)
v1.include_router(search_router)
v1.include_router(history_router)
v1.include_router(templates_router)
v1.include_router(favorites_router)
v1.include_router(candidates_router)
v1.include_router(estaff_router)
v1.include_router(llm_router)
v1.include_router(telegram_router)
app.include_router(v1, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
