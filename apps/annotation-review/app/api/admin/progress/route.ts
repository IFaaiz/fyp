import {reviewer,db,result,failed} from '../../../../lib/database';
export const dynamic='force-dynamic';
export async function GET(){try{const u=await reviewer();if(!u.isAdmin)return result({error:'Only the owner can view study progress.'},403);const x=await db().prepare('SELECT status,COUNT(*) count,SUM(active_ms) active_ms FROM reviews GROUP BY status').all();return result({progress:x.results,gold_annotations:0,blind_answers_hidden:true});}catch(e){return failed(e);}}
