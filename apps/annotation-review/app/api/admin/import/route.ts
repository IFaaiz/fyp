import {env} from 'cloudflare:workers';
import {db,identity,result,failed,requireSameOrigin} from '../../../../lib/database';
export const dynamic='force-dynamic';
function equal(a:string,b:string){let difference=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)difference|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return difference===0;}
export async function POST(request:Request){try{
 requireSameOrigin(request);const secret=String((env as any).IMPORT_KEY||''),supplied=request.headers.get('x-fyp-import-key')||'';
 const serviceImport=secret.length>=64&&equal(secret,supplied);
 if(!serviceImport){const u=await identity();if(u.email.toLowerCase()!==String((env as any).ADMIN_EMAIL||'').toLowerCase())return result({error:'Only the owner can import.'},403);}
 const rows=await request.json();if(!Array.isArray(rows)||rows.length>25)return result({error:'Import at most 25 emails at once.'},400);const statements=[];
 for(const r of rows){if(typeof r.source_id!=='string'||!r.source_id||typeof r.subject!=='string'||typeof r.current_message!=='string'||!Array.isArray(r.authored_ranges)||!Number.isInteger(r.position)||r.position<0||!r.source_sha256||!['calibration_training','blind_agreement','labeler_human_holdout'].includes(r.allocation))return result({error:'Immutable source manifest fields missing or invalid.'},400);
  if(r.current_message.length>60000||r.is_synthetic||r.data_origin==='SYNTHETIC')return result({error:'Only bounded real corpus emails belong in calibration.'},400);
  const n=Array.from(r.current_message).length;if(!r.authored_ranges.length||r.authored_ranges.some((x:any)=>!Number.isInteger(x.start)||!Number.isInteger(x.end)||x.start<0||x.end<=x.start||x.end>n))return result({error:'Invalid authored source range.'},400);
  if(typeof r.common_blind!=='boolean'||(!r.common_blind&&![0,1,2].includes(r.owner_slot)))return result({error:'Reviewer assignment is missing.'},400);
  const old:any=await db().prepare('SELECT sha256,position,allocation,common_blind,owner_slot,subject,body FROM sources WHERE id=?').bind(r.source_id).first();if(old&&(old.sha256!==r.source_sha256||old.body!==r.current_message||old.subject!==r.subject||old.position!==r.position||old.allocation!==r.allocation||old.common_blind!==Number(r.common_blind)||old.owner_slot!==(r.owner_slot??r.position%3)))return result({error:'Existing source bytes or assignment differ.'},409);
  const safe={authored_ranges:r.authored_ranges,thread_context:r.thread_context||'',context_sources:[],data_origin:r.data_origin||'PUBLIC_CORPUS'};
  statements.push(db().prepare(`INSERT OR IGNORE INTO sources(id,position,subject,body,source_json,sha256,allocation,common_blind,owner_slot,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)`).bind(r.source_id,r.position,r.subject,r.current_message,JSON.stringify(safe),r.source_sha256,r.allocation,r.common_blind?1:0,r.owner_slot??r.position%3,new Date().toISOString()));}
 const inserted=statements.length?await db().batch(statements):[];return result({accepted:rows.length,inserted:inserted.reduce((n,x)=>n+(x.meta.changes||0),0)});
 }catch(e){return failed(e);}}


