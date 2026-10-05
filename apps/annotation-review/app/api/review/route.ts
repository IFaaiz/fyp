import {db,reviewer,result,failed,requireSameOrigin} from '../../../lib/database';
import {validateAnnotation} from '../../../lib/annotation';
export const dynamic='force-dynamic';
export async function POST(request:Request){try{
 requireSameOrigin(request);const u=await reviewer();const b:any=await request.json();if(!['draft','submitted'].includes(b.status))return result({error:'Invalid review state.'},400);
 const s:any=await db().prepare('SELECT * FROM sources WHERE id=? AND (common_blind=1 OR owner_slot=?)').bind(b.source_id,u.slot).first();if(!s)return result({error:'Email is not assigned to you.'},403);
 const source={...JSON.parse(s.source_json),source_id:s.id,subject:s.subject,current_message:s.body};const a=b.annotation;if(!a||a.current_source_id!==s.id)return result({error:'Review belongs to another email.'},400);
 const now=new Date().toISOString();a.provenance={data_origin:source.data_origin||'PUBLIC_CORPUS',source_reference:s.id,synthetic_case_id:null,annotation_tier:'UNSET',annotation_mode:'BLIND_HUMAN',annotator_id:u.userId,annotated_at:now,blind_prelabels_shown:false,human_review:null,ai_assistance:null};
 if(b.status==='submitted'){if(b.human_attestation!==true)return result({error:'Confirm that you read and reviewed the source.'},400);const errors=validateAnnotation(a,source);if(errors.length)return result({error:'Correct these fields before submitting.',errors},422);}
 const payload=JSON.stringify(a);if(payload.length>150000)return result({error:'Review is too large.'},413);
 const old:any=await db().prepare('SELECT revision,status FROM reviews WHERE source_id=? AND user_id=?').bind(s.id,u.userId).first();if(old?.status==='submitted')return result({error:'Submitted blind reviews are frozen. Contact the owner for corrections.'},409);
 if(Number(b.revision)!==Number(old?.revision||0))return result({error:'Another tab saved a newer draft. Reload before editing.'},409);
 const revision=Number(old?.revision||0)+1,ms=Math.max(0,Math.min(120000,Number(b.active_ms)||0));
 const write=old?db().prepare(`UPDATE reviews SET annotation_json=?,status=?,revision=?,active_ms=active_ms+?,updated_at=?,submitted_at=? WHERE source_id=? AND user_id=? AND revision=? AND status='draft'`).bind(payload,b.status,revision,ms,now,b.status==='submitted'?now:null,s.id,u.userId,old.revision):db().prepare(`INSERT OR IGNORE INTO reviews(source_id,user_id,annotation_json,status,revision,active_ms,created_at,updated_at,submitted_at) VALUES(?,?,?,?,?,?,?,?,?)`).bind(s.id,u.userId,payload,b.status,revision,ms,now,now,b.status==='submitted'?now:null);
 const log=db().prepare(`INSERT INTO review_revisions(id,source_id,user_id,revision,annotation_json,status,created_at) SELECT ?,source_id,user_id,revision,annotation_json,status,updated_at FROM reviews WHERE source_id=? AND user_id=? AND revision=? AND updated_at=? AND changes()=1`).bind(crypto.randomUUID(),s.id,u.userId,revision,now);
 const writes=await db().batch([write,log]);if(!writes[0].meta.changes)return result({error:'A concurrent save won. Reload your draft.'},409);
 return result({saved:true,revision,status:b.status,saved_at:now});
 }catch(e){return failed(e);}}


