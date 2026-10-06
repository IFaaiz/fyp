import {legacyDerivedLabelVersion,rules,stampBlindHumanSubmission,stampUnannotatedDraft,validateAnnotation} from './annotation';
import {directVersion,stampDirectDraft,stampDirectSubmission,validateDirect} from './direct-annotation';
export function prepareReview(input:any,source:any,prior:any,status:string,userId:string,now:string){
 const expected=prior?.schema_version||directVersion;
 if(input?.schema_version!==expected)throw Object.assign(new Error('This saved review keeps its original schema. Open its original form; no silent conversion is allowed.'),{status:409});
 if(expected===directVersion){const a=status==='submitted'?stampDirectSubmission(input,source,userId,now):stampDirectDraft(input,source);return {annotation:a,errors:status==='submitted'?validateDirect(a,source):[]};}
 if(expected!=='fyp-structured-v1')throw Object.assign(new Error('Unsupported saved annotation format. Contact the owner.'),{status:409});
 const version=prior?.derived_label_version||legacyDerivedLabelVersion;
 if(![legacyDerivedLabelVersion,rules.derived_label_version].includes(version))throw Object.assign(new Error('Unsupported saved label rule version.'),{status:409});
 const a=status==='submitted'?stampBlindHumanSubmission(input,source,userId,now,version):stampUnannotatedDraft(input,source,version);
 return {annotation:a,errors:status==='submitted'?validateAnnotation(a,source):[]};
}
