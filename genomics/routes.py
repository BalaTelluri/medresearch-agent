from pathlib import Path
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from genomics.core import interpret, DATA
router=APIRouter()
class Request(BaseModel):
    text:str
    assembly:str='GRCh38'
    literature:bool=True
@router.get('/genomics',include_in_schema=False)
def page(): return FileResponse(Path(__file__).parent/'index.html')
@router.get('/api/genomics/metrics')
def metrics(): return {'metrics':json.loads((DATA/'metrics.json').read_text()),'manifest':json.loads((DATA/'manifest.json').read_text())}
@router.post('/api/genomics/interpret')
def run(req:Request):
    try: return interpret(req.text,req.assembly,req.literature)
    except ValueError as e: raise HTTPException(400,str(e))
