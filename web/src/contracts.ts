export type Payload = Record<string, unknown>;
export interface Event {event_id:string;run_id:string;seq:number;kind:string;parent:string|null;tool:string|null;step:number|null;payload:Payload;status:string;provenance:string;checkpoint:string|null;capture_complete:boolean;event_digest:string;timestamp:string;}
export interface Outcome {task_correct?:boolean;final_files?:Record<string,string>;result?:Payload;journal?:Payload[];journal_reconciled?:boolean}
export interface Run {driver_version?:string|null;capture_policy?:{mode:string;synthetic:boolean};id:string;name:string;created:string;event_count:number;status:string;provenance:string;parent_id?:string;source_event?:string;label?:string;replay_eligible:boolean;integrity:{valid:boolean;status:string};outcome:Outcome|null}
export function statePresentation(run:Run){
 const virtual=run.driver_version==='document-agent.v1'&&run.capture_policy?.synthetic===true;
 const available=virtual&&!!run.outcome?.final_files&&typeof run.outcome.final_files==='object'&&!Array.isArray(run.outcome.final_files);
 return {heading:run.source_event?'BRANCH / SCRIPTED CONTINUATION':virtual?'RECORDING / VIRTUAL DOCUMENT WORKSPACE':'RECORDING / SDK TOOL EVENTS',tab:virtual?'Virtual filesystem state':'Recorded state',available,stateTitle:available?'Virtual filesystem state':'No workspace snapshot available'};
}
export interface Comparison {original_id:string;branch_id:string;original_outcome:Outcome;branch_outcome:Outcome;source_event:string;source_checkpoint:string;first_observed_divergence:string|null;continuation_changed:boolean;shared_prefix_end:number;state_diff:Payload[];actions:Payload[];limitations:string}
export function validateReplacement(text:string):Payload {
  const p:unknown = JSON.parse(text);
  if (!p || typeof p !== 'object' || Array.isArray(p)) throw new Error('A JSON object is required');
  const v=p as Payload;
  const allowed=['action','target','content','approved','note'];
  if(Object.keys(v).some(k=>!allowed.includes(k))) throw new Error('Unknown ticket field');
  if(!['delete','write','archive','noop'].includes(String(v.action))) throw new Error('action must be delete, write, archive or noop');
  if(typeof v.target!=='string'||!v.target.startsWith('/documents/')||v.target.length>256||v.target.includes('\\')||v.target.includes('\0')||v.target.includes(':')||v.target.split('/').includes('..')) throw new Error('target must stay inside the virtual /documents root');
  for(const k of ['content','note']) if(v[k]!==undefined&&(typeof v[k]!=='string'||(v[k] as string).length>8192)) throw new Error(`${k} must be a string of at most 8192 characters`);
  if(v.approved!==undefined&&typeof v.approved!=='boolean') throw new Error('approved must be boolean');
  return v;
}
export async function api<T>(path:string, body?:unknown):Promise<T>{
  const r=await fetch(`/api${path}`,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await r.json();
  if(!r.ok) throw new Error(value.error?`${value.error.code}: ${value.error.message}`:JSON.stringify(value.detail||value));
  return value as T;
}
