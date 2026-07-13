from __future__ import annotations
import hashlib, re, uuid
from datetime import datetime, timezone
from typing import Any
from core.project_context import ProjectContext
from system.data_store import DataStore
from system.revision_service import RevisionService

def now(): return datetime.now(timezone.utc).isoformat()
def eid(p): return f"{p}_{uuid.uuid4().hex[:16]}"
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
class NarrativeMemoryError(RuntimeError): code="NARRATIVE_MEMORY_ERROR"
class EventNotFound(NarrativeMemoryError): code="NARRATIVE_EVENT_NOT_FOUND"

class NarrativeMemoryService:
 def __init__(self, context: ProjectContext): self.context=context; self.store=DataStore(context)
 def _path(self, chapter:int): return f"data/narrative_memory/events/chapter_{chapter:03d}.json"
 def _meta(self):
  return self.store.read_json('data/narrative_memory/metadata.json',default={'schema_version':'1.0','updated_at':now()},expected_type=dict) or {}
 def _save_meta(self,m): m['updated_at']=now(); self.store.write_json('data/narrative_memory/metadata.json',m)
 def events(self, chapter_id:int|None=None, include_inactive=False):
  paths=[self._path(chapter_id)] if chapter_id else [self.context.relative_path(x) for x in self.context.narrative_events_dir.glob('chapter_*.json')]
  out=[]
  for path in paths:
   data=self.store.read_json(path,default=[],expected_type=list) or []; out += [x for x in data if include_inactive or x.get('active',True)]
  return sorted(out,key=lambda x:(x.get('chapter_id',0),x.get('event_order',0)))
 def extract(self, chapter_id:int):
  canon=RevisionService(self.context).active_canon(chapter_id); text=canon['content']; candidates=[]; order=0
  # Conservative deterministic candidates; all remain unreviewed until a person confirms them.
  for i,line in enumerate([x.strip() for x in text.splitlines() if x.strip()]):
   typ=None; changes=[]; participants=[]
   if any(w in line.lower() for w in ['died', 'dead', 'killed', '\u6b7b\u4ea1', '\u6b7b\u4e86', '\u88ab\u6740']): typ='death'
   elif any(w in line.lower() for w in ['injured', 'wounded', 'hurt', '\u53d7\u4f24', '\u53d7\u4f24']): typ='injury'
   elif any(w in line.lower() for w in ['gave ', 'handed ', 'received ', '\u4ea4\u7ed9', '\u83b7\u5f97', '\u593a\u5f97']): typ='item_transferred'
   elif any(w in line.lower() for w in ['arrived', 'reached', 'entered', '\u62b5\u8fbe', '\u8fdb\u5165', '\u6765\u5230']): typ='arrival'
   elif any(w in line.lower() for w in ['departed', 'left ', 'left.', '\u79bb\u5f00', '\u51fa\u53d1']): typ='departure'
   elif any(w in line.lower() for w in ['learned', 'discovered', 'realized', '\u5f97\u77e5', '\u53d1\u73b0', '\u660e\u767d']): typ='character_knowledge_gain'
   if not typ: continue
   order+=1; candidates.append({'event_id':eid('event'),'project_id':self.context.root.name,'chapter_id':chapter_id,'chapter_number':chapter_id,'canon_version_id':canon['canon_version_id'],'event_order':order,'event_type':typ,'summary':line[:300],'participants':participants,'entities':[],'state_changes':changes,'source':{'paragraph_index':i,'text_excerpt':line[:500],'content_hash':canon['content_hash']},'extraction_method':'rule','confidence':0.55,'confirmation_status':'unreviewed','active':True,'created_at':now(),'invalidated_at':None})
  self.store.write_json(self._path(chapter_id),candidates); self.project(); return candidates
 def confirm(self,event_id:str, decision:str='confirmed', patch:dict[str,Any]|None=None):
  for e in self.events(include_inactive=True):
   if e['event_id']==event_id:
    e.update(patch or {}); e['confirmation_status']=decision; e['confirmed_at']=now(); self._replace_event(e); self.project(); return e
  raise EventNotFound('Event not found.')
 def _replace_event(self,event):
  path=self._path(int(event['chapter_id'])); data=self.store.read_json(path,default=[],expected_type=list) or []; self.store.write_json(path,[event if x.get('event_id')==event['event_id'] else x for x in data])
 def project(self):
  state={'characters':{},'relationships':{},'items':{},'locations':{},'organizations':{},'foreshadowing':{},'world_rules':{},'knowledge':{},'timeline':[],'source_event_ids':[]}
  for e in self.events():
   if e.get('confirmation_status') not in {'confirmed','corrected'}: continue
   state['source_event_ids'].append(e['event_id']); state['timeline'].append({'timeline_id':eid('timeline'),'event_id':e['event_id'],'chapter_id':e['chapter_id'],'time_reference':e.get('time_reference','unknown'),'summary':e['summary']})
   for change in e.get('state_changes',[]): self._apply(state,change,e)
  for key in ['characters','relationships','items','locations','organizations','foreshadowing','world_rules','knowledge']:
   self.store.write_json(f'data/narrative_memory/state/{key}.json',state[key])
  self.store.write_json('data/narrative_memory/timeline.json',state['timeline']); self.store.write_json('data/narrative_memory/state/current.json',state); self.conflicts(); return state
 def _apply(self,s,c,e):
  kind=str(c.get('entity_type','')); ident=str(c.get('entity_id',''))
  if not kind or not ident:return
  bucket=s.get(kind+'s',s.get(kind,{})); bucket.setdefault(ident,{}).update(c.get('patch',{})); bucket[ident]['source_event_ids']=bucket[ident].get('source_event_ids',[])+[e['event_id']]
 def snapshot(self,chapter:int):
  canon=RevisionService(self.context).active_canon(chapter); payload={'chapter_id':chapter,'canon_version_id':canon['canon_version_id'],'created_at':now(),'state':self.project()}; self.store.write_json(f'data/narrative_memory/snapshots/chapter_{chapter:03d}.json',payload); return payload
 def conflicts(self):
  items=self.store.read_json('data/narrative_memory/state/items.json',default={},expected_type=dict) or {}; out=[]
  for k,v in items.items():
   holders=v.get('holders',[]) if isinstance(v,dict) else []
   if len(set(holders))>1: out.append({'conflict_id':eid('conflict'),'type':'item_holder','entity_id':k,'severity':'blocking','status':'open','created_at':now(),'sources':v.get('source_event_ids',[])})
  self.store.write_json('data/narrative_memory/conflicts/conflicts.json',out); return out
 def invalidate_from(self, chapter:int):
  for e in self.events(include_inactive=True):
   if int(e.get('chapter_id',0)) >= chapter and e.get('active',True):
    e['active']=False; e['invalidated_at']=now(); self._replace_event(e)
  for path in self.context.narrative_snapshots_dir.glob('chapter_*.json'):
   try:
    n=int(path.stem.split('_')[-1])
    if n>=chapter:
     snap=self.store.read_json(path,default={},expected_type=dict) or {}; snap['status']='stale'; self.store.write_json(path,snap)
   except ValueError: pass
  self.project(); return {'invalidated_from_chapter':chapter}
 def set_override(self, kind:str, value:Any):
  if kind not in {'pins','exclusions'}: raise NarrativeMemoryError('INVALID_OVERRIDE')
  path=f'data/narrative_memory/overrides/{kind}.json'; values=self.store.read_json(path,default=[],expected_type=list) or []
  if value not in values: values.append(value)
  self.store.write_json(path,values); return values
 def overview(self):
  cur=self.store.read_json('data/narrative_memory/state/current.json',default={},expected_type=dict) or {}; return {'events':len(self.events()),'confirmed_events':sum(x.get('confirmation_status') in {'confirmed','corrected'} for x in self.events()),'timeline':len(cur.get('timeline',[])),'conflicts':len(self.conflicts()),'state':cur}
 def preview(self,chapter_id:int):
  cur=self.store.read_json('data/narrative_memory/state/current.json',default={},expected_type=dict) or {}; pins=self.store.read_json('data/narrative_memory/overrides/pins.json',default=[],expected_type=list) or []; excludes=self.store.read_json('data/narrative_memory/overrides/exclusions.json',default=[],expected_type=list) or []
  selected=[{'source_type':'pinned','value':x,'reason':'manual pin'} for x in pins if x not in excludes]; selected += [{'source_type':'state','value':{'characters':cur.get('characters',{}),'items':cur.get('items',{}),'timeline_tail':cur.get('timeline',[])[-5:]},'reason':'current confirmed canon projection'}]
  record={'context_id':eid('context'),'chapter_id':chapter_id,'created_at':now(),'selected':selected,'excluded':excludes}; hist=self.store.read_json('data/narrative_memory/retrieval/retrieval_history.json',default=[],expected_type=list) or []; self.store.write_json('data/narrative_memory/retrieval/retrieval_history.json',(hist+[record])[-200:]); return record
 def preflight(self,chapter_id:int):
  conflicts=self.conflicts(); return {'chapter_id':chapter_id,'status':'blocked' if any(x['severity']=='blocking' for x in conflicts) else 'pass','blocking':[x for x in conflicts if x['severity']=='blocking'],'warnings':[]}
