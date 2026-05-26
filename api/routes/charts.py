"""GET /charts and GET /charts/{chart_name} — serves PNGs from outputs/charts."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import get_charts_dir

router = APIRouter(prefix="/charts", tags=["charts"])


@router.get("")
def charts_list() -> dict:
    """List every .png currently sitting in outputs/charts/."""
    base = Path(get_charts_dir())
    if not base.is_dir():
        return {"charts_dir": str(base), "charts": []}
    files = sorted(p.name for p in base.glob("*.png"))
    return {"charts_dir": str(base), "charts": files}


@router.get("/{chart_name}")
def charts_get(chart_name: str):
    # Defensive: never let the client traverse out of the charts dir.
    if "/" in chart_name or "\\" in chart_name or ".." in chart_name:
        raise HTTPException(status_code=400, detail="invalid chart name")
    base = Path(get_charts_dir())
    path = base / chart_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"chart not found: {chart_name}")
    return FileResponse(str(path), media_type="image/png")
