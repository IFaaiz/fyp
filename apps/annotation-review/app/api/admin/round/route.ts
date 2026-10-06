import {db,reviewer,result,failed,requireSameOrigin} from '../../../../lib/database';
import {roundId} from '../../../../lib/round';
export const dynamic='force-dynamic';
export async function POST(request:Request){try{requireSameOrigin(request);const u=await reviewer();if(!u.isAdmin)return result({error:'Only the owner prepares the shared round.'},403);
 const d=db(),existing:any=await d.prepare('SELECT COUNT(*) n FROM calibration_round_sources WHERE round_id=?').bind(roundId).first();
 if(!existing.n){const counts:any=await d.prepare("SELECT SUM(common_blind=1) shared,SUM(allocation='calibration_training' AND common_blind=0) train FROM sources").first();if(counts.shared!==24||counts.train<6)return result({error:'Expected frozen queue of 24 shared emails and at least six eligible TRAIN emails.'},409);
 await d.prepare(`INSERT OR IGNORE INTO calibration_round_sources(round_id,source_id,source_sha256,position,created_at) SELECT ?,id,sha256,position,? FROM sources WHERE common_blind=1 OR id IN (SELECT id FROM sources WHERE allocation='calibration_training' AND common_blind=0 ORDER BY position LIMIT 6)`).bind(roundId,new Date().toISOString()).run();}
 const n:any=await d.prepare('SELECT COUNT(*) n FROM calibration_round_sources WHERE round_id=?').bind(roundId).first();return result({round_id:roundId,count:n.n,message:`Shared first round ready: ${n.n} emails. The first two registered reviewers label all of them independently; a third can join. Source allocations are unchanged.`});
 }catch(e){return failed(e);}}
