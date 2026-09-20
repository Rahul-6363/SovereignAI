"""Health and model-gateway routes."""
from fastapi import APIRouter

from app.deps import get_state
from app.schemas import ModelStatusOut, TrustStatusOut

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health_status():
    state = get_state()
    ollama_ok = await state.gateway.is_available()
    return {
        "status": "ok",
        "ollama": ollama_ok,
        "app": "meshcore",
        "local_only": not state.settings.enable_external_network,
    }


@router.get("/ollama")
async def ollama_health():
    state = get_state()
    ok = await state.gateway.is_available()
    models = await state.gateway.local_models()
    sizes = await state.gateway.model_sizes()
    return {
        "connected": ok,
        "base_url": state.settings.ollama_base_url,
        "models": models,
        "sizes": sizes,
        "chat_model_installed": await state.gateway.model_installed(
            state.settings.ollama_chat_model
        ),
        "vision_model_installed": await state.gateway.model_installed(
            state.settings.ollama_vision_model
        ),
        "embed_model_installed": await state.gateway.model_installed(
            state.settings.ollama_embed_model
        ),
        "latency": state.gateway.latency.history[-10:],
    }