from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pharmacovigilance.core import build_report, snapshot
router = APIRouter()
class ReportRequest(BaseModel):
    drug: str = Field(min_length=2, max_length=80)
    live: bool = True
@router.get('/pharmacovigilance', include_in_schema=False)
def page():
    return FileResponse(Path(__file__).with_name('index.html'))
@router.get('/api/pv/drugs')
def drugs():
    return snapshot('metformin').get('available_drugs', [])
@router.post('/api/pv/report')
def report(req: ReportRequest):
    try:
        value = build_report(req.drug, live=req.live)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if 'error' in value:
        raise HTTPException(404, value)
    return value
