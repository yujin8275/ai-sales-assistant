import {money} from './api.js';

export type Specs={display_inches?:number|null;weight_g?:number|null;battery_mah?:number|null;processor?:string|null};
export function conditionLabels(filters:Record<string,unknown>):string[]{
 const labels:string[]=[];
 for(const [key,value] of Object.entries(filters)){
  if(value===null||value===undefined||(Array.isArray(value)&&!value.length))continue;
  if(key==='budget'&&typeof value==='object'){
   const b=value as {amount:number;scope:string;comparison?:string;upper_amount?:number}; const label=b.comparison==='RANGE'?money(b.amount)+' 이상 ~ '+money(b.upper_amount!)+' 이하':money(b.amount)+' '+({LTE:'이하',LT:'미만',GTE:'이상',GT:'초과'}[b.comparison||'LTE']||'이하'); labels.push((b.scope==='TOTAL'?'총 가격 조건 ':'1대당 가격 조건 ')+label);
  }else if(key==='brands'&&Array.isArray(value))labels.push('브랜드 '+value.join(', '));
  else if(key==='colors'&&Array.isArray(value))labels.push('색상 '+value.join(', '));
  else if(key==='max_weight_g')labels.push('무게 '+value+'g 이하');
  else if(key==='min_display_inches')labels.push('화면 '+value+'인치 이상');
  else if(key==='min_battery_mah')labels.push('배터리 '+Number(value).toLocaleString('ko-KR')+'mAh 이상');
  else if(key==='storage_gb')labels.push('저장 용량 '+value+'GB');
  else if(key==='min_storage_gb')labels.push('저장 용량 '+value+'GB 이상');
  else if(key==='ram_gb')labels.push('RAM '+value+'GB');
  else if(key==='quantity')labels.push('조회 수량 '+value+'대');
  else if(key==='purpose')labels.push('용도: '+value);
  else if(key==='card_company')labels.push('카드사 '+value);
 }
 return labels;
}
export function relevantSpecs(specs:Specs|undefined,filters:Record<string,unknown>):string[]{
 const labels:string[]=[];
 const purpose=String(filters.purpose??'');
 if(filters.max_weight_g!==undefined||/가벼|무게|휴대성/.test(purpose))labels.push(specs?.weight_g==null?'무게 미확인':'무게 '+specs.weight_g+'g');
 if(filters.min_display_inches!==undefined||/화면|영상/.test(purpose))labels.push(specs?.display_inches==null?'화면 크기 미확인':'화면 '+Number(specs.display_inches)+'인치');
 if(filters.min_battery_mah!==undefined||/배터리/.test(purpose))labels.push(specs?.battery_mah==null?'배터리 미확인':'배터리 '+specs.battery_mah.toLocaleString('ko-KR')+'mAh');
 return labels;
}

