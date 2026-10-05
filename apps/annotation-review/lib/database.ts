import {env} from 'cloudflare:workers';
import {getChatGPTUser} from '../app/chatgpt-auth';
export function db():D1Database {if(!(env as any).DB)throw new Error('Review storage is unavailable. Changes have not been saved.');return (env as any).DB;}
export async function identity(){const u=await getChatGPTUser();if(!u)throw Object.assign(new Error('Sign in with your own ChatGPT account.'),{status:401});return u;}
export async function reviewer(){
 const u=await identity(),d=db();let row:any=await d.prepare('SELECT * FROM reviewers WHERE user_id=?').bind(u.userId).first();
 if(!row){await d.prepare(`INSERT OR IGNORE INTO reviewers(user_id,email,display_name,slot,created_at)
  SELECT ?,?,?,slots.n,? FROM (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2) slots
  WHERE slots.n NOT IN (SELECT slot FROM reviewers) ORDER BY slots.n LIMIT 1`).bind(u.userId,u.email.toLowerCase(),u.displayName,new Date().toISOString()).run();
  row=await d.prepare('SELECT * FROM reviewers WHERE user_id=?').bind(u.userId).first();
  if(!row)throw Object.assign(new Error('Only three registered reviewers may participate. Contact the owner.'),{status:403});}
 return {...u,slot:row.slot,isAdmin:u.email.toLowerCase()===String((env as any).ADMIN_EMAIL||'').toLowerCase()};
}
export function result(v:unknown,status=200){return Response.json(v,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
export function failed(e:any){return result({error:e?.message||'Request could not be completed.'},e?.status||503);}
export function requireSameOrigin(r:Request){const o=r.headers.get('origin');if(o&&o!==new URL(r.url).origin)throw Object.assign(new Error('Save from the review app.'),{status:403});}
