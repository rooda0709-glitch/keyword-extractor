import base64, hashlib, hmac, io, re, time
from collections import Counter, deque
from urllib.parse import urljoin, urlparse, urldefrag
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title='검색광고 키워드 추출기 v6', page_icon='🔎', layout='wide')
NAVER='https://api.searchad.naver.com'

NOISE={'로그인','회원가입','장바구니','마이페이지','고객센터','공지사항','이용약관','개인정보처리방침','회사소개','검색','메뉴','홈','이전','다음','더보기','상품','제품','전체','카테고리','브랜드','추천','베스트','신상품','문의','배송','교환','반품','리뷰','후기','구매','판매','가격','주문','이벤트','상세보기','바로가기'}
INDUSTRY_RULES=[
('식물/조경',r'나무|묘목|모종|수국|장미|조경|정원|화훼|식물|구상|배롱'),
('법률',r'회생|파산|변호사|법률|소송|이혼|형사|채무|상속'),
('교육/자격증',r'자격증|교육|수강|학점|과정|사회복지|평생교육|학원'),
('렌탈',r'렌탈|정수기|공기청정기|매트리스|비데'),
('자동차/화물',r'자동차|화물차|포터|봉고|리스|렌트|용달|화물|배차|콜센터'),
('부동산',r'아파트|분양|매매|전세|월세|부동산|오피스텔'),
('식품/B2B',r'소스|식품|납품|도매|식자재|원료'),
('병원/의료',r'병원|의원|치료|검사|수술|진료|클리닉')]
MODS={
'식물/조경':['묘목','모종','정원수','조경수','농장','판매','가격','배송','택배'],
'법률':['변호사','법률상담','상담','비용','수임료','전문'],
'교육/자격증':['자격증','수강','교육','온라인','비용','신청'],
'렌탈':['렌탈','가격','비용','견적','비교','신청'],
'자동차/화물':['가격','견적','배차','콜','운송','용달','화물','상담'],
'부동산':['매매','분양','전세','월세','가격','시세'],
'식품/B2B':['구매','판매','도매','대량','납품','가격','배송'],
'병원/의료':['병원','의원','진료','상담','비용','예약'],
'기타':['가격','비용','상담','구매','판매','업체']}
REGIONS=sorted(set('''서울특별시 서울 부산광역시 부산 대구광역시 대구 인천광역시 인천 광주광역시 광주 대전광역시 대전 울산광역시 울산 세종특별자치시 세종 경기도 경기 강원특별자치도 강원도 강원 충청북도 충북 충청남도 충남 전북특별자치도 전라북도 전북 전라남도 전남 경상북도 경북 경상남도 경남 제주특별자치도 제주도 제주 수원 성남 용인 고양 화성 부천 남양주 안산 안양 평택 시흥 파주 김포 광명 군포 하남 오산 이천 안성 의왕 양평 여주 동두천 과천 구리 포천 의정부 양주 가평 연천 청주 충주 제천 천안 아산 서산 당진 공주 보령 논산 춘천 원주 강릉 속초 전주 익산 군산 목포 여수 순천 포항 경주 구미 안동 창원 진주 김해 양산 제주시 서귀포 서귀포시 강남구 송파구 서초구 강동구 마포구 영등포구 구로구 금천구 관악구 동작구 종로구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 양천구 강서구 해운대구 수영구'''.split()), key=len, reverse=True)

def clean(x): return re.sub(r'\s+',' ',str(x or '')).strip()
def parse_list(x): return [clean(v) for v in re.split(r'[,/\n]+',x or '') if clean(v)]
def dedupe(xs):
    out=[]; seen=set()
    for x in xs:
        x=clean(x)
        if x and x not in seen: seen.add(x); out.append(x)
    return out

def remove_regions(k):
    s=clean(k); found=[]
    for r in REGIONS:
        if r in s: found.append(r); s=s.replace(r,'')
    s=re.sub(r'[\s\-_/]+','',s)
    return (s or clean(k)), dedupe(found)

def norm_url(u):
    u=clean(u)
    return u if u.startswith(('http://','https://')) else 'https://'+u

def same_domain(a,b): return urlparse(a).netloc.replace('www.','')==urlparse(b).netloc.replace('www.','')

def fetch(url):
    r=requests.get(url,timeout=15,headers={'User-Agent':'Mozilla/5.0 KeywordToolV6'})
    r.raise_for_status()
    return r.text if 'text/html' in r.headers.get('content-type','') else ''

def parse_page(html,url):
    soup=BeautifulSoup(html,'html.parser')
    for t in soup(['script','style','noscript','svg']): t.decompose()
    title=clean(soup.title.get_text(' ',strip=True) if soup.title else '')
    heads=[clean(x.get_text(' ',strip=True)) for x in soup.find_all(['h1','h2','h3','h4'])]
    cand=[]
    sels=['[class*="product"] [class*="name"]','[class*="goods"] [class*="name"]','[class*="item"] [class*="name"]','[class*="service"] [class*="name"]','[class*="product"] a','[class*="goods"] a','[class*="item"] a','[class*="service"] a','[class*="category"] a','[class*="cate"] a','h1','h2','h3','h4']
    for sel in sels:
        try:
            for el in soup.select(sel)[:180]:
                t=clean(el.get_text(' ',strip=True))
                if 2<=len(t)<=60: cand.append(t)
        except: pass
    links=[]
    for a in soup.find_all('a',href=True):
        h=a.get('href','').strip()
        if not h or h.startswith(('#','javascript:','mailto:','tel:')): continue
        u,_=urldefrag(urljoin(url,h))
        if same_domain(url,u): links.append(u)
    return {'url':url,'title':title,'heads':dedupe(heads)[:40],'cand':dedupe(cand)[:250],'links':dedupe(links)[:350]}

def crawl(start,max_pages=12):
    q=deque([start]); seen=set(); pages=[]
    while q and len(pages)<max_pages:
        u=q.popleft()
        if u in seen: continue
        seen.add(u)
        try:
            h=fetch(u)
            if not h: continue
            p=parse_page(h,u); pages.append(p)
            pref=[]; rest=[]
            for link in p['links']:
                if re.search(r'\.(jpg|png|gif|webp|pdf|zip|css|js|xml|mp4)$',urlparse(link).path,re.I): continue
                (pref if re.search(r'product|goods|item|service|category|cate|shop|course|program',link,re.I) else rest).append(link)
            for x in reversed(pref):
                if x not in seen: q.appendleft(x)
            for x in rest:
                if x not in seen: q.append(x)
            time.sleep(.08)
        except: pass
    return pages

def clean_candidate(s):
    s=clean(s); s=re.sub(r'\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}',' ',s)
    s=re.sub(r'\b\d+(?:\.\d+)?\s*(?:cm|mm|m|kg|g|L|ml|호|개|입|팩|set)\b',' ',s,flags=re.I)
    s=re.sub(r'\b(?:무료배송|특가|할인|세일|추천|한정|품절|이벤트)\b',' ',s)
    s=re.sub(r'[|/·,:;!★☆▶▷→]+',' ',s)
    return clean(s)

def analyze_site(pages):
    texts=[]; counts=Counter()
    for p in pages:
        texts += [p['title']]+p['heads']+p['cand']
        for raw in p['heads']+p['cand']:
            v=clean_candidate(raw)
            if not 2<=len(v)<=35 or v in NOISE or re.fullmatch(r'[\d\s,.\-~%원₩]+',v): continue
            counts[v]+=1
    joined=' '.join(texts); industry='기타'
    for name,pat in INDUSTRY_RULES:
        if re.search(pat,joined,re.I): industry=name; break
    scored=[]
    for v,c in counts.items():
        score=c*3+(2 if len(v)<=12 else 0)-(3 if len(v)>=25 else 0)
        if any(t in v for t in ['문의','무료','이벤트','공지','로그인','회원']): score-=6
        if score>0: scored.append((score,v))
    scored.sort(key=lambda z:(-z[0],z[1]))
    return industry,[v for _,v in scored[:40]]

def sign(ts,method,uri,secret):
    msg=f'{ts}.{method}.{uri}'
    return base64.b64encode(hmac.new(secret.encode(),msg.encode(),hashlib.sha256).digest()).decode()

def headers(method,uri,key,secret,cid):
    ts=str(int(time.time()*1000))
    return {'X-Timestamp':ts,'X-API-KEY':key,'X-Customer':str(cid),'X-Signature':sign(ts,method,uri,secret),'Content-Type':'application/json; charset=UTF-8'}

def keyword_tool(seed,key,secret,cid):
    uri='/keywordstool'
    r=requests.get(NAVER+uri,headers=headers('GET',uri,key,secret,cid),params={'hintKeywords':seed,'showDetail':'1'},timeout=20)
    if r.status_code==429: raise RuntimeError('네이버 API 호출 한도 초과(429)')
    if r.status_code>=400: raise RuntimeError(f'네이버 API 오류 {r.status_code}: {r.text[:300]}')
    rows=[]
    for x in r.json().get('keywordList',[]):
        rows.append({'키워드':clean(x.get('relKeyword')),'PC월간검색수':x.get('monthlyPcQcCnt'),'모바일월간검색수':x.get('monthlyMobileQcCnt'),'PC월평균클릭수':x.get('monthlyAvePcClkCnt'),'모바일월평균클릭수':x.get('monthlyAveMobileClkCnt'),'경쟁정도':x.get('compIdx'),'평균광고수':x.get('plAvgDepth'),'기준키워드':seed})
    return pd.DataFrame(rows)

def is_related(k,seed):
    k=clean(k).replace(' ',''); s=clean(seed).replace(' ','')
    if s in k or k in s: return True
    nk,_=remove_regions(k); ns,_=remove_regions(s)
    if ns in nk or nk in ns: return True
    if len(ns)>=4 and ns[:2] in nk and ns[-2:] in nk: return True
    return False

def num(v):
    if v is None:return 0
    if isinstance(v,(int,float)):return int(v)
    s=str(v).replace(',','')
    if '<' in s:
        m=re.findall(r'\d+',s); return max(int(m[0])-1,0) if m else 0
    m=re.findall(r'\d+',s); return int(m[0]) if m else 0

def filter_naver(frames,strict=True,strip_region=True):
    if not frames:return pd.DataFrame()
    raw=pd.concat(frames,ignore_index=True)
    rows=[]
    for _,r in raw.iterrows():
        original=clean(r['키워드']); seed=clean(r['기준키워드'])
        if not original or original in NOISE: continue
        if strict and not is_related(original,seed): continue
        k,regs=remove_regions(original) if strip_region else (original,[])
        if len(k)<2: continue
        rows.append({'키워드':k,'원본키워드':original,'감지지역':', '.join(regs),'기준키워드':seed,'PC월간검색수':r['PC월간검색수'],'모바일월간검색수':r['모바일월간검색수'],'PC월평균클릭수':r['PC월평균클릭수'],'모바일월평균클릭수':r['모바일월평균클릭수'],'경쟁정도':r['경쟁정도'],'평균광고수':r['평균광고수']})
    df=pd.DataFrame(rows)
    if df.empty:return df
    df['총검색수']=df['PC월간검색수'].apply(num)+df['모바일월간검색수'].apply(num)
    agg={'원본키워드':lambda s:', '.join(dedupe(s.astype(str).tolist())),'감지지역':lambda s:', '.join(dedupe([x for x in s.astype(str).tolist() if x])),'기준키워드':lambda s:', '.join(dedupe(s.astype(str).tolist())),'PC월간검색수':'first','모바일월간검색수':'first','PC월평균클릭수':'first','모바일월평균클릭수':'first','경쟁정도':'first','평균광고수':'first','총검색수':'sum'}
    return df.groupby('키워드',as_index=False).agg(agg).sort_values('키워드').reset_index(drop=True)

def combine(bases,mods,direction,label):
    rows=[]
    for b in bases:
        for m in mods:
            if not b or not m: continue
            if direction in ('앞조합','앞+뒤 모두'): rows.append([label,b,m,'앞조합',m+b])
            if direction in ('뒤조합','앞+뒤 모두'): rows.append([label,b,m,'뒤조합',b+m])
    df=pd.DataFrame(rows,columns=['구분','기본키워드','조합어','조합방식','완성키워드'])
    return df.drop_duplicates('완성키워드').sort_values('완성키워드').reset_index(drop=True) if not df.empty else df

def export_xlsx(filtered,combo,industry,cands,seeds):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine='openpyxl') as w:
        filtered.to_excel(w,sheet_name='1차 필터 키워드',index=False)
        if combo is not None and not combo.empty: combo.to_excel(w,sheet_name='2차 조합 키워드',index=False)
        pd.DataFrame([{'항목':'추정 업종','내용':industry},{'항목':'홈페이지 후보','내용':', '.join(cands)},{'항목':'확정 기준키워드','내용':', '.join(seeds)},{'항목':'주의','내용':'홈페이지 후보는 참고용. 최종 1차 키워드는 네이버 키워드 도구 결과만 사용'}]).to_excel(w,sheet_name='홈페이지 참고분석',index=False)
        for ws in w.book.worksheets:
            ws.freeze_panes='A2'
            for c in ws[1]: c.font=c.font.copy(bold=True)
            for col in ws.columns:
                letter=col[0].column_letter; mx=max([len(str(c.value)) if c.value is not None else 0 for c in col[:200]]+[10]); ws.column_dimensions[letter].width=min(max(mx+2,12),45)
    return out.getvalue()

for k,v in {'api':'','secret':'','cid':'','industry':'','cands':[],'filtered':None,'seeds':[]}.items():
    if k not in st.session_state: st.session_state[k]=v

st.title('🔎 검색광고 키워드 추출기 v6')
st.write('홈페이지는 **업종·판매 상품/서비스 파악용 참고**로만 쓰고, 실제 1차 키워드는 **네이버 키워드 도구 결과만 사용**합니다.')

with st.expander('🔐 네이버 검색광고 API 연결'):
    c1,c2=st.columns(2)
    with c1:
        api=st.text_input('Access License / API Key',type='password',value=st.session_state.api)
        cid=st.text_input('Customer ID',value=st.session_state.cid)
    with c2:
        secret=st.text_input('Secret Key',type='password',value=st.session_state.secret)
    if st.button('API 연결 테스트'):
        try:
            if not all([api,secret,cid]): raise RuntimeError('인증정보 3개를 모두 입력해 주세요.')
            n=len(keyword_tool('테스트',api,secret,cid)); st.session_state.api,st.session_state.secret,st.session_state.cid=api,secret,cid
            st.success(f'정상 연결되었습니다. 응답 {n}개 확인')
        except Exception as e: st.error(str(e))

st.subheader('1. 홈페이지 참고 분석')
url=st.text_input('홈페이지 URL',placeholder='https://example.com')
max_pages=st.slider('참고 페이지 수',3,30,12,3)
if st.button('① 홈페이지 분석',type='primary'):
    if not url: st.error('URL을 입력해 주세요.')
    else:
        with st.spinner('업종과 상품/서비스 후보를 파악 중입니다...'):
            pages=crawl(norm_url(url),max_pages)
            if not pages: st.error('사이트를 읽지 못했습니다.')
            else:
                ind,cands=analyze_site(pages); st.session_state.industry=ind; st.session_state.cands=cands
                st.success(f'업종 추정: {ind}')

if st.session_state.cands:
    st.info('아래는 **참고 후보**입니다. 최종 키워드에 자동으로 섞이지 않습니다. 실제 상품/서비스에 해당하는 기준키워드만 남겨주세요.')
    seed_text=st.text_area('② 확정 기준키워드',value='\n'.join(st.session_state.cands[:20]),height=180)

    st.subheader('2. 네이버 키워드 도구')
    c1,c2=st.columns(2)
    with c1: strict=st.checkbox('기준키워드와 직접 연관된 결과만 남기기',True)
    with c2: strip_region=st.checkbox('지역명 자동 제거',True)
    limit=st.slider('조회 기준키워드 수',1,30,15)

    if st.button('③ 네이버 키워드 추출 + 필터링',type='primary'):
        seeds=dedupe(parse_list(seed_text)); st.session_state.seeds=seeds
        api=api or st.session_state.api; secret=secret or st.session_state.secret; cid=cid or st.session_state.cid
        if not seeds: st.error('기준키워드를 최소 1개 남겨주세요.')
        elif not all([api,secret,cid]): st.error('네이버 API 인증정보를 먼저 입력해 주세요.')
        else:
            frames=[]; errors=[]; prog=st.progress(0)
            for i,s in enumerate(seeds[:limit]):
                try: frames.append(keyword_tool(s,api,secret,cid)); time.sleep(.12)
                except Exception as e: errors.append(f'{s}: {e}')
                prog.progress(int((i+1)/min(len(seeds),limit)*100))
            f=filter_naver(frames,strict,strip_region); st.session_state.filtered=f
            if errors: st.warning('\n'.join(errors[:5]))
            if f.empty: st.error('필터 후 남은 키워드가 없습니다. 직접 연관 옵션을 꺼서 다시 확인해보세요.')
            else: st.success(f'1차 필터 완료: {len(f):,}개')

if isinstance(st.session_state.filtered,pd.DataFrame) and not st.session_state.filtered.empty:
    f=st.session_state.filtered
    st.subheader('3. 지역 제거 + 가나다순 검토')
    st.caption('검색량은 참고값으로만 유지하고, 목록은 가나다순으로 정렬합니다.')
    st.dataframe(f,use_container_width=True,height=500)

    st.subheader('4. 별도 조합기')
    bases_text=st.text_area('기본키워드',value='\n'.join(f['키워드'].astype(str).tolist()),height=160)
    default_mods=MODS.get(st.session_state.industry,MODS['기타'])
    mods_text=st.text_area('일반 조합어',value=', '.join(default_mods),height=80)
    regions_text=st.text_area('지역 조합어 (선택)',placeholder='서울, 경기, 인천, 수원, 용인',height=70)
    direction=st.radio('조합 방향',['앞조합','뒤조합','앞+뒤 모두'],horizontal=True,index=2)
    if st.button('④ 조합 생성'):
        bases=dedupe(parse_list(bases_text)); mods=dedupe(parse_list(mods_text)); regs=dedupe(parse_list(regions_text))
        a=combine(bases,mods,direction,'일반조합'); b=combine(bases,regs,direction,'지역조합') if regs else pd.DataFrame()
        combo=pd.concat([a,b],ignore_index=True) if not b.empty else a
        combo=combo.sort_values('완성키워드').reset_index(drop=True) if not combo.empty else combo
        st.session_state.combo=combo

    if isinstance(st.session_state.get('combo'),pd.DataFrame) and not st.session_state.combo.empty:
        st.dataframe(st.session_state.combo,use_container_width=True,height=420)
        xlsx=export_xlsx(f,st.session_state.combo,st.session_state.industry,st.session_state.cands,st.session_state.seeds)
        st.download_button('📥 최종 Excel 다운로드',xlsx,'검색광고_키워드_추출_v6.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
