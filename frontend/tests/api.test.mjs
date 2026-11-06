import test from 'node:test';
import assert from 'node:assert/strict';
import {chat,post,ApiError} from '../.test-build/api.js';
import {conditionLabels,relevantSpecs} from '../.test-build/queryFacts.js';

test('무게 조회 기준과 실제 무게를 구분해서 표시한다',()=>{
 assert.deepEqual(conditionLabels({max_weight_g:180}),['무게 180g 이하']);
 assert.deepEqual(relevantSpecs({weight_g:162},{max_weight_g:180}),['무게 162g']);
});
test('화면·배터리 조건의 실제 사양도 표시한다',()=>{
 assert.deepEqual(relevantSpecs({display_inches:6.7,battery_mah:5000},{min_display_inches:6.5,min_battery_mah:5000}),['화면 6.7인치','배터리 5,000mAh']);
});
test('미확인 사양은 조건값으로 대신 채우지 않는다',()=>{
 assert.deepEqual(relevantSpecs(undefined,{max_weight_g:180}),['무게 미확인']);
 assert.deepEqual(conditionLabels({scope_product_ids:['internal'],colors:[]}),[]);
});

const terminal={status:'OK',message:'견적 669,000원',data:{quote:{total:669000}}};
function mockStream(text){const bytes=new TextEncoder().encode(text);globalThis.fetch=async()=>new Response(new ReadableStream({start(controller){for(const byte of bytes)controller.enqueue(new Uint8Array([byte]));controller.close()}}))}
test('한글 UTF-8과 CRLF가 바이트 경계에서 나뉘어도 SSE 완료 결과를 읽는다',async()=>{
 mockStream('event: progress\r\ndata: {"message":"조회 중"}\r\n\r\nevent: final\r\ndata: '+JSON.stringify(terminal)+'\r\n\r\n');
 const progress=[];assert.deepEqual(await chat('s','q',s=>progress.push(s),new AbortController().signal),terminal);assert.deepEqual(progress,['조회 중']);
});
test('최종 이벤트 없는 연결 종료는 성공 처리하지 않는다',async()=>{
 mockStream(': waiting\n\n');await assert.rejects(chat('s','q',()=>{},new AbortController().signal),/연결이 중단/);
});
test('SSE 오류 결과를 정상 견적으로 바꾸지 않는다',async()=>{
 const error={status:'ERROR',message:'실패',data:null,error:{code:'MODEL_ERROR'}};mockStream('event: error\ndata: '+JSON.stringify(error)+'\n\n');assert.deepEqual(await chat('s','q',()=>{},new AbortController().signal),error);
});
test('만료 오류 코드는 화면에 전달된다',async()=>{
 globalThis.fetch=async()=>new Response(JSON.stringify({message:'새 상담',error:{code:'SESSION_EXPIRED'}}),{status:410});await assert.rejects(post('/sessions',{}),e=>e instanceof ApiError&&e.code==='SESSION_EXPIRED');
});
test('프록시 HTML 오류를 그대로 노출하지 않는다',async()=>{
 globalThis.fetch=async()=>new Response('<html>Bad Gateway</html>',{status:502});await assert.rejects(post('/sessions',{}),/서버에 연결할 수 없습니다/);
});
test('응답이 끝없이 지연되면 시간 초과 안내로 전환한다',async()=>{
 globalThis.fetch=async(url,options)=>new Promise((resolve,reject)=>{
  options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});
 });
 await assert.rejects(chat('s','q',()=>{},new AbortController().signal,20),e=>e instanceof ApiError&&e.code==='REQUEST_TIMEOUT'&&e.message.includes('120초'));
});
