"""Broker settings — a single config surface for the paper broker."""

from fastapi import APIRouter, Request

from services import config_store

router = APIRouter(tags=["config"])


@router.get("/v1/config")
async def get_config(request: Request):
    """Current broker config + field metadata (defaults + help) for the UI."""
    return config_store.describe()


@router.put("/v1/config")
async def put_config(patch: dict, request: Request):
    """Update broker config; applies live (fees, pricing, defaults)."""
    cfg = config_store.save(patch)
    # apply live so subsequent trades/accounts pick it up without a restart
    request.app.state.pmb_config = cfg
    svc = getattr(request.app.state, "account_service", None)
    if svc is not None:
        svc._fee_per_share = float(cfg.get("fee_per_share", 0.0))
        svc._bp_mult = float(cfg.get("buying_power_multiplier", 2.0))
    return {"ok": True, "config": cfg}
