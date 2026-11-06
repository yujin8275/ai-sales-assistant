import {useState} from 'react';
import {money,Product} from './api';

export function ServiceFeatures(){return <section className="service-features" aria-label="상담 서비스 안내">
 <article><strong>등록 재고 기준 추천</strong><p>구매 가능한 옵션만 골라 최대 5개 기종을 추천해요</p></article>
 <article><strong>카드 할인 자동 계산</strong><p>등록된 카드사 정책의 기간·대상 상품을 확인해 적용해요</p></article>
 <article><strong>제품 설명서 근거 제공</strong><p>추천 이유에 설명서 문서명과 페이지를 함께 보여드려요</p></article>
</section>}

export default function HomeProducts({products,error,start,disabled}:{products:Product[];error:string;start:(message:string)=>void;disabled:boolean}){
 const [brand,setBrand]=useState('');
 const visible=products.filter(p=>!brand||p.brand===brand);
 return <section className="store-products" id="popular-products"><div className="store-section-heading"><div><h2>최근 많이 팔린 스마트폰</h2><p>최근 3개월 판매량 순{products[0]?.sales_reference_date?' · 기준일 '+products[0].sales_reference_date.replaceAll('-','.'):''}</p></div>
 <div className="brand-filters" aria-label="상품 브랜드 필터">{[['','전체'],['Samsung','삼성'],['Apple','애플'],['Xiaomi','샤오미']].map(([value,label])=><button key={value} aria-pressed={brand===value} onClick={()=>setBrand(value)}>{label}</button>)}</div></div>
 {error?<p role="alert">{error}</p>:!products.length?<p className="muted">상품을 불러오는 중입니다…</p>:<div className="store-grid">{visible.map(product=>{
 const specs=product.specs,v=product.representative_variant,soldOut=v.availability==='OUT_OF_STOCK';
 return <article className="store-card" key={product.product_id}><div className="store-image">{product.image_url?<img src={'/api'+product.image_url} alt={product.product_name}/>:<span>이미지 준비 중</span>}</div>
 <div className="store-name"><h3>{product.product_name}</h3><span className={soldOut?'stock-tag':'rank-tag'}>{soldOut?'품절':'판매 '+product.rank+'위'}</span></div>
 <p className="store-specs">{product.brand}{specs?.display_inches?' · '+specs.display_inches+'인치':''}{specs?.weight_g?' · '+specs.weight_g+'g':''} · {v.storage_gb??'미확인'}GB</p>
 <p className={'store-price'+(soldOut?' unavailable':'')}>{soldOut?'현재 전 옵션 품절':money(product.price_from)}{!soldOut&&<small>부터</small>}</p>
 <div className="store-bottom"><span>최근 3개월 {product.sales_quantity_3m?.toLocaleString('ko-KR')}대 판매</span><button disabled={disabled} onClick={()=>start(product.product_name+'('+product.product_id+')의 전체 옵션과 재고를 보여줘')}>AI 상담</button></div></article>})}</div>}
 {!!products.length&&!visible.length&&<p className="muted">현재 상위 8개 상품에 해당 브랜드가 없습니다.</p>}
 </section>
}
