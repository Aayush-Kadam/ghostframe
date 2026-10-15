import {describe,it} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source=fs.readFileSync(new URL('../src/contracts.ts',import.meta.url),'utf8');
const javascript=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const {validateReplacement,statePresentation}=await import('data:text/javascript;base64,'+Buffer.from(javascript).toString('base64'));
describe('production ticket contract',()=>{
 it('accepts a schema-valid virtual ticket',()=>assert.equal(validateReplacement('{"action":"delete","target":"/documents/draft.txt"}').action,'delete'));
 for(const text of ['{}','null','[]','{"action":"shell","target":"/documents/a"}','{"action":"delete","target":"/etc/passwd"}','{"action":"delete","target":"/documents/../secret"}','{"action":"noop","target":"/documents/a","approved":"yes"}','{"action":"delete","target":"/documents/a","extra":2}']){
  it(`rejects ${text}`,()=>assert.throws(()=>validateReplacement(text)));
 }
});

describe('state provenance labels',()=>{
 const sdk={source_event:null,driver_version:null,capture_policy:{mode:'metadata_only',synthetic:false},outcome:{capture:'DISABLED'}};
 it('generic SDK trace does not claim virtual workspace',()=>{const p=statePresentation(sdk);assert.equal(p.heading,'RECORDING / SDK TOOL EVENTS');assert.equal(p.available,false);assert.equal(p.stateTitle,'No workspace snapshot available')});
 it('missing SDK snapshot is not inferred from payload-shaped fields',()=>assert.equal(statePresentation({...sdk,outcome:{final_files:{'/documents/x':'value'}}}).available,false));
 it('supported synthetic document snapshot is virtual state',()=>{const p=statePresentation({...sdk,driver_version:'document-agent.v1',capture_policy:{synthetic:true},outcome:{final_files:{'/documents/x':'value'}}});assert.equal(p.available,true);assert.equal(p.tab,'Virtual filesystem state')});
 it('partial or missing document snapshot is explicit',()=>assert.equal(statePresentation({...sdk,driver_version:'document-agent.v1',capture_policy:{synthetic:true},outcome:null}).stateTitle,'No workspace snapshot available'));
 it('branch retains scripted continuation provenance',()=>assert.equal(statePresentation({...sdk,source_event:'owned-event'}).heading,'BRANCH / SCRIPTED CONTINUATION'));
});
