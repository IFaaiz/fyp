import {db,reviewer,result,failed} from '../../../lib/database';
export const dynamic='force-dynamic';
export async function GET(){try{const u=await reviewer();const x=await db().prepare(`SELECT s.id,s.position,s.subject,COALESCE(r.status,'new') status,COALESCE(r.revision,0) revision FROM sources s LEFT JOIN reviews r ON r.source_id=s.id AND r.user_id=? WHERE s.common_blind=1 OR s.owner_slot=? ORDER BY s.position`).bind(u.userId,u.slot).all();return result({user:{name:u.displayName,email:u.email,isAdmin:u.isAdmin},queue:x.results});}catch(e){return failed(e);}}
