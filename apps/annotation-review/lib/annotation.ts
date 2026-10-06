import schemaFile from './schema.json';
export const schema:any=schemaFile;
export const rules:any=schema['x-semantics'];
export const legacyDerivedLabelVersion:string=schema.properties?.derived_label_version?.enum?.find((version:string)=>version!==rules.derived_label_version)||'fyp-derived-labels-1.0';
export const eventStates:Record<string,string[]>={MEETING:['proposed','scheduled','rescheduled','cancelled','completed'],ACTION:['requested','assigned','committed','completed','cancelled'],DOCUMENT:['requested','expected','submitted','delivered','missing','reviewed'],APPROVAL:['requested','granted','rejected','withheld','conditional'],STATUS:['progress','completed','blocker','decision','work_state_change']};
export const roleNames:Record<string,string>={EVENT_ANCHOR:'Event words',ACTION:'Action to perform',DOCUMENT:'Document',RESPONSIBLE_PARTY:'Responsible person/team',CONTRIBUTOR:'Contributing department/team',RECIPIENT:'Recipient',MENTION_ONLY:'Mentioned person only',PARTICIPANT:'Meeting participant',MEETING_NAME:'Meeting name',LOCATION:'Meeting location',MEETING_DATE:'Meeting date',MEETING_TIME:'Meeting time',DUE_DATE:'Due date',DUE_TIME:'Due time',OCCURRENCE_DATE:'Other event date',OCCURRENCE_TIME:'Other event time',APPROVAL_TARGET:'What is approved',APPROVER:'Approver',STATUS:'Status words',AGENDA:'Meeting agenda',PROJECT:'Project name'};
export const cp=(s:string)=>Array.from(s);
export function blank(source:any){return {schema_version:'fyp-structured-v1',derived_label_version:rules.derived_label_version,record_id:source.source_id,current_source_id:source.source_id,scope:{value:'UNCERTAIN',evidence_span_ids:[],reason:''},spans:[],events:[],event_span_links:[],event_relations:[],needs_review:false,review_reasons:[],provenance:{data_origin:source.data_origin,source_reference:source.source_id,synthetic_case_id:null,annotation_tier:'UNSET',annotation_mode:'UNANNOTATED',annotator_id:null,annotated_at:null,blind_prelabels_shown:null,human_review:null,ai_assistance:null}};}
export const labelOrder:string[]=Object.keys(rules.derived_label_rules);
export const derivedLabelHelp:Record<string,string>={
 MEETING:'A supported project meeting event.',
 DEADLINE:'A due date or time linked to a task or document.',
 REPORT_REQUEST:'A project deliverable linked to a document request.',
 DEPARTMENTAL_INPUT:'A department linked as a contributor to project work.',
 ACTION_REQUEST:'A supported operational task that is requested or assigned.',
 FOLLOW_UP:'A current event linked to a verified earlier event.',
 APPROVAL:'A supported formal approval event.',
 GENERAL_UPDATE:'A project update, or a task or document completed, cancelled, submitted, delivered, missing or reviewed.',
 NON_PROJECT:'A supported decision that this message is outside project work.'
};
export function deriveLabels(a:any):string[]{
 if(!a||a.schema_version!=='fyp-structured-v1'||a.needs_review!==false||!Array.isArray(a.review_reasons)||a.review_reasons.length)return [];
 const derivationVersion=a.derived_label_version||'fyp-derived-labels-1.0';if(!['fyp-derived-labels-1.0',rules.derived_label_version].includes(derivationVersion))return [];
 if(a.scope?.value==='NON_PROJECT')return a.events?.length||a.event_span_links?.length||a.event_relations?.length?[]:['NON_PROJECT'];
 if(a.scope?.value!=='PROJECT'||![a.events,a.event_span_links,a.event_relations,a.spans].every(Array.isArray))return [];
 if([...a.events,...a.event_span_links,...a.event_relations].some((x:any)=>x?.certainty!=='SUPPORTED'))return [];
 const spans=new Map<string,any>(a.spans.map((s:any)=>[s.id,s])),events=new Map<string,any>(a.events.map((e:any)=>[e.id,e])),byEvent=new Map<string,any[]>();
 for(const l of a.event_span_links){if(!events.has(l.event_id)||!spans.has(l.span_id))return [];byEvent.set(l.event_id,[...(byEvent.get(l.event_id)||[]),l]);}
 const emitted=new Set<string>();
 for(const e of a.events){const links=byEvent.get(e.id)||[],roles=new Set(links.map(l=>l.role));if(e.kind==='MEETING')emitted.add('MEETING');
  if(['ACTION','DOCUMENT'].includes(e.kind)&&['DUE_DATE','DUE_TIME'].some(r=>roles.has(r)))emitted.add('DEADLINE');
  if(e.kind==='DOCUMENT'&&e.state==='requested'&&e.document_class==='PROJECT_DELIVERABLE')emitted.add('REPORT_REQUEST');
  if(derivationVersion===rules.derived_label_version&&e.kind==='DOCUMENT'&&['submitted','delivered','missing','reviewed'].includes(e.state))emitted.add('GENERAL_UPDATE');
  if(e.kind==='ACTION'&&e.action_class==='OPERATIONAL'&&['requested','assigned'].includes(e.state))emitted.add('ACTION_REQUEST');
  if(derivationVersion===rules.derived_label_version&&e.kind==='ACTION'&&['completed','cancelled'].includes(e.state))emitted.add('GENERAL_UPDATE');
  if(e.kind==='ACTION'&&e.action_class==='DEPARTMENTAL_CONTRIBUTION'&&links.some(l=>l.role==='CONTRIBUTOR'&&spans.get(l.span_id)?.type==='ACTOR'&&spans.get(l.span_id)?.actor_kind==='DEPARTMENT'))emitted.add('DEPARTMENTAL_INPUT');
  if(e.kind==='APPROVAL')emitted.add('APPROVAL');if(e.kind==='STATUS')emitted.add('GENERAL_UPDATE');
 }
 for(const r of a.event_relations)if(r.kind==='FOLLOW_UP_OF'&&events.has(r.source_event_id)&&r.target!==null)emitted.add('FOLLOW_UP');
 return labelOrder.filter((label:string)=>emitted.has(label));
}
function trustedProvenance(source:any,mode:string,annotatorId:string|null=null,annotatedAt:string|null=null){
 const origin=source.data_origin||'UNKNOWN',synthetic=origin==='SYNTHETIC',submitted=mode==='BLIND_HUMAN';
 return {
  data_origin:origin,
  source_reference:['REAL_EMAIL','PUBLIC_CORPUS'].includes(origin)?source.source_id:null,
  synthetic_case_id:synthetic?(source.synthetic_case_id||source.source_id):null,
  annotation_tier:submitted&&synthetic?'SYNTHETIC':'UNSET',
  annotation_mode:mode,
  annotator_id:submitted?annotatorId:null,
  annotated_at:submitted?annotatedAt:null,
  blind_prelabels_shown:submitted?false:null,
  human_review:null,
  ai_assistance:null
 };
}
export function stampUnannotatedDraft(input:any,source:any,derivedLabelVersion:string=rules.derived_label_version){
 const a=structuredClone(input);
 a.derived_label_version=derivedLabelVersion;
 a.provenance=trustedProvenance(source,'UNANNOTATED');
 return a;
}
export function stampBlindHumanSubmission(input:any,source:any,annotatorId:string,annotatedAt:string,derivedLabelVersion:string=rules.derived_label_version){
 const a=structuredClone(input);
 a.derived_label_version=derivedLabelVersion;
 a.provenance=trustedProvenance(source,'BLIND_HUMAN',annotatorId,annotatedAt);
 return a;
}
function provenanceErrors(p:any):string[]{
 const e:string[]=[],origin=p.data_origin,tier=p.annotation_tier,mode=p.annotation_mode,ai=p.ai_assistance,review=p.human_review,annotator=p.annotator_id,at=p.annotated_at,blind=p.blind_prelabels_shown;
 if(origin==='SYNTHETIC'){if(tier!=='SYNTHETIC')e.push('Synthetic examples must keep SYNTHETIC provenance.');if(!p.synthetic_case_id)e.push('Synthetic examples need a case ID.');}
 else if(p.synthetic_case_id!==null)e.push('Only synthetic examples may have a synthetic case ID.');
 if(['REAL_EMAIL','PUBLIC_CORPUS'].includes(origin)&&!String(p.source_reference||'').trim())e.push('Real and public messages need a source reference.');
 if(tier==='GOLD'){if(!['REAL_EMAIL','PUBLIC_CORPUS'].includes(origin))e.push('GOLD requires a real or public message.');if(!['BLIND_HUMAN','AI_ASSISTED_HUMAN'].includes(mode))e.push('GOLD requires human annotation.');if(!String(annotator||'').trim()||!at)e.push('GOLD needs annotator identity and annotation time.');if(!review)e.push('GOLD needs a separate human review.');else if(!String(review.reviewer_id||'').trim()||!review.reviewed_at)e.push('GOLD review needs reviewer identity and time.');else if(review.decision==='rejected')e.push('A rejected annotation cannot be GOLD.');}
 if(mode==='BLIND_HUMAN'){if(!String(annotator||'').trim()||!at)e.push('Blind human annotation needs annotator identity and time.');if(blind!==false)e.push('Blind human annotation must record that no prelabels were shown.');if(ai!==null)e.push('Blind human annotation cannot include AI assistance.');}
 else if(mode==='AI_ASSISTED_HUMAN'){if(!String(annotator||'').trim()||!at)e.push('AI-assisted annotation needs annotator identity and time.');if(blind!==true)e.push('AI-assisted annotation must record that prelabels were shown.');if(!ai||!['accepted','modified','rejected'].includes(ai.human_disposition))e.push('AI-assisted annotation needs model details and the human decision.');}
 else if(mode==='AI_ONLY'){if(!['SILVER','SYNTHETIC'].includes(tier))e.push('AI-only annotation must stay SILVER or SYNTHETIC.');if(!ai)e.push('AI-only annotation needs model and run details.');if(review!==null||annotator!==null||at!==null||blind!==null)e.push('AI-only annotation cannot claim human review or presentation.');}
 else if(mode==='RULE_BASED'){if(tier!=='SILVER')e.push('Rule-based annotations must stay SILVER.');if(ai!==null)e.push('Rule-based annotations cannot claim model assistance.');}
 else if(mode==='UNANNOTATED'){if(tier!=='UNSET'||annotator!==null||at!==null)e.push('Unannotated records must stay UNSET and have no annotator or annotation time.');if(review!==null||ai!==null||blind!==null)e.push('Unannotated records cannot claim human review, AI help or blind work.');}
 else if(mode==='SYNTHETIC_GENERATION'&&(origin!=='SYNTHETIC'||tier!=='SYNTHETIC'))e.push('Synthetic generation must remain SYNTHETIC.');
 return e;
}
function structural(v:any,s:any,p='$'):string[]{
 if(s===true)return [];if(s===false)return [p+' is forbidden'];let e:string[]=[];
 if(s.$ref)e.push(...structural(v,s.$ref.split('/').slice(1).reduce((a:any,k:string)=>a[k],schema),p));
 if('const'in s&&JSON.stringify(v)!==JSON.stringify(s.const))e.push(p+' has an invalid value');
 if(s.enum&&!s.enum.some((x:any)=>JSON.stringify(x)===JSON.stringify(v)))e.push(p+' has an invalid choice');
 if(s.type){const ts=Array.isArray(s.type)?s.type:[s.type];if(!ts.some((t:string)=>t==='null'?v===null:t==='array'?Array.isArray(v):t==='object'?v!==null&&typeof v==='object'&&!Array.isArray(v):t==='integer'?Number.isInteger(v):typeof v===t))return [...e,p+' has an invalid type'];}
 if(typeof v==='string'){if(s.minLength&&cp(v).length<s.minLength)e.push(p+' is required');if(s.format==='date-time'&&!/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(v))e.push(p+' needs an ISO timestamp');}
 if(typeof v==='number'&&s.minimum!==undefined&&v<s.minimum)e.push(p+' is below the minimum');
 if(Array.isArray(v)){if(s.minItems!==undefined&&v.length<s.minItems)e.push(p+' needs evidence');if(s.maxItems!==undefined&&v.length>s.maxItems)e.push(p+' has too many items');if(s.uniqueItems&&new Set(v.map(x=>JSON.stringify(x))).size!==v.length)e.push(p+' contains duplicates');if(s.items)v.forEach((x,i)=>e.push(...structural(x,s.items,`${p}[${i}]`)));}
 if(v!==null&&typeof v==='object'&&!Array.isArray(v)){for(const k of s.required||[])if(!(k in v))e.push(p+'.'+k+' is required');for(const [k,x]of Object.entries(v)){if(s.properties?.[k])e.push(...structural(x,s.properties[k],p+'.'+k));else if(s.additionalProperties===false)e.push(p+'.'+k+' is not allowed');}}
 if(s.allOf)for(const x of s.allOf)e.push(...structural(v,x,p));
 if(s.oneOf&&s.oneOf.filter((x:any)=>structural(v,x,p).length===0).length!==1)e.push(p+' does not match exactly one allowed record');
 if(s.anyOf&&!s.anyOf.some((x:any)=>structural(v,x,p).length===0))e.push(p+' does not match an allowed value');
 if(s.not&&structural(v,s.not,p).length===0)e.push(p+' has a forbidden combination');
 if(s.if){const branch=structural(v,s.if,p).length===0?s.then:s.else;if(branch)e.push(...structural(v,branch,p));}return e;
}
export function validateAnnotation(a:any,source:any):string[]{
 let errors=structural(a,schema);if(errors.length)return errors.slice(0,20);const fail=(s:string)=>errors.push(s);
 if(a.current_source_id!==source.source_id)fail('Wrong current email.');
 const sources=new Map<string,any>([[source.source_id,source],...(source.context_sources||[]).map((x:any)=>[x.source_id,x])]);
 const spans=new Map<string,any>(),events=new Map<string,any>();const allIds=new Set<string>();for(const x of [...a.spans,...a.events,...a.event_relations]){if(allIds.has(x.id))fail('Evidence/event/relation IDs must be globally unique.');allIds.add(x.id);}const coords=new Set<string>();
 for(const s of a.spans){if(spans.has(s.id))fail('Duplicate evidence ID.');spans.set(s.id,s);const src=sources.get(s.source_id);const text=src?.[s.field];if(typeof text!=='string'||s.end<=s.start||s.end>cp(text).length||cp(text).slice(s.start,s.end).join('')!==s.text)fail(`Evidence ${s.id} must exactly match its source.`);const key=JSON.stringify([s.source_id,s.field,s.type,s.start,s.end]);if(coords.has(key))fail('Share existing evidence instead of duplicating it.');coords.add(key);if(s.source_id!==source.source_id)fail('Evidence must belong to the current email.');if(s.field==='current_message'&&!(src?.authored_ranges||[]).some((r:any)=>s.start>=r.start&&s.end<=r.end))fail(`Evidence ${s.id} is outside the authored message.`);}
 for(const id of a.scope.evidence_span_ids){const s=spans.get(id);if(!s||s.source_id!==source.source_id)fail('Project relevance needs evidence from this email.');}
 for(const e of a.events){if(events.has(e.id))fail('Duplicate event ID.');events.set(e.id,e);}
 const linkKeys=new Set();for(const l of a.event_span_links){const e=events.get(l.event_id),s=spans.get(l.span_id);if(!e||!s){fail('An evidence link has no matching event/span.');continue;}if(!rules.role_types[l.role]?.includes(s.type)||!rules.role_event_kinds[l.role]?.includes(e.kind))fail(`${roleNames[l.role]||l.role} is incompatible with this event/evidence.`);if(rules.role_actor_kind?.[l.role]&&!rules.role_actor_kind[l.role].includes(s.actor_kind))fail('This role requires a department actor.');if(l.role==='EVENT_ANCHOR'&&(s.source_id!==source.source_id||s.field!=='current_message'))fail('Event words must be in the current authored message.');const k=JSON.stringify([l.event_id,l.span_id,l.role]);if(linkKeys.has(k))fail('Duplicate evidence link.');linkKeys.add(k);}
 for(const e of a.events){const links=a.event_span_links.filter((l:any)=>l.event_id===e.id);for(const role of rules.required_event_roles[e.kind])if(!links.some((l:any)=>l.role===role))fail(`${e.kind} ${e.id} needs ${roleNames[role]}.`);}
 const relationIds=new Set(),relationKeys=new Set();for(const r of a.event_relations){if(relationIds.has(r.id))fail('Duplicate relation ID.');relationIds.add(r.id);if(!events.has(r.source_event_id))fail('Relation has no current event.');for(const id of r.evidence_span_ids){const s=spans.get(id);if(!s||s.source_id!==source.source_id||s.field!=='current_message')fail('Thread relation needs current authored evidence.');}if(!a.event_span_links.some((l:any)=>l.event_id===r.source_event_id&&l.role==='EVENT_ANCHOR'&&r.evidence_span_ids.includes(l.span_id)))fail('Thread relation evidence must include its current event words.');if(r.target?.source_id===source.source_id)fail('Thread target must be an earlier source.');if(r.target&&!sources.has(r.target.source_id))fail('Prior source is absent.');if(r.target){const prior=(source.context_annotations||[]).find((x:any)=>x.current_source_id===r.target.source_id)?.events?.find((e:any)=>e.id===r.target.event_id);if(!prior)fail('Prior event target has not been independently resolved.');else if(r.kind==='SUPERSEDES'&&prior.kind!==events.get(r.source_event_id)?.kind)fail('A superseding event must replace a prior event of the same kind.');const key=JSON.stringify([r.source_event_id,r.kind,r.target.source_id,r.target.event_id]);if(relationKeys.has(key))fail('Share an existing relation instead of duplicating it.');relationKeys.add(key);}}
 for(const message of provenanceErrors(a.provenance))fail(message);
 if(a.scope.value==='NON_PROJECT'&&(a.events.length||a.event_span_links.length||a.event_relations.length))fail('Not project related must have no project events or relations.');
 const uncertain=a.scope.value==='UNCERTAIN'||a.events.some((e:any)=>e.certainty==='UNCERTAIN'||rules.review_classes.action_class.includes(e.action_class)||rules.review_classes.document_class.includes(e.document_class))||a.event_span_links.some((l:any)=>l.certainty==='UNCERTAIN')||a.event_relations.some((r:any)=>r.certainty==='UNCERTAIN'||!r.target);
 if(uncertain&&!a.needs_review)fail('Uncertainty or unresolved prior events require another review.');if(a.needs_review&&!a.review_reasons.length)fail('Explain what needs another review.');if(!a.needs_review&&a.review_reasons.length)fail('Clear review notes or select Needs another review.');return [...new Set(errors)].slice(0,20);
}
