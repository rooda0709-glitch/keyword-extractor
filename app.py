
import io
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup


st.set_page_config(page_title="검색광고 키워드 추출기 v3", page_icon="🔎", layout="wide")

PURPOSE_PRESETS = {
    "네이버 파워링크 세팅": {
        "desc": "구매/상담/문의 가능성이 높은 검색광고 키워드를 우선 발굴",
        "base": ["구매","판매","가격","비용","견적","상담","신청","주문","배송","택배","업체","전문업체"]
    },
    "검색광고 키워드 확장": {
        "desc": "기존 키워드에서 연관 키워드와 롱테일 키워드를 폭넓게 확장",
        "base": ["구매","판매","가격","비교","추천","업체","전문","상담","신청","후기"]
    },
    "쇼핑검색광고 세팅": {
        "desc": "상품 구매 의도가 높은 제품/가격/배송 중심 키워드 발굴",
        "base": ["구매","판매","가격","최저가","주문","온라인주문","배송","택배","할인"]
    },
    "SEO/콘텐츠 키워드": {
        "desc": "정보 탐색형 키워드까지 포함해 콘텐츠 주제를 확장",
        "base": ["추천","비교","후기","방법","종류","가격","정보","장단점"]
    },
    "경쟁사/시장 키워드 조사": {
        "desc": "사이트에서 상품/서비스명을 추출해 시장 키워드 풀을 넓게 수집",
        "base": ["가격","비용","후기","추천","비교","업체","전문업체","상담"]
    },
}

INDUSTRY_PRESETS = {
    "자동 감지": [],
    "식물/조경": ["묘목","모종","정원수","조경수","농장","전문농장","식재","키우기","관리법","월동"],
    "법률": ["변호사","법률상담","상담","비용","수임료","신청","전문","해결"],
    "교육/자격증": ["자격증","수강","교육","온라인","비용","가격","신청","과정","학원"],
    "렌탈": ["렌탈","가격","비용","견적","비교","신청","설치","상담"],
    "자동차/화물차": ["가격","견적","구매","판매","리스","렌트","할부","상담"],
    "병원/의료": ["병원","의원","진료","상담","비용","예약","치료","검사"],
    "부동산": ["매매","분양","전세","월세","가격","시세","상담","중개"],
    "식품/B2B": ["구매","판매","도매","대량","납품","가격","배송","주문","업체"],
    "기타": [],
}

NOISE = {
    "로그인","회원가입","장바구니","마이페이지","고객센터","공지사항","이용약관",
    "개인정보처리방침","회사소개","검색","메뉴","홈","이전","다음","더보기",
    "상품","제품","전체","카테고리","브랜드","추천","베스트","신상품","문의",
    "배송","교환","반품","리뷰","후기","구매","판매","가격","주문","이벤트"
}

PURCHASE_TERMS = {
    "구매":3,"판매":3,"가격":2,"비용":2,"견적":3,"상담":3,"신청":3,"주문":3,
    "온라인주문":3,"배송":2,"택배":2,"업체":2,"전문업체":2,"농장":2,"전문농장":2,
    "묘목":2,"모종":2,"정원수":2,"조경수":2,"렌탈":3,"리스":3,"렌트":3,"예약":3,
    "도매":3,"대량":2,"납품":3,"수강":2,"교육":1,"변호사":2,"법률상담":3
}
INFO_TERMS = {
    "키우기":3,"키우는법":3,"관리":2,"관리법":3,"물주기":3,"가지치기":3,
    "심는법":3,"월동":2,"재배":2,"재배법":3,"후기":2,"뜻":3,"효능":3,
    "사진":2,"방법":2,"정보":2,"장단점":2
}


def norm_url(url):
    url = url.strip()
    if not url.startswith(("http://","https://")):
        url = "https://" + url
    return url


def same_domain(a,b):
    return urlparse(a).netloc.replace("www.","") == urlparse(b).netloc.replace("www.","")


def clean(s):
    return re.sub(r"\s+"," ",s or "").strip()


def clean_name(s):
    s = clean(s)
    s = re.sub(r"\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}"," ",s)
    s = re.sub(r"\b\d+(?:\.\d+)?\s*(?:cm|mm|m|kg|g|L|ml|호|개|입|팩|set|SET)\b"," ",s,flags=re.I)
    s = re.sub(r"\b(?:무료배송|당일배송|특가|할인|세일|신상품|베스트|추천|한정|품절|예약)\b"," ",s)
    s = re.sub(r"[|/·,:;!★☆▶▷→]+"," ",s)
    return clean(s)[:70]


def fetch(url):
    r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0 (KeywordExtractor/3.0)"})
    r.raise_for_status()
    if "text/html" not in r.headers.get("content-type",""):
        return ""
    return r.text


def parse_page(html,url):
    soup = BeautifulSoup(html,"html.parser")
    for tag in soup(["script","style","noscript","svg"]):
        tag.decompose()

    title = clean(soup.title.get_text(" ",strip=True) if soup.title else "")
    headings=[clean(x.get_text(" ",strip=True)) for x in soup.find_all(["h1","h2","h3"])]
    headings=[x for x in headings if x]

    cands=[]
    for sel in [
        '[class*="product"] a','[class*="item"] a','[class*="goods"] a',
        '[class*="name"]','[class*="title"]','h1','h2','h3','h4','main a','article a','li a'
    ]:
        try:
            for el in soup.select(sel)[:220]:
                t=clean(el.get_text(" ",strip=True))
                if 2<=len(t)<=100:
                    cands.append(t)
        except:
            pass

    for img in soup.find_all("img")[:150]:
        alt=clean(img.get("alt",""))
        if 2<=len(alt)<=100:
            cands.append(alt)

    links=[]
    for a in soup.find_all("a",href=True):
        href=a.get("href","").strip()
        if not href or href.startswith(("#","javascript:","mailto:","tel:")):
            continue
        u=urljoin(url,href)
        u,_=urldefrag(u)
        if same_domain(url,u):
            links.append(u)

    return {
        "url":url,
        "title":title,
        "headings":list(dict.fromkeys(headings))[:30],
        "candidates":list(dict.fromkeys(cands))[:250],
        "links":list(dict.fromkeys(links))[:300],
    }


def crawl(start,max_pages=15):
    q=deque([start]); seen=set(); pages=[]
    while q and len(pages)<max_pages:
        u=q.popleft()
        if u in seen: continue
        seen.add(u)
        try:
            html=fetch(u)
            if not html: continue
            p=parse_page(html,u); pages.append(p)
            for link in p["links"]:
                path=urlparse(link).path.lower()
                if re.search(r"\.(jpg|jpeg|png|gif|webp|pdf|zip|rar|mp4|mp3|css|js|xml)$",path):
                    continue
                if link not in seen: q.append(link)
            time.sleep(0.12)
        except:
            continue
    return pages


def guess_category(page):
    for h in page["headings"]:
        if 2<=len(h)<=30 and h not in NOISE:
            return h
    return "미분류"


def extract_entities(pages):
    rows=[]
    for p in pages:
        cat=guess_category(p)
        local=set()
        for raw in p["candidates"]:
            v=clean_name(raw)
            if not (2<=len(v)<=50): continue
            if v in NOISE: continue
            if re.fullmatch(r"[\d\s,.\-~%원₩]+",v): continue
            if v in local: continue
            local.add(v)
            rows.append([cat,v,raw,p["url"]])
    df=pd.DataFrame(rows,columns=["카테고리","메인명","원문","출처 URL"])
    if not df.empty:
        df=df.drop_duplicates(subset=["카테고리","메인명"]).reset_index(drop=True)
    return df


def auto_detect_industry(entities):
    text=" ".join(entities["메인명"].astype(str).tolist()[:300]) if not entities.empty else ""
    checks=[
        ("식물/조경",r"나무|묘목|모종|수국|장미|조경|정원|화훼|식물"),
        ("법률",r"회생|파산|변호사|법률|소송|이혼|형사"),
        ("교육/자격증",r"자격증|교육|수강|학점|과정|사회복지"),
        ("렌탈",r"렌탈|정수기|공기청정기|매트리스"),
        ("자동차/화물차",r"자동차|화물차|포터|봉고|리스|렌트"),
        ("부동산",r"아파트|분양|매매|전세|월세|부동산"),
        ("식품/B2B",r"소스|식품|납품|도매|식자재"),
    ]
    for name,pat in checks:
        if re.search(pat,text,re.I):
            return name
    return "기타"


def parse_list(text):
    return [clean(x) for x in re.split(r"[,/\n]+",text or "") if clean(x)]


def dedupe_keep_order(items):
    out=[]; seen=set()
    for x in items:
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out


def intent_score(k):
    score=1; reason=[]
    for term,w in PURCHASE_TERMS.items():
        if term in k:
            score+=w; reason.append(term)
    for term,w in INFO_TERMS.items():
        if term in k:
            score-=w; reason.append(term)
    if score>=6: label="매우높음"
    elif score>=4: label="높음"
    elif score>=2: label="중간"
    else: label="낮음"
    return label,score,reason


def search_potential(k,base):
    extra=max(0,len(k)-len(base))
    score=5
    if k==base: score+=3
    if extra>=8: score-=1
    if extra>=14: score-=1
    suffix_hits=sum(1 for t in list(PURCHASE_TERMS)+list(INFO_TERMS) if t in k.replace(base,"",1))
    if suffix_hits>=2: score-=2
    if score>=7:return "높음"
    if score>=5:return "중간"
    return "낮음"


def classify(k,base,kind):
    intent,score,reasons=intent_score(k)
    sp=search_potential(k,base)
    if k==base: group="핵심"
    elif kind=="정보": group="정보형"
    elif intent in ("매우높음","높음") and sp=="낮음": group="롱테일 고의도"
    elif intent in ("매우높음","높음"): group="고의도"
    elif intent=="중간": group="테스트"
    else: group="검토"
    return group,intent,sp,", ".join(sorted(set(reasons)))


def make_keywords(entities,combos,include_info,include_longtail):
    rows=[]; seen=set()
    info_combos=["후기","방법","관리법","비교"]
    all_combos=[("일반",x) for x in combos]
    if include_info:
        all_combos += [("정보",x) for x in info_combos]

    for _,r in entities.iterrows():
        base=str(r["메인명"]); cat=str(r["카테고리"])
        candidates=[("핵심","",base)]
        for typ,suf in all_combos:
            candidates.append((typ,suf,base+suf))

        if include_longtail:
            long_pairs=[
                ("구매","배송"),("판매","택배"),("가격","비교"),
                ("주문","배송"),("상담","비용"),("업체","가격")
            ]
            for s1,s2 in long_pairs:
                candidates.append(("롱테일",f"{s1}+{s2}",base+s1+s2))

        for typ,suf,k in candidates:
            key=(cat,base,k)
            if key in seen: continue
            seen.add(key)
            group,intent,sp,reason=classify(k,base,typ)
            rows.append([cat,base,k,group,intent,sp,suf if suf else "(단독)",reason,r["출처 URL"]])

    return pd.DataFrame(rows,columns=[
        "카테고리","메인명","추천 키워드","분류","전환 의도","검색량 잠재치","조합","판단 근거","출처 URL"
    ])


def excel_bytes(entities,keywords,purpose,industry,combos):
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:
        entities.to_excel(writer,sheet_name="대표명",index=False)
        keywords.to_excel(writer,sheet_name="전체키워드",index=False)
        for g in ["핵심","고의도","롱테일 고의도","정보형","테스트","검토"]:
            part=keywords[keywords["분류"]==g]
            if not part.empty:
                part.to_excel(writer,sheet_name=g[:31],index=False)
        summary=keywords.groupby(["분류","전환 의도","검색량 잠재치"]).size().reset_index(name="키워드 수")
        summary.to_excel(writer,sheet_name="요약",index=False)
        pd.DataFrame([
            ["추출 목적",purpose],
            ["업종",industry],
            ["사용 조합어",", ".join(combos)],
        ],columns=["설정","값"]).to_excel(writer,sheet_name="실행설정",index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes="A2"
            for c in ws[1]:
                c.font=c.font.copy(bold=True)
            for col in ws.columns:
                letter=col[0].column_letter
                mx=max([len(str(c.value)) if c.value is not None else 0 for c in col[:200]]+[10])
                ws.column_dimensions[letter].width=min(max(mx+2,12),42)
    return out.getvalue()


st.title("🔎 검색광고 키워드 추출기 v3")
st.write("사이트 주소를 넣고 **목적만 선택하면 추천 조합어까지 자동으로 제안**합니다.")

with st.container(border=True):
    url=st.text_input("① 분석할 사이트 주소",placeholder="https://example.com")

    purpose=st.selectbox("② 무엇을 하실 건가요?",list(PURPOSE_PRESETS.keys()))
    st.caption(PURPOSE_PRESETS[purpose]["desc"])

    industry=st.selectbox("③ 업종",list(INDUSTRY_PRESETS.keys()))

    recommended = PURPOSE_PRESETS[purpose]["base"] + INDUSTRY_PRESETS.get(industry,[])
    recommended = dedupe_keep_order(recommended)

    st.markdown("#### ④ 추천 조합어")
    st.caption("직접 생각하실 필요 없습니다. 아래 추천값을 그대로 쓰셔도 됩니다.")
    combo_text=st.text_area(
        "추천 조합어",
        value=", ".join(recommended),
        height=90,
        help="필요 없는 단어는 지우고, 원하는 단어는 추가하셔도 됩니다."
    )

    c1,c2=st.columns(2)
    with c1:
        include_longtail=st.checkbox("롱테일 고의도 키워드 자동 생성",value=True)
    with c2:
        include_info=st.checkbox("정보성 키워드도 함께 분류",value=True)

    analyze=st.button("🚀 자동 추출 시작",type="primary",use_container_width=True)

if analyze:
    if not url.strip():
        st.error("사이트 주소를 입력해 주세요.")
        st.stop()

    start=norm_url(url)
    combos=parse_list(combo_text)

    bar=st.progress(0,text="사이트를 확인하고 있습니다...")
    pages=crawl(start,15)
    bar.progress(40,text=f"{len(pages)}개 페이지 확인 완료. 대표명을 정리하고 있습니다...")

    if not pages:
        st.error("사이트를 읽지 못했습니다.")
        st.stop()

    entities=extract_entities(pages)
    if entities.empty:
        st.error("대표 상품/서비스명을 찾지 못했습니다.")
        st.stop()

    detected=auto_detect_industry(entities)
    actual_industry = detected if industry=="자동 감지" else industry

    if industry=="자동 감지":
        auto_extra=INDUSTRY_PRESETS.get(detected,[])
        combos=dedupe_keep_order(combos+auto_extra)

    bar.progress(70,text="추천 키워드를 생성하고 전환 의도를 분류하고 있습니다...")
    keywords=make_keywords(entities,combos,include_info,include_longtail)
    data=excel_bytes(entities,keywords,purpose,actual_industry,combos)
    bar.progress(100,text="완료")

    st.success(f"완료되었습니다. 감지 업종: **{actual_industry}**")

    a,b,c,d=st.columns(4)
    a.metric("확인 페이지",f"{len(pages):,}")
    b.metric("대표명",f"{len(entities):,}")
    c.metric("전체 키워드",f"{len(keywords):,}")
    d.metric("롱테일 고의도",f"{(keywords['분류']=='롱테일 고의도').sum():,}")

    tabs=st.tabs(["추천 키워드","롱테일 고의도","대표명","사용된 조합어"])
    with tabs[0]:
        st.dataframe(keywords,use_container_width=True,height=420)
    with tabs[1]:
        st.dataframe(keywords[keywords["분류"]=="롱테일 고의도"],use_container_width=True,height=360)
    with tabs[2]:
        st.dataframe(entities,use_container_width=True,height=360)
    with tabs[3]:
        st.write(", ".join(combos))

    st.download_button(
        "📥 엑셀 다운로드",
        data=data,
        file_name="검색광고_키워드_추출결과_v3.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    st.caption("※ 검색량 잠재치는 실제 네이버 월간 검색량이 아니라 구조적 추정치입니다.")
