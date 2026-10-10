import {db,reviewer,result,failed,requireSameOrigin} from '../../../lib/database';
import {prepareReview} from '../../../lib/review-format';
import {assignedSQL} from '../../../lib/round';
import {directVersion} from '../../../lib/direct-annotation';
export const dynamic='force-dynamic';
export async function POST(request:Request){try{
 requireSameOrigin(request);const u=await reviewer();const b:any=await request.json();if(!['draft','submitted'].includes(b.status))return result({error:'Invalid review state.'},400);
 const s:any=await db().prepare(`SELECT s.* FROM sources s WHERE s.id=? AND ${assignedSQL}`).bind(b.source_id,u.slot).first();if(!s)return result({error:'Email is not assigned to you.'},403);
 const source={...JSON.parse(s.source_json),source_id:s.id,subject:s.subject,current_message:s.body};let a=b.annotation;if(!a||a.current_source_id!==s.id)return result({error:'Review belongs to another email.'},400);
 if(a.schema_version==='fyp-direct-label-v1')return result({error:'The saved v1 draft is preserved. Reload to start a separate v1.1 review; old direct records cannot be changed by this build.'},409);
 if(!['fyp-structured-v1',directVersion].includes(a.schema_version))return result({error:'Unsupported annotation schema. Reload the current form.'},409);
 const table=a.schema_version==='fyp-structured-v1'?'reviews':'direct_label_reviews',logTable=table==='reviews'?'review_revisions':'direct_label_review_revisions';
 const old:any=await db().prepare(`SELECT revision,status,annotation_json FROM ${table} WHERE source_id=? AND user_id=?`).bind(s.id,u.userId).first();if(old?.status==='submitted')return result({error:'Submitted blind reviews are frozen. Contact the owner for corrections.'},409);
 if(Number(b.revision)!==Number(old?.revision||0))return result({error:'Another tab saved a newer draft. Reload before editing.'},409);
 const prior=old?.annotation_json?JSON.parse(old.annotation_json):null;
 const now=new Date().toISOString();
 if(b.status==='submitted'&&b.human_attestation!==true)return result({error:'Confirm that you independently reviewed the source.'},400);
 const prepared=prepareReview(a,source,prior,b.status,u.userId,now);a=prepared.annotation;if(prepared.errors.length)return result({error:'Correct these fields before submitting.',errors:prepared.errors},422);
 const payload=JSON.stringify(a);if(payload.length>150000)return result({error:'Review is too large.'},413);
 const revision=Number(old?.revision||0)+1,ms=Math.max(0,Math.min(120000,Number(b.active_ms)||0));
 const write=old?db().prepare(`UPDATE ${table} SET annotation_json=?,status=?,revision=?,active_ms=active_ms+?,updated_at=?,submitted_at=? WHERE source_id=? AND user_id=? AND revision=? AND status='draft'`).bind(payload,b.status,revision,ms,now,b.status==='submitted'?now:null,s.id,u.userId,old.revision):db().prepare(`INSERT OR IGNORE INTO ${table}(source_id,user_id,annotation_json,status,revision,active_ms,created_at,updated_at,submitted_at) VALUES(?,?,?,?,?,?,?,?,?)`).bind(s.id,u.userId,payload,b.status,revision,ms,now,now,b.status==='submitted'?now:null);
 const log=db().prepare(`INSERT INTO ${logTable}(id,source_id,user_id,revision,annotation_json,status,created_at) SELECT ?,source_id,user_id,revision,annotation_json,status,updated_at FROM ${table} WHERE source_id=? AND user_id=? AND revision=? AND updated_at=? AND changes()=1`).bind(crypto.randomUUID(),s.id,u.userId,revision,now);
 const writes=await db().batch([write,log]);if(!writes[0].meta.changes)return result({error:'A concurrent save won. Reload your draft.'},409);
 return result({saved:true,revision,status:b.status,saved_at:now});
 }catch(e){return failed(e);}}


