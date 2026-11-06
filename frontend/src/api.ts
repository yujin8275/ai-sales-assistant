import type {Specs} from './queryFacts';
export type Product = {specs?:Specs;rank?:number;sales_quantity_3m?:number;sales_reference_date?:string;position:number; product_id:string;product_name:string;brand:string;image_url:string|null;price_from:number;representative_variant:Variant;reasons:{summary:string;source_ids:string[]}[]};
export type Variant = {availability?:string;sku:string;color:string|null;ram_gb:number|null;storage_gb:number|null;sale_price:number;stock_quantity:number};
export type Quote = {items:(Variant & {product_name:string;quantity:number;unit_price:number;subtotal:number;discount_amount:number;total:number})[];subtotal:number;discount_amount:number;total:number;checked_at:string};
export type Result = {follow_up?:{text:string;options:{label:string;message:string}[]}|null;status:string;message:string;data:null|{applied_filters?:Record<string,unknown>;products?:{product_name:string;specs:Specs}[];session?:{session_id:string};recommendations?:Product[];variants?:Variant[];product?:{product_name:string;specs:Specs};quote?:Quote;comparison?:{products:{product_name:string}[];differences:string[]};sales_ranking?:Product[];stock_issues?:{sku:string;requested_quantity:number;available_quantity:number}[];consultation?:{constraints:Record<string,unknown>;selected_items:{sku:string;quantity?:number}[];expires_at:string}};questions:{text:string;options:{label:string;message:string}[]}[];warnings:string[];sources:{source_id:string;source_file:string;page_number:number;summary:string}[];error:null|{code:string}};
export const money=(n:number)=>new Intl.NumberFormat('ko-KR').format(n)+'원';
export class ApiError extends Error {constructor(public code:string,message:string){super(message)}}
async function jsonResponse(response:Response):Promise<Result>{
 try{return await response.json()}catch{throw new ApiError('INVALID_RESPONSE','서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.')}
}
export async function post(path:string,body:unknown,signal?:AbortSignal):Promise<Result>{
 const response=await fetch('/api'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
 const data=await jsonResponse(response);if(!response.ok)throw new ApiError(data.error?.code||'HTTP_ERROR',data.message||'연결에 실패했습니다.');return data;
}
export async function chat(session_id:string,message:string,onProgress:(text:string)=>void,signal:AbortSignal,timeoutMs=120000):Promise<Result>{
 const controller=new AbortController();let timedOut=false;
 const cancel=()=>controller.abort();
 if(signal.aborted)cancel();else signal.addEventListener('abort',cancel,{once:true});
 const timer=setTimeout(()=>{timedOut=true;controller.abort()},timeoutMs);
 try{return await readChat(session_id,message,onProgress,controller.signal)}
 catch(error){if(timedOut)throw new ApiError('REQUEST_TIMEOUT','응답 대기 시간 120초를 초과했습니다. 입력한 내용을 다시 보내주세요.');throw error}
 finally{clearTimeout(timer);signal.removeEventListener('abort',cancel)}
}
async function readChat(session_id:string,message:string,onProgress:(text:string)=>void,signal:AbortSignal):Promise<Result>{
 const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id,request_id:crypto.randomUUID(),message}),signal});
 if(!response.ok){const data=await jsonResponse(response);throw new ApiError(data.error?.code||'HTTP_ERROR',data.message)}
 if(!response.body)throw new Error('응답을 읽을 수 없습니다.');
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',final:Result|undefined;
 try{while(true){const {done,value}=await reader.read();buffer=(buffer+decoder.decode(value,{stream:!done})).replace(/\r\n/g,'\n');let end;
 while((end=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,end);buffer=buffer.slice(end+2);let event='',parts:string[]=[];for(const line of block.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('data:'))parts.push(line.slice(5).trimStart())}if(!parts.length)continue;const data=JSON.parse(parts.join('\n'));if(event==='progress')onProgress(data.message);if(event==='final'||event==='error')final=data;}
 if(done)break;}}finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
 if(!final)throw new Error('응답 연결이 중단되었습니다. 새 요청으로 다시 시도해 주세요.');return final;
}


