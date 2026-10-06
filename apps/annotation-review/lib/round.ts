export const roundId='fyp-direct-round-1';
// This additive assignment overlay preserves every original source allocation.
export const roundAssignedSQL="EXISTS (SELECT 1 FROM calibration_round_sources cr WHERE cr.round_id='fyp-direct-round-1' AND cr.source_id=s.id AND cr.source_sha256=s.sha256)";
export const assignedSQL=`(s.common_blind=1 OR s.owner_slot=? OR ${roundAssignedSQL})`;
export async function prepareRound(d:D1Database){
 const existing:any=await d.prepare('SELECT COUNT(*) n FROM calibration_round_sources WHERE round_id=?').bind(roundId).first();if(existing.n)return existing.n;
 const counts:any=await d.prepare("SELECT SUM(common_blind=1) shared,SUM(allocation='calibration_training' AND common_blind=0) train FROM sources").first();if(counts.shared!==24||counts.train<6)return 0;
 await d.prepare(`INSERT OR IGNORE INTO calibration_round_sources(round_id,source_id,source_sha256,position,created_at) SELECT ?,id,sha256,position,? FROM sources WHERE common_blind=1 OR id IN (SELECT id FROM sources WHERE allocation='calibration_training' AND common_blind=0 ORDER BY position LIMIT 6)`).bind(roundId,new Date().toISOString()).run();
 const n:any=await d.prepare('SELECT COUNT(*) n FROM calibration_round_sources WHERE round_id=?').bind(roundId).first();return n.n;
}
