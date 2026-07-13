from pathlib import Path
from fastapi.testclient import TestClient
from web.app import app
def test_recovered_routes(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "chapters").mkdir(parents=True)
    (tmp_path / "data" / "chapters" / "chapter_001.md").write_text("# One\n\nArrival.",encoding="utf-8")
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/planning/overview").status_code == 200
        assert client.get("/api/narrative-memory/overview").status_code == 200
        assert client.post("/api/revisions",json={"chapter_id":1}).status_code == 200


def test_recovered_revision_flow(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path); chapter=tmp_path/'data'/'chapters'/'chapter_001.md'; chapter.parent.mkdir(parents=True); chapter.write_text('# One\n\nOriginal.',encoding='utf-8')
    with TestClient(app) as client:
        created=client.post('/api/revisions',json={'chapter_id':1}).json(); rid=created['result']['revision']['revision_id']
        candidate=client.post(f'/api/revisions/{rid}/candidates',json={'content':'# One\n\nChanged.'}).json()['result']['candidate']
        assert client.get(f"/api/revisions/{rid}/candidates/{candidate['candidate_version_id']}").status_code==200
        updated=client.put(f"/api/revisions/{rid}/candidates/{candidate['candidate_version_id']}",json={'content':'# One\n\nChanged again.'}).json()
        assert updated['ok'] is True and updated['result']['replaces_candidate_id']==candidate['candidate_version_id']
        assert client.get(f'/api/revisions/{rid}/diff').status_code==200
        for endpoint in ('quality-check','continuity-check','impact-analysis'):
            response=client.post(f'/api/revisions/{rid}/{endpoint}',json={})
            assert response.status_code==200 and response.json()['result']['job']['job_type'].startswith('revision_')
        assert client.post(f'/api/revisions/{rid}/review',json={'decision':'approve'}).status_code==200
        assert client.get('/api/chapters/1/canon-versions').status_code==200


def test_recovered_planning_crud(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        made=client.post('/api/planning/chapters',json={'payload':{'title':'Plan'}}); assert made.status_code==200
        item=made.json()['result']['item']; key=item.get('chapter_id') or item.get('id')
        assert client.get('/api/planning/chapters').status_code==200
        if key: assert client.put(f'/api/planning/chapters/{key}',json={'payload':{'title':'Updated'}}).status_code==200

def test_recovered_job_endpoints(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/jobs').status_code==200
        assert client.get('/api/jobs/active').status_code==200


def test_recovered_narrative_endpoints(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path); chapter=tmp_path/'data'/'chapters'/'chapter_001.md'; chapter.parent.mkdir(parents=True); chapter.write_text('# One\n\nHe arrived at the gate.',encoding='utf-8')
    with TestClient(app) as client:
        assert client.post('/api/narrative-memory/chapters/1/extract').status_code==200
        assert client.get('/api/narrative-memory/timeline').status_code==200
        assert client.get('/api/narrative-memory/conflicts').status_code==200
        assert client.post('/api/continuity/preflight',json={'chapter_id':2}).status_code in {200,409}

def test_narrative_confirmation_projection_snapshot_and_preview(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    chapter = tmp_path / 'data' / 'chapters' / 'chapter_001.md'
    chapter.parent.mkdir(parents=True)
    chapter.write_text('# One\n\nThe guide arrived at the gate.', encoding='utf-8')
    with TestClient(app) as client:
        extracted = client.post('/api/narrative-memory/chapters/1/extract').json()['result']['events']
        assert extracted and extracted[0]['confirmation_status'] == 'unreviewed'
        event = client.post(
            f"/api/narrative-memory/events/{extracted[0]['event_id']}/confirm",
            json={'decision': 'corrected', 'patch': {'state_changes': [{'entity_type': 'locations', 'entity_id': 'gate', 'patch': {'occupied': True}}]}},
        ).json()['result']['event']
        assert event['confirmation_status'] == 'corrected'
        assert client.post('/api/narrative-memory/project').status_code == 200
        overview = client.get('/api/narrative-memory/overview').json()['result']
        assert overview['state']['locations']['gate']['occupied'] is True
        assert client.post('/api/narrative-memory/chapters/1/snapshot').status_code == 200
        assert client.get('/api/narrative-memory/context-preview?chapter_id=2').status_code == 200
        assert client.post('/api/narrative-memory/overrides/pins', json={'value': 'Preserve the gate arrival.'}).status_code == 200

def test_recovery_client_contract():
    root=Path(__file__).resolve().parents[1]
    text=(root/'web'/'static'/'recovery-api.js').read_text(encoding='utf-8')
    assert '/api/projects' in text and '/api/jobs' in text and '/api/revisions' in text


def test_restored_error_contracts(monkeypatch,tmp_path:Path):
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/jobs/missing/logs').status_code==404
        assert client.post('/api/jobs/missing/retry').status_code==404
        assert client.get('/api/archive/missing').status_code==404


def test_recovered_frontend_contract():
    root=Path(__file__).resolve().parents[1]
    template=(root/'web'/'templates'/'index.html').read_text(encoding='utf-8')
    recovery=(root/'web'/'static'/'recovery-api.js').read_text(encoding='utf-8')
    narrative=(root/'web'/'static'/'narrative-memory-view.js').read_text(encoding='utf-8')
    assert 'narrative-memory-panel' in template and 'narrative-memory-view.js' in template
    assert 'storyos:project-changed' in recovery and 'storyos:project-cleared' in recovery
    assert '/api/narrative-memory/overview' in narrative and 'storyos:project-cleared' in narrative
    assert 'data-event-confirm' in narrative and 'data-event-reject' in narrative
    assert 'data-narrative-extract' in template and 'data-narrative-preview' in template


def test_context_aware_web_assets_follow_active_project_without_chdir(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for name, title in (("a", "Novel A"), ("b", "Novel B")):
        data = tmp_path / 'projects' / name / 'data'
        data.mkdir(parents=True)
        (data / 'story_spec.json').write_text('{"title": "' + title + '"}', encoding='utf-8')
        (data / 'state.json').write_text('{"current_chapter": 0}', encoding='utf-8')
    config = tmp_path / '.story_os' / 'config.json'
    config.parent.mkdir()
    config.write_text('{"active_project": "projects/a"}', encoding='utf-8')
    with TestClient(app) as client:
        assets_a = client.get('/api/project-assets').json()['result']['assets']
        assert 'Novel A' in next(item for item in assets_a if item['id'] == 'story_spec')['content']
        config.write_text('{"active_project": "projects/b"}', encoding='utf-8')
        assets_b = client.get('/api/project-assets').json()['result']['assets']
        assert 'Novel B' in next(item for item in assets_b if item['id'] == 'story_spec')['content']
        assert client.post('/api/project-assets/project_md', json={'content': '# B'}).status_code == 200
    assert not (tmp_path / 'projects' / 'a' / 'data' / 'project.md').exists()
    assert (tmp_path / 'projects' / 'b' / 'data' / 'project.md').read_text(encoding='utf-8') == '# B'
