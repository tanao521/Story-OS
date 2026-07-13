from __future__ import annotations
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore

ENTITY_KEYS={"volumes":"volume_id","phases":"phase_id","chapters":"chapter_id","plot_threads":"thread_id","character_arcs":"character_arc_id","foreshadowing":"foreshadowing_id","conflicts":"conflict_id","climaxes":"climax_id"}

def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _id(prefix): return f"{prefix}_{uuid4().hex[:10]}"
def _path(c): return c.data_dir / "story_planning.json"
def _versions(c): return c.data_dir / "planning_versions"

def load_planning(context: ProjectContext|None=None)->dict[str,Any]:
 c=context or get_project_context(); store=DataStore(c); saved=store.read_json(_path(c),default=None,expected_type=dict)
 if saved: return _normalize(saved)
 legacy=store.read_json(c.data_dir/'story_blueprint.json',default={},expected_type=dict) or {}
 plan={"schema_version":"2.0","created_at":_now(),"updated_at":_now(),"story":{"title":legacy.get("title",""),"core_premise":legacy.get("core_premise",""),"theme":legacy.get("theme","") or legacy.get("genre",""),"protagonist_goal":legacy.get("main_arc","") ,"core_conflict":legacy.get("core_conflict","") ,"ending_direction":legacy.get("ending_direction","") ,"tone":legacy.get("tone","")},"volumes":[],"phases":copy.deepcopy(legacy.get("story_phases",[]) or []),"chapters":copy.deepcopy(legacy.get("chapter_plan",[]) or []),"plot_threads":copy.deepcopy(legacy.get("plot_threads",[]) or []),"character_arcs":copy.deepcopy(legacy.get("character_arcs",[]) or []),"foreshadowing":copy.deepcopy(legacy.get("foreshadows",[]) or []),"conflicts":[],"climaxes":[],"world_rule_refs":[],"legacy_blueprint":legacy}
 return _normalize(plan)

def _normalize(plan):
 plan=copy.deepcopy(plan); plan.setdefault('schema_version','2.0'); plan.setdefault('story',{}); plan.setdefault('legacy_blueprint',{}); plan.setdefault('created_at',_now()); plan.setdefault('updated_at',_now())
 for key,idkey in ENTITY_KEYS.items():
  values=plan.setdefault(key,[])
  for i,item in enumerate(values):
   if not isinstance(item,dict): values[i]={idkey:_id(idkey.replace('_id','') ),'title':str(item),'order':i+1}
   item=values[i]; item.setdefault(idkey, str(item.get('id') or _id(idkey.replace('_id','')))); item.setdefault('order',i+1); item.setdefault('title',item.get('chapter_title',''))
 return plan

def save_planning(plan,context=None,reason='manual save'):
 c=context or get_project_context(); store=DataStore(c); plan=_normalize(plan); plan['updated_at']=_now(); _versions(c).mkdir(parents=True,exist_ok=True); version=f"planning_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"; snapshot={'version_id':version,'created_at':_now(),'reason':reason,'planning':plan}; store.write_json(_versions(c)/f'{version}.json',snapshot,backup=False); store.write_json(_path(c),plan,backup=True); return plan

def overview(context=None):
 c=context or get_project_context(); p=load_planning(c); validation=validate(p,c); state=DataStore(c).read_json(c.data_dir/'state.json',default={},expected_type=dict) or {}; return {'planning':p,'summary':{'current_chapter':state.get('current_chapter',0),'volumes':len(p['volumes']),'phases':len(p['phases']),'chapters':len(p['chapters']),'active_threads':sum(1 for x in p['plot_threads'] if x.get('status')=='active'),'open_foreshadows':sum(1 for x in p['foreshadowing'] if x.get('status') not in {'resolved','abandoned'})},'validation':validation}

def list_entities(kind,context=None): return load_planning(context).get(kind,[])
def create_entity(kind,payload,context=None):
 c=context or get_project_context(); p=load_planning(c); key=ENTITY_KEYS[kind]; item=copy.deepcopy(payload); item[key]=item.get(key) or _id(key.replace('_id','')); item.setdefault('order',len(p[kind])+1); p[kind].append(item); save_planning(p,c,f'create {kind}'); return item
def update_entity(kind,entity_id,payload,context=None):
 c=context or get_project_context(); p=load_planning(c); key=ENTITY_KEYS[kind]
 for item in p[kind]:
  if str(item.get(key))==entity_id: item.update(copy.deepcopy(payload)); item[key]=entity_id; save_planning(p,c,f'update {kind}'); return item
 raise KeyError(entity_id)
def delete_entity(kind,entity_id,context=None):
 c=context or get_project_context(); p=load_planning(c); key=ENTITY_KEYS[kind]; item=next((x for x in p[kind] if str(x.get(key))==entity_id),None)
 if item is None: raise KeyError(entity_id)
 if kind=='volumes' and any(str(x.get('volume_id'))==entity_id for x in p['chapters']): raise ValueError('Cannot delete a volume that still has chapter plans.')
 if kind=='phases' and any(str(x.get('phase_id'))==entity_id for x in p['chapters']): raise ValueError('Cannot delete a phase that still has chapter plans.')
 p[kind].remove(item); save_planning(p,c,f'delete {kind}'); return item
def reorder(kind,ids,context=None):
 c=context or get_project_context(); p=load_planning(c); key=ENTITY_KEYS[kind]; byid={str(x.get(key)):x for x in p[kind]}
 if set(ids)!=set(byid): raise ValueError('Reorder ids must match the existing collection.')
 if kind=='chapters' and any(x.get('status')=='committed' for x in p[kind]): raise ValueError('Committed chapter plans cannot be reordered.')
 p[kind]=[byid[x] for x in ids]
 for i,x in enumerate(p[kind],1): x['order']=i
 save_planning(p,c,f'reorder {kind}'); return p[kind]
def validate(p=None,context=None):
 c=context or get_project_context(); p=p or load_planning(c); warnings=[]; errors=[]; vols={str(x.get('volume_id')) for x in p['volumes']}; phases={str(x.get('phase_id')) for x in p['phases']}; nums=set()
 for ch in p['chapters']:
  n=ch.get('chapter_number',ch.get('chapter_id')); 
  if n in nums: errors.append(f'Duplicate chapter number: {n}')
  nums.add(n)
  if ch.get('volume_id') and str(ch['volume_id']) not in vols: warnings.append(f'Chapter {n} references a missing volume.')
  if ch.get('phase_id') and str(ch['phase_id']) not in phases: warnings.append(f'Chapter {n} references a missing phase.')
 return {'ok':not errors,'warnings':warnings,'errors':errors}
def sync_next_plan(chapter_id,context=None):
 c=context or get_project_context(); store=DataStore(c); p=load_planning(c); ch=next((x for x in p['chapters'] if str(x.get('chapter_id'))==str(chapter_id) or str(x.get('chapter_number'))==str(chapter_id)),None)
 if not ch: raise KeyError(chapter_id)
 next_plan=store.read_json(c.data_dir/'next_chapter_plan.json',default={},expected_type=dict) or {}; next_plan.update({k:v for k,v in ch.items() if v not in (None,'',[],{})}); next_plan['chapter_id']=int(ch.get('chapter_number',ch.get('chapter_id'))); next_plan['planning_source']={'chapter_plan_id':ch.get('chapter_id'),'updated_at':_now()}; store.write_json(c.data_dir/'next_chapter_plan.json',next_plan,backup=True); return next_plan
def list_versions(context=None):
 c=context or get_project_context(); d=_versions(c); return sorted([{'version_id':x.stem,'created_at':datetime.fromtimestamp(x.stat().st_mtime,timezone.utc).isoformat()} for x in d.glob('planning_*.json')] if d.exists() else [],key=lambda x:x['created_at'],reverse=True)
def restore_version(version_id,context=None):
 c=context or get_project_context(); record=DataStore(c).read_json(_versions(c)/f'{version_id}.json',strict=True,expected_type=dict); return save_planning(record['planning'],c,f'restore {version_id}')
