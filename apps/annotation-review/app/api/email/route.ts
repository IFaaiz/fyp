import {db,reviewer,result,failed} from '../../../lib/database';
import {assignedSQL} from '../../../lib/round';
export const dynamic='force-dynamic';
export async function GET(request:Request){try{
 const u=await reviewer(),id=new URL(request.url).searchParams.get('id');const s:any=await db().prepare(`SELECT s.* FROM sources s WHERE s.id=? AND ${assignedSQL}`).bind(id,u.slot).first();if(!s)return result({error:'Email is not assigned to you.'},404);
 const legacy=new URL(request.url).searchParams.get('format')==='legacy',table=legacy?'reviews':'direct_reviews';
 const r:any=await db().prepare(`SELECT annotation_json,status,revision FROM ${table} WHERE source_id=? AND user_id=?`).bind(id,u.userId).first();const source=JSON.parse(s.source_json);
 const old:any=legacy?null:await db().prepare('SELECT status FROM reviews WHERE source_id=? AND user_id=?').bind(id,u.userId).first();
 return result({source:{source_id:s.id,source_sha256:s.sha256,legacy_review_available:!!old,subject:s.subject,current_message:s.body,authored_ranges:source.authored_ranges,thread_context:source.thread_context||'',data_origin:source.data_origin||'PUBLIC_CORPUS',context_sources:source.context_sources||[],context_annotations:[]},annotation:r?JSON.parse(r.annotation_json):null,status:r?.status||'new',revision:r?.revision||0});
 }catch(e){return failed(e);}}
