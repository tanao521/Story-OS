from __future__ import annotations
from pathlib import Path
import pytest
from core.project_context import get_project_context
from system.data_store import DataStore
from system.planning_service import create_entity, delete_entity, load_planning, reorder, save_planning, sync_next_plan, validate

def test_legacy_blueprint_migrates_without_loss(tmp_path: Path):
 c=get_project_context(tmp_path); DataStore(c).write_json('data/story_blueprint.json',{'title':'Legacy','unknown':{'kept':True},'story_phases':[{'phase_id':1,'title':'Start'}],'chapter_plan':[{'chapter_id':2,'chapter_title':'Two'}]})
 p=load_planning(c); assert p['story']['title']=='Legacy'; assert p['legacy_blueprint']['unknown']['kept']; assert p['phases'][0]['phase_id']==1
 save_planning(p,c); assert (c.data_dir/'story_planning.json').exists()

def test_references_validation_and_safe_volume_delete(tmp_path: Path):
 c=get_project_context(tmp_path); v=create_entity('volumes',{'title':'One'},c); ch=create_entity('chapters',{'title':'One','chapter_number':1,'volume_id':v['volume_id']},c)
 with pytest.raises(ValueError): delete_entity('volumes',v['volume_id'],c)
 p=load_planning(c); assert not validate(p,c)['errors']; assert ch['chapter_id']

def test_reorder_and_sync_next_plan(tmp_path: Path):
 c=get_project_context(tmp_path); a=create_entity('chapters',{'title':'A','chapter_number':1},c); b=create_entity('chapters',{'title':'B','chapter_number':2,'chapter_goal':'Goal'},c)
 reorder('chapters',[b['chapter_id'],a['chapter_id']],c); next_plan=sync_next_plan(b['chapter_id'],c)
 assert next_plan['chapter_id']==2 and next_plan['chapter_goal']=='Goal'
