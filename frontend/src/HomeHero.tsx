import {useEffect,useState} from 'react';
import {Product} from './api';

export default function HomeHero({start}:{start:()=>void}){
 const [leaders,setLeaders]=useState<Product[]>([]),[failed,setFailed]=useState(false);
 useEffect(()=>{const controller=new AbortController();fetch('/api/home',{signal:controller.signal})
  .then(async response=>{if(!response.ok)throw new Error();const result=await response.json();setLeaders(result.data.brand_leaders)})
  .catch(error=>{if(error.name!=='AbortError')setFailed(true)});return()=>controller.abort()},[]);
 return <section className="hero hero-reference"><div className="hero-copy"><span className="hero-kicker">AI 휴대폰 구매 상담</span>
  <h1>나에게 맞는 폰,<br/>AI 상담으로 쉽게 고르세요</h1>
  <p>예산과 원하는 조건만 말하면 등록된 재고 기준으로 상품을 추천하고,<br className="desktop-break"/>옵션 확인부터 카드 할인 견적까지 바로 계산해 드려요.</p>
  <div className="hero-actions"><button className="primary" onClick={start}>AI 상담 시작하기</button><a className="popular-link" href="#popular-products">인기 상품 보기</a></div>
 </div><div className="brand-winners"><span className="winners-label">브랜드별 최근 3개월 판매 1위</span>
  <div className="winners-grid">{leaders.map(product=><article className="winner-card" key={product.brand}>
   <div className="winner-photo">{product.image_url?<img src={'/api'+product.image_url} alt={product.product_name}/>:<span>이미지 준비 중</span>}</div>
   <h2>{product.product_name}</h2><p>{product.brand} 판매 1위</p>
  </article>)}{!leaders.length&&<p className="winners-placeholder" role="status">{failed?'판매 순위를 불러오지 못했습니다.':'브랜드별 인기 상품을 불러오는 중입니다…'}</p>}</div>
 </div></section>
}
