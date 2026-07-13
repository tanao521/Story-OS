from __future__ import annotations
from pathlib import Path
from fastapi.testclient import TestClient
from web.app import app

def test_planning_api_contract(tmp_path: Path, monkeypatch):
 monkeypatch.chdir(tmp_path)
 with TestClient(app) as client:
  overview=client.get('/api/planning/overview').json(); assert overview['ok'] and 'planning' in overview['result']
  volume=client.post('/api/planning/volumes',json={'payload':{'title':'Volume A'}}).json()['result']['item']
  chapter=client.post('/api/planning/chapters',json={'payload':{'title':'Chapter A','chapter_number':1,'volume_id':volume['volume_id']}}).json()['result']['item']
  assert client.get('/api/planning/chapters').json()['result']['chapters']
  assert client.get('/api/planning/validation').json()['ok']
  assert client.post(f"/api/planning/chapters/{chapter['chapter_id']}/sync-next").json()['ok']
  assert client.delete(f"/api/planning/volumes/{volume['volume_id']}").json()['ok'] is False
