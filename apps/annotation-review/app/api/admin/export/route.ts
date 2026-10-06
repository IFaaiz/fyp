import {env} from 'cloudflare:workers';
import {db,identity,result,failed} from '../../../../lib/database';
import {roundId} from '../../../../lib/round';
export const dynamic='force-dynamic';
export async function GET(){try{
 const u=await identity();if(u.email.toLowerCase()!==String((env as any).ADMIN_EMAIL||'').toLowerCase())return result({error:'Only the owner can export the completed blind round.'},403);
 const d=db(),total:any=await d.prepare(`SELECT COUNT(*) n,SUM(CASE WHEN s.id IS NULL OR cr.source_sha256<>s.sha256 OR s.allocation='labeler_human_holdout' THEN 1 ELSE 0 END) invalid FROM calibration_round_sources cr LEFT JOIN sources s ON s.id=cr.source_id WHERE cr.round_id=?`).bind(roundId).first();
 if(total.invalid||total.n<25||total.n>30)return result({error:'Prepare the first 25–30-email round before export.'},409);
 const counts=await d.prepare(`SELECT p.user_id,p.display_name,p.slot,COUNT(r.source_id) submitted FROM reviewers p LEFT JOIN direct_reviews r ON r.user_id=p.user_id AND r.status='submitted' AND r.source_id IN (SELECT source_id FROM calibration_round_sources WHERE round_id=?) GROUP BY p.user_id,p.slot ORDER BY p.slot`).bind(roundId).all();
 const people:any[]=counts.results;
 if(!people.some(p=>p.slot===0&&p.submitted===total.n)||!people.some(p=>p.slot===1&&p.submitted===total.n))return result({error:'Export unlocks after the first two registered reviewers independently submit every first-round email. Peer answers remain hidden.'},409);
 const selected=people.filter(p=>p.submitted===total.n),ids=selected.map(p=>p.user_id),placeholders=ids.map(()=>'?').join(',');
 const sources=await d.prepare('SELECT s.id source_id,s.subject,s.body current_message,s.source_json,s.allocation,s.sha256 source_sha256,cr.position FROM sources s JOIN calibration_round_sources cr ON cr.source_id=s.id AND cr.source_sha256=s.sha256 WHERE cr.round_id=? ORDER BY cr.position').bind(roundId).all();
 const reviews=await d.prepare(`SELECT source_id,user_id,annotation_json,status,revision,active_ms,created_at,updated_at,submitted_at FROM direct_reviews WHERE status='submitted' AND source_id IN (SELECT source_id FROM calibration_round_sources WHERE round_id=?) AND user_id IN (${placeholders})`).bind(roundId,...ids).all();
 return result({schema_version:'fyp-calibration-export-v2',round_id:roundId,exported_at:new Date().toISOString(),annotation_tier:'UNSET',gold_count:0,purpose:'Private direct-label comparison and later adjudication. Legacy records retain their format. Sealed holdout omitted.',sources:sources.results.map((s:any)=>{const {source_json,...rest}=s;return {...JSON.parse(source_json),...rest};}),reviewers:selected.map(({submitted,...p})=>p),reviews:reviews.results});
 }catch(e){return failed(e);}}
