/** Apply relevance without retaining invisible project labels or placeholder review flags. */
export function setDirectScope(annotation:any,value:string){
 annotation.scope.value=value;
 if(value==='PROJECT')annotation.labels=annotation.labels.filter((label:string)=>label!=='NON_PROJECT');
 if(value!=='UNCERTAIN'){
  annotation.review_reasons=annotation.review_reasons.filter((reason:string)=>!['Project relevance has not been decided.','Project relevance is unclear.'].includes(reason));
  if(!annotation.review_reasons.length&&!annotation.label_support.some((row:any)=>row.review_reason?.trim()))annotation.needs_review=false;
 }
 if(value!=='PROJECT'){
  annotation.labels=value==='NON_PROJECT'?['NON_PROJECT']:[];
  annotation.label_support=[];
  annotation.spans=annotation.spans.filter((span:any)=>annotation.scope.evidence_span_ids.includes(span.id));
 }
 if(value==='UNCERTAIN'){
  annotation.needs_review=true;
  if(!annotation.review_reasons.length)annotation.review_reasons=['Project relevance is unclear.'];
 }
}
