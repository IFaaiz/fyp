import {cp, rules} from './annotation';

export const kinds:Record<string,{title:string;description:string;example:string}>={
 MEETING:{title:'Meeting',description:'Arrange, change, cancel or report a project meeting.',example:'“Let’s review Project Orion on Friday at 3.” Friday is the meeting date, not a deadline.'},
 ACTION:{title:'Task',description:'Ask for, assign, promise or finish a specific piece of work.',example:'“Please test the Orion login screen.” Label the task. A request to send a report belongs under Document.'},
 DOCUMENT:{title:'Document',description:'Request, expect, send, receive or review a project deliverable.',example:'“Please send the Orion report by Friday.” Add one Document label. Friday is its due date.'},
 APPROVAL:{title:'Approval',description:'Ask for or communicate permission or a formal decision.',example:'“The Orion budget is approved.” Asking someone to review a draft is a task, not automatically approval.'},
 STATUS:{title:'Project update',description:'Report progress, completion, a problem or a project decision.',example:'“Orion testing is complete.” Highlight the words describing that update. Don’t use this label just because an email gives information.'},
};
export const roleLabels:Record<string,string>={EVENT_ANCHOR:'Words that show this label',ACTION:'What work needs doing',DOCUMENT:'Document name',RESPONSIBLE_PARTY:'Who will do the work',CONTRIBUTOR:'Department giving input',RECIPIENT:'Who receives it',MENTION_ONLY:'Person only mentioned',PARTICIPANT:'Who attends',MEETING_NAME:'Meeting name',LOCATION:'Where it happens',MEETING_DATE:'Meeting date',MEETING_TIME:'Meeting time',DUE_DATE:'Due date',DUE_TIME:'Due time',OCCURRENCE_DATE:'Date of the update',OCCURRENCE_TIME:'Time of the update',APPROVAL_TARGET:'What needs approval',APPROVER:'Who approves',STATUS:'What changed or happened',AGENDA:'What the meeting covers',PROJECT:'Project name'};
export const roleHints:Record<string,string>={
 EVENT_ANCHOR:'Highlight the current author’s words showing this act, such as “please send the report” or “testing is complete”. Use the message, not the subject.',
 ACTION:'Highlight the work itself, with its verb and object, such as “test the login screen”. This can be the same phrase you used above.',
 STATUS:'Highlight the actual update, such as “testing is complete”. This can be the same phrase you used above.',
 RESPONSIBLE_PARTY:'Only highlight someone explicitly assigned to or promising this work. A name in a signature is not enough.',
 CONTRIBUTOR:'Use this only for an explicitly contributing department. A group or team is not automatically a department.',
 DUE_DATE:'Only add a date when the words say the task or document is due then. Do not use a meeting date.',
 DUE_TIME:'Only add a time when the words make it a deadline.',
 MEETING_DATE:'Highlight the date of this meeting. Do not label it as a due date.',
 MEETING_TIME:'Highlight the time of this meeting.',
 DOCUMENT:'Highlight the document or deliverable actually named in this message.',
 APPROVER:'Highlight the person who is explicitly asked to decide or who made the decision.',
};
export const stateLabels:Record<string,string>={proposed:'Suggested, not confirmed',scheduled:'Scheduled / confirmed',rescheduled:'Time or date changed',cancelled:'Cancelled',completed:'Finished',requested:'Requested',assigned:'Assigned to someone',committed:'Someone promises to do it',expected:'Expected / planned',submitted:'Submitted for review',delivered:'Sent / delivered',missing:'Missing / not received',reviewed:'Already reviewed',granted:'Approved',rejected:'Rejected',withheld:'Decision held back',conditional:'Approved with conditions',progress:'Progress update',blocker:'Problem blocking work',decision:'Decision about the project',work_state_change:'Change in the work'};
export const guide:[string,string][]=[
 ['Start here','Read the current message. Decide whether it is project work, add only the labels it actually supports, then check and submit. You do not need to fill every detail.'],
 ['What counts as project work?','Look for a bounded goal, workstream, deliverable, milestone or meeting. The word “project” need not appear. A contract, data request or staffing email alone does not prove project work. If it is clearly routine or unrelated, choose “Not project work”; if the connection to a defined initiative is unclear, choose “Not sure.”'],
 ['Contracts, data and staffing','A defined analysis phase or workstream with a deliverable can be project work. Routine monthly pricing, invoice administration or an internal career move is not project work by itself. Contract changes, market operations and raw data requests need context; use “Not sure” when the message does not show whether they belong to a defined initiative.'],
 ['Only label the author’s current message','The subject and older messages can help you understand context. They cannot supply a new task or update that the current author did not express. Ignore signatures, forwarded requests and hypothetical draft scripts as current evidence. Faded text is reference only.'],
 ['A small worked example','“For Project Orion, please send the revised report by Friday.” Choose Project work and use “For Project Orion” as relevance evidence. Add Document → Requested. Highlight “please send the revised report” as the words showing the label, “revised report” as the document, and “Friday” as the due date. Do not repeat the document transfer as a Task.'],
 ['Meeting','Arrange, confirm, move, cancel or report a specific project meeting. Highlight the words showing the meeting. Add its date, time or location only if given. Meeting dates are not deadlines.'],
 ['Task','A concrete piece of work is requested, assigned, promised, completed or cancelled. Highlight both the words showing the act and the work to do. They may be the same phrase. Sending a file by itself is Document. A completed or cancelled Task already derives an update label; do not add a second Project update for the same act.'],
 ['Document','A project report or deliverable is requested, expected, submitted, delivered, missing or reviewed. Add a document name and due date only when stated. Raw data, a spreadsheet, comments or a draft contract is not automatically a project report. If the document is not clearly a project deliverable, choose the “Other / needs review” option. Do not also add a Task just to repeat a file transfer.'],
 ['Approval','Someone asks for or communicates formal permission or a decision. “Please review this draft,” “send comments,” and “any suggestions?” ask for work or input; they are not Approval unless the message explicitly grants, denies or requests authorization.'],
 ['Project update','The message explicitly gives progress, completion, a blocker, a decision or a change in project work. Highlight the words showing the update and the update itself. They may be the same phrase. This is not a general “information” label. Submitted, delivered, missing or reviewed documents also derive an update label; do not add a second Project update for the same document event.'],
 ['Several labels, or none','Add a label for each distinct act. One email may have several. Project-related wording with no explicit act can have no labels. A clearly unrelated message has no project labels. Do not invent one to fill the form.'],
 ['Which words should I highlight?','Use the shortest complete phrase that supports the fact. Keep a task’s verb and object together. Highlight exact words in the message or use “Paste exact words”. Add names and dates to the correct label; leave unstated facts blank.'],
 ['People and departments','A person mentioned is not necessarily responsible. Add responsibility only when explicitly assigned or promised. “Department giving input” requires a real department, not just a team or a name in a signature.'],
 ['Follow-ups','Use explicit reminder wording, not just “Re:” in a subject. An earlier event must be verified before linking it. Use the follow-up control to flag an unresolved earlier event for another review.'],
 ['When you are unsure','Use “Not sure” for unclear project relevance, or mark the particular label unclear. Say what is uncertain in the final step. An honest uncertainty is useful; do not guess names, dates, labels or earlier events.'],
 ['Saving and independent review','Drafts save every ten seconds and can resume after signing in again. Submit only after reading the message yourself. Submitted answers are locked for independent comparison. Do not ask teammates or AI for answers to your assigned emails.'],
];

export function authored(source:any,start:number,end:number){return (source.authored_ranges||[]).some((r:any)=>start>=r.start&&end<=r.end);}
export function exactMatches(source:any,field:string,words:string){
 const text=cp(source[field]||''),needle=cp(words),found:any[]=[];
 if(!needle.length)return found;
 for(let i=0;i<=text.length-needle.length;i++)if(text.slice(i,i+needle.length).join('')===words&&(field!=='current_message'||authored(source,i,i+needle.length)))found.push({field,start:i,end:i+needle.length,text:words});
 return found;
}
export function missingRoles(annotation:any,event:any){return rules.required_event_roles[event.kind].filter((role:string)=>!annotation.event_span_links.some((l:any)=>l.event_id===event.id&&l.role===role));}
