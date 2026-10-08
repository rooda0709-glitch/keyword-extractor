
import base64
import hashlib
import hmac
import io
import re
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="검색광고 키워드 크로스체크 v4", page_icon="🔎", layout="wide")

NAVER_API_BASE = "https://api.searchad.naver.com"

PURPOSE_PRESETS = {
    "네이버 파워링크 신규 세팅": ["구매","판매","가격","비용","견적","상담","신청","주문","배송","택배","업체","전문업체"],
    "기존 파워링크 키워드 확장": ["가격","비용","견적","상담","신청","추천","비교","업체","전문","구매","판매"],
    "쇼핑검색광고 키워드 발굴": ["구매","판매","가격","최저가","주문","온라인주문","배송","택배","할인"],
    "시장/경쟁사 키워드 조사": ["가격","비용","비교","추천","후기","업체","전문업체","상담"],
}

INDUSTRY_PRESETS = {
    "자동 감지": [],
    "식물/조경": ["묘목","모종","정원수","조경수","농장","전문농장","식재","키우기","관리법","월동"],
    "법률": ["변호사","법률상담","상담","비용","수임료","신청","전문"],
    "교육/자격증": ["자격증","수강","교육","온라인","비용","가격","신청","과정"],
    "렌탈": ["렌탈","가격","비용","견적","비교","신청","설치","상담"],
    "자동차/화물": ["가격","견적","구매","판매","리스","렌트","할부","상담"],
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
    "구매":4,"판매":4,"가격":2,"비용":2,"견적":4,"상담":4,"신청":4,"주문":4,
    "온라인주문":4,"배송":2,"택배":2,"업체":3,"전문업체":3,"농장":3,"전문농장":3,
    "묘목":3,"모종":3,"정원수":3,"조경수":3,"렌탈":4,"리스":4,"렌트":4,
    "예약":4,"도매":4,"대량":3,"납품":4,"수강":3,"변호사":3,"법률상담":4,
}
INFO_TERMS = {
    "키우기":3,"키우는법":3,"관리":2,"관리법":3,"물주기":3,"가지치기":3,
    "심는법":3,"월동":2,"재배":2,"재배법":3,"후기":2,"뜻":3,"효능":3,
    "사진":2,"방법":2,"정보":2,"장단점":2
}

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def parse_list(text):
    vals = re.split(r"[,/\n]+", text or "")
    return [clean(x) for x in vals if clean(x)]

def dedupe(items):
    out, seen = [], set()
    for x in items:
        x = clean(x)
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

def norm_url(url):
    url = clean(url)
    if not url:
        return ""
    if not url.startswith(("http://","https://")):
        url = "https://" + url
    return url

def same_domain(a,b):
    return urlparse(a).netloc.lower().replace("www.","") == urlparse(b).netloc.lower().replace("www.","")

def naver_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")

def naver_headers(method, uri, api_key, secret_key, customer_id):
    timestamp = str(int(time.time() * 1000))
    return {
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": naver_signature(timestamp, method, uri, secret_key),
        "Content-Type": "application/json; charset=UTF-8",
    }

def naver_keyword_tool(seed, api_key, secret_key, customer_id, show_detail=True):
    uri = "/keywordstool"
    params = {"hintKeywords": seed, "showDetail": "1" if show_detail else "0"}
    headers = naver_headers("GET", uri, api_key, secret_key, customer_id)
    r = requests.get(NAVER_API_BASE + uri, headers=headers, params=params, timeout=20)
    if r.status_code == 429:
        raise RuntimeError("네이버 API 호출 한도를 초과했습니다(429). 잠시 후 다시 시도해 주세요.")
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        raise RuntimeError(f"네이버 API 오류 {r.status_code}: {detail}")
    data = r.json()
    rows = data.get("keywordList", [])
    out = []
    for x in rows:
        out.append({
            "키워드": clean(x.get("relKeyword")),
            "PC월간검색수": x.get("monthlyPcQcCnt"),
            "모바일월간검색수": x.get("monthlyMobileQcCnt"),
            "PC월평균클릭수": x.get("monthlyAvePcClkCnt"),
            "모바일월평균클릭수": x.get("monthlyAveMobileClkCnt"),
            "PC월평균CTR": x.get("monthlyAvePcCtr"),
            "모바일월평균CTR": x.get("monthlyAveMobileCtr"),
            "평균광고수": x.get("plAvgDepth"),
            "경쟁정도": x.get("compIdx"),
            "네이버기준키워드": seed,
        })
    return pd.DataFrame(out)

def connection_test(api_key, secret_key, customer_id):
    df = naver_keyword_tool("테스트", api_key, secret_key, customer_id, show_detail=False)
    return True, len(df)

def clean_name(s):
    s = clean(s)
    s = re.sub(r"\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}", " ", s)
    s = re.sub(r"\b\d+(?:\.\d+)?\s*(?:cm|mm|m|kg|g|L|ml|호|개|입|팩|set|SET)\b", " ", s, flags=re.I)
    s = re.sub(r"\b(?:무료배송|당일배송|특가|할인|세일|신상품|베스트|추천|한정|품절|예약)\b", " ", s)
    s = re.sub(r"[|/·,:;!★☆▶▷→]+", " ", s)
    return clean(s)[:80]

def fetch(url):
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (KeywordCrosscheck/4.0)"})
    r.raise_for_status()
    if "text/html" not in r.headers.get("content-type", ""):
        return ""
    return r.text

def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","noscript","svg"]):
        tag.decompose()
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    headings = [clean(x.get_text(" ",strip=True)) for x in soup.find_all(["h1","h2","h3"])]
    headings = [x for x in headings if x]
    candidates = []
    selectors = [
        '[class*="product"] [class*="name"]','[class*="goods"] [class*="name"]',
        '[class*="item"] [class*="name"]','[class*="product"] a','[class*="goods"] a',
        '[class*="item"] a','[class*="category"] a','[class*="cate"] a',
        'h1','h2','h3','h4','main a',
    ]
    for sel in selectors:
        try:
            for el in soup.select(sel)[:250]:
                txt = clean(el.get_text(" ", strip=True))
                if 2 <= len(txt) <= 100:
                    candidates.append(txt)
        except Exception:
            pass
    for img in soup.find_all("img")[:180]:
        alt = clean(img.get("alt", ""))
        if 2 <= len(alt) <= 100:
            candidates.append(alt)
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#","javascript:","mailto:","tel:")):
            continue
        u = urljoin(url, href)
        u, _ = urldefrag(u)
        if same_domain(url, u):
            links.append(u)
    return {"url":url,"title":title,"headings":dedupe(headings)[:40],"candidates":dedupe(candidates)[:300],"links":dedupe(links)[:400]}

def crawl(start, max_pages=20):
    q = deque([start])
    seen, pages = set(), []
    while q and len(pages) < max_pages:
        u = q.popleft()
        if u in seen:
            continue
        seen.add(u)
        try:
            html = fetch(u)
            if not html:
                continue
            p = parse_page(html, u)
            pages.append(p)
            preferred, normal = [], []
            for link in p["links"]:
                path = urlparse(link).path.lower()
                if re.search(r"\.(jpg|jpeg|png|gif|webp|pdf|zip|rar|mp4|mp3|css|js|xml)$", path):
                    continue
                if re.search(r"product|goods|item|category|cate|shop|store|service|course|program", link, re.I):
                    preferred.append(link)
                else:
                    normal.append(link)
            for link in reversed(preferred):
                if link not in seen:
                    q.appendleft(link)
            for link in normal:
                if link not in seen:
                    q.append(link)
            time.sleep(0.12)
        except Exception:
            continue
    return pages

def guess_category(page):
    for h in page["headings"]:
        if 2 <= len(h) <= 32 and h not in NOISE:
            return h
    return "미분류"

def extract_site_entities(pages, seed_keywords):
    rows = []
    seed_keywords = [x.lower() for x in seed_keywords]
    for p in pages:
        cat = guess_category(p)
        local = set()
        for raw in p["candidates"]:
            v = clean_name(raw)
            if not (2 <= len(v) <= 60):
                continue
            if v in NOISE or re.fullmatch(r"[\d\s,.\-~%원₩]+", v):
                continue
            if v in local:
                continue
            local.add(v)
            lv = v.lower()
            exact_seed_hit = any(seed == lv for seed in seed_keywords)
            partial_seed_hit = any(seed in lv or lv in seed for seed in seed_keywords if len(seed) >= 2)
            if exact_seed_hit:
                rel, rel_score = "기준키워드 직접일치", 5
            elif partial_seed_hit:
                rel, rel_score = "기준키워드 연관후보", 4
            else:
                rel, rel_score = "사이트 고유후보", 2
            rows.append({
                "카테고리": cat,"사이트후보": v,"원문": raw,
                "사이트관련성": rel,"사이트관련성점수": rel_score,"출처 URL": p["url"],
            })
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["카테고리","사이트후보"]).reset_index(drop=True) if not df.empty else df

def detect_industry(site_df):
    if site_df.empty:
        return "기타"
    text = " ".join(site_df["사이트후보"].astype(str).tolist()[:600])
    checks = [
        ("식물/조경", r"나무|묘목|모종|수국|장미|조경|정원|화훼|식물|구상|배롱"),
        ("법률", r"회생|파산|변호사|법률|소송|이혼|형사|채무"),
        ("교육/자격증", r"자격증|교육|수강|학점|과정|사회복지"),
        ("렌탈", r"렌탈|정수기|공기청정기|매트리스"),
        ("자동차/화물", r"자동차|화물차|포터|봉고|리스|렌트"),
        ("부동산", r"아파트|분양|매매|전세|월세|부동산"),
        ("식품/B2B", r"소스|식품|납품|도매|식자재"),
    ]
    for name, pat in checks:
        if re.search(pat, text, re.I):
            return name
    return "기타"

def numeric_search_count(v):
    if v is None:
        return 0
    if isinstance(v, (int,float)):
        return int(v)
    s = str(v).strip()
    if "<" in s:
        nums = re.findall(r"\d+", s)
        return max((int(nums[0]) - 1), 0) if nums else 0
    nums = re.findall(r"\d+", s.replace(",",""))
    return int(nums[0]) if nums else 0

def purchase_intent(keyword):
    score = 1
    reasons = []
    for t,w in PURCHASE_TERMS.items():
        if t in keyword:
            score += w
            reasons.append(t)
    for t,w in INFO_TERMS.items():
        if t in keyword:
            score -= w
            reasons.append(t)
    if score >= 7:
        label = "매우높음"
    elif score >= 4:
        label = "높음"
    elif score >= 2:
        label = "중간"
    else:
        label = "낮음"
    return label, score, reasons

def merge_naver_frames(frames):
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df
    df["PC수치"] = df["PC월간검색수"].apply(numeric_search_count)
    df["모바일수치"] = df["모바일월간검색수"].apply(numeric_search_count)
    df["총월간검색수"] = df["PC수치"] + df["모바일수치"]
    agg = {
        "PC월간검색수":"first","모바일월간검색수":"first",
        "PC월평균클릭수":"first","모바일월평균클릭수":"first",
        "PC월평균CTR":"first","모바일월평균CTR":"first",
        "평균광고수":"first","경쟁정도":"first",
        "네이버기준키워드": lambda s: ", ".join(dedupe(s.astype(str).tolist())),
        "총월간검색수":"max",
    }
    return df.groupby("키워드", as_index=False).agg(agg)

def build_crosscheck(site_df, naver_df, seed_keywords, purpose, industry, custom_suffixes):
    seed_keywords = dedupe(seed_keywords)
    seed_set = set(seed_keywords)
    site_set = set(site_df["사이트후보"].tolist()) if not site_df.empty else set()
    naver_set = set(naver_df["키워드"].tolist()) if not naver_df.empty else set()

    base_suffixes = dedupe(PURPOSE_PRESETS[purpose] + INDUSTRY_PRESETS.get(industry, []) + custom_suffixes)
    generated = set()
    for base in dedupe(list(seed_keywords) + list(site_set)):
        if len(base) > 24:
            continue
        for suf in base_suffixes:
            if suf and not base.endswith(suf):
                generated.add(base + suf)

    all_keywords = dedupe(list(seed_keywords) + list(naver_set) + list(site_set) + list(generated))
    naver_lookup = naver_df.set_index("키워드").to_dict("index") if not naver_df.empty else {}
    rows = []

    for kw in all_keywords:
        in_seed = kw in seed_set
        in_site = kw in site_set
        in_naver = kw in naver_set
        in_generated = kw in generated
        nv = naver_lookup.get(kw, {})
        total_search = int(nv.get("총월간검색수", 0) or 0)

        intent_label, intent_score, intent_reasons = purchase_intent(kw)

        confidence = 0
        evidence = []
        if in_seed:
            confidence += 30; evidence.append("사용자 기준키워드")
        if in_site:
            confidence += 25; evidence.append("사이트 추출")
        if in_naver:
            confidence += 30; evidence.append("네이버 연관키워드")
        if in_generated:
            confidence += 8; evidence.append("프로그램 조합")

        if total_search >= 10000:
            confidence += 12
        elif total_search >= 1000:
            confidence += 9
        elif total_search >= 100:
            confidence += 6
        elif total_search > 0:
            confidence += 3

        if intent_label == "매우높음":
            confidence += 10
        elif intent_label == "높음":
            confidence += 7
        elif intent_label == "중간":
            confidence += 3

        confidence = min(confidence, 100)

        if in_site and in_naver and (in_seed or confidence >= 70):
            final_class = "최우선"
        elif in_naver and intent_label in ("매우높음","높음") and total_search < 100:
            final_class = "롱테일 고의도"
        elif in_naver and in_seed:
            final_class = "확장 추천"
        elif in_site and in_naver:
            final_class = "신뢰도 높음"
        elif in_site and not in_naver:
            final_class = "사이트 고유 상품/서비스"
        elif in_naver and not in_site:
            final_class = "네이버 신규 확장 후보"
        elif in_generated and intent_label in ("매우높음","높음"):
            final_class = "조합 테스트 후보"
        elif any(t in kw for t in INFO_TERMS):
            final_class = "정보형"
        else:
            final_class = "검토 필요"

        rows.append({
            "키워드": kw,"최종분류": final_class,"신뢰도점수": confidence,
            "전환의도": intent_label,"전환의도점수": intent_score,
            "사용자기준": "O" if in_seed else "","사이트추출": "O" if in_site else "",
            "네이버연관어": "O" if in_naver else "","프로그램조합": "O" if in_generated else "",
            "PC월간검색수": nv.get("PC월간검색수", ""),"모바일월간검색수": nv.get("모바일월간검색수", ""),
            "총월간검색수": total_search if in_naver else "","경쟁정도": nv.get("경쟁정도", ""),
            "평균광고수": nv.get("평균광고수", ""),"네이버기준키워드": nv.get("네이버기준키워드", ""),
            "판단근거": ", ".join(evidence),"의도어": ", ".join(dedupe(intent_reasons)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        class_order = {
            "최우선":1,"신뢰도 높음":2,"확장 추천":3,"롱테일 고의도":4,
            "네이버 신규 확장 후보":5,"사이트 고유 상품/서비스":6,
            "조합 테스트 후보":7,"정보형":8,"검토 필요":9,
        }
        df["_order"] = df["최종분류"].map(class_order).fillna(99)
        df = df.sort_values(["_order","신뢰도점수","총월간검색수"], ascending=[True,False,False]).drop(columns=["_order"]).reset_index(drop=True)
    return df

def excel_bytes(site_df, naver_df, cross_df, seeds, purpose, industry):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        cross_df.to_excel(writer, sheet_name="최종 크로스체크", index=False)
        site_df.to_excel(writer, sheet_name="사이트 추출 원본", index=False)
        naver_df.to_excel(writer, sheet_name="네이버 API 원본", index=False)
        for cls in ["최우선","신뢰도 높음","확장 추천","롱테일 고의도","네이버 신규 확장 후보","사이트 고유 상품서비스","조합 테스트 후보","정보형","검토 필요"]:
            target = "사이트 고유 상품/서비스" if cls == "사이트 고유 상품서비스" else cls
            part = cross_df[cross_df["최종분류"] == target]
            if not part.empty:
                part.to_excel(writer, sheet_name=cls[:31], index=False)
        pd.DataFrame({
            "설정":["추출 목적","업종","기준키워드"],
            "값":[purpose, industry, ", ".join(seeds)]
        }).to_excel(writer, sheet_name="실행 설정", index=False)
        pd.DataFrame([
            ["네이버 API 원본","네이버 검색광고 API에서 반환된 데이터"],
            ["사이트 추출 원본","입력한 홈페이지에서 프로그램이 추출한 자체 데이터"],
            ["프로그램조합","목적/업종/조합어 규칙으로 프로그램이 생성한 자체 후보"],
            ["최종 크로스체크","위 데이터들을 비교해 프로그램이 분류한 결과"],
        ], columns=["구분","설명"]).to_excel(writer, sheet_name="데이터 출처 안내", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for c in ws[1]:
                c.font = c.font.copy(bold=True)
            for col in ws.columns:
                letter = col[0].column_letter
                mx = max([len(str(c.value)) if c.value is not None else 0 for c in col[:300]] + [10])
                ws.column_dimensions[letter].width = min(max(mx + 2, 12), 42)
    return out.getvalue()

st.title("🔎 검색광고 키워드 크로스체크 v4")
st.write("사이트만 긁는 방식이 아니라 **기준키워드 + 네이버 키워드 도구 + 사이트 추출값**을 서로 비교합니다.")

for key in ["naver_api_key","naver_secret_key","naver_customer_id"]:
    if key not in st.session_state:
        st.session_state[key] = ""

with st.expander("🔐 1. 네이버 검색광고 API 연결", expanded=True):
    st.caption("입력한 인증정보는 현재 앱 세션에서만 사용하며 엑셀에는 저장하지 않습니다.")
    c1, c2 = st.columns(2)
    with c1:
        api_key = st.text_input("Access License / API Key", type="password", value=st.session_state["naver_api_key"], key="api_key_input")
        customer_id = st.text_input("Customer ID", value=st.session_state["naver_customer_id"], key="customer_input")
    with c2:
        secret_key = st.text_input("Secret Key", type="password", value=st.session_state["naver_secret_key"], key="secret_input")

    if st.button("네이버 API 연결 테스트"):
        if not api_key or not secret_key or not customer_id:
            st.error("Access License, Secret Key, Customer ID를 모두 입력해 주세요.")
        else:
            try:
                ok, count = connection_test(api_key, secret_key, customer_id)
                st.session_state["naver_api_key"] = api_key
                st.session_state["naver_secret_key"] = secret_key
                st.session_state["naver_customer_id"] = customer_id
                st.success(f"연결되었습니다. 키워드 도구 응답 확인 완료 ({count}개 결과).")
            except Exception as e:
                st.error(str(e))

with st.container(border=True):
    st.subheader("2. 추출 조건")
    url = st.text_input("분석할 사이트 URL", placeholder="https://example.com")
    purpose = st.selectbox("추출 목적", list(PURPOSE_PRESETS.keys()))
    industry = st.selectbox("업종", list(INDUSTRY_PRESETS.keys()))
    seeds_text = st.text_area(
        "기준키워드 (권장 3~20개)",
        placeholder="예: 수국, 구상나무, 배롱나무, 묘목, 정원수",
        height=100,
        help="사이트의 핵심 상품/서비스를 대표하는 단어를 적어주세요.",
    )
    base_recommend = dedupe(PURPOSE_PRESETS[purpose] + INDUSTRY_PRESETS.get(industry, []))
    custom_text = st.text_area(
        "추천 조합어",
        value=", ".join(base_recommend),
        height=90,
        help="기본 추천값을 그대로 사용해도 됩니다.",
    )
    c1, c2 = st.columns(2)
    with c1:
        max_pages = st.slider("사이트 확인 페이지 수", 5, 50, 20, 5)
    with c2:
        naver_seed_limit = st.slider("네이버 API 조회 기준키워드 수", 1, 20, 10, 1)
    run = st.button("🚀 사이트 + 네이버 크로스체크 시작", type="primary", use_container_width=True)

if run:
    seeds = dedupe(parse_list(seeds_text))
    custom_suffixes = dedupe(parse_list(custom_text))
    if not url.strip():
        st.error("사이트 URL을 입력해 주세요.")
        st.stop()
    if not seeds:
        st.error("기준키워드를 최소 1개 입력해 주세요.")
        st.stop()

    api_key = api_key or st.session_state["naver_api_key"]
    secret_key = secret_key or st.session_state["naver_secret_key"]
    customer_id = customer_id or st.session_state["naver_customer_id"]

    if not (api_key and secret_key and customer_id):
        st.error("먼저 네이버 API 인증정보를 입력해 주세요.")
        st.stop()

    st.session_state["naver_api_key"] = api_key
    st.session_state["naver_secret_key"] = secret_key
    st.session_state["naver_customer_id"] = customer_id

    progress = st.progress(0, text="사이트를 분석하고 있습니다...")
    pages = crawl(norm_url(url), max_pages=max_pages)
    progress.progress(28, text=f"사이트 {len(pages)}개 페이지 확인 완료. 후보를 정리합니다...")

    if not pages:
        st.error("사이트 페이지를 읽지 못했습니다.")
        st.stop()

    site_df = extract_site_entities(pages, seeds)
    detected_industry = detect_industry(site_df)
    actual_industry = detected_industry if industry == "자동 감지" else industry

    progress.progress(45, text=f"업종: {actual_industry}. 네이버 키워드 도구를 조회합니다...")

    frames, errors = [], []
    limit = min(len(seeds), naver_seed_limit)
    for i, seed in enumerate(seeds[:limit]):
        try:
            frames.append(naver_keyword_tool(seed, api_key, secret_key, customer_id, show_detail=True))
            time.sleep(0.12)
        except Exception as e:
            errors.append(f"{seed}: {e}")
        pct = 45 + int(35 * ((i + 1) / max(1, limit)))
        progress.progress(min(pct, 80), text=f"네이버 조회 중: {i+1}/{limit}")

    naver_df = merge_naver_frames(frames)
    if naver_df.empty:
        st.error("네이버 키워드 도구 결과를 가져오지 못했습니다.")
        if errors:
            st.code("\n".join(errors[:10]))
        st.stop()

    progress.progress(85, text="사이트/기준키워드/네이버 데이터를 크로스체크합니다...")

    if industry == "자동 감지":
        custom_suffixes = dedupe(custom_suffixes + INDUSTRY_PRESETS.get(actual_industry, []))

    cross_df = build_crosscheck(site_df, naver_df, seeds, purpose, actual_industry, custom_suffixes)
    xlsx = excel_bytes(site_df, naver_df, cross_df, seeds, purpose, actual_industry)
    progress.progress(100, text="완료")

    if errors:
        st.warning("일부 기준키워드는 네이버 조회에 실패했습니다.\n\n" + "\n".join(errors[:5]))

    st.success(f"완료되었습니다. 인식 업종: **{actual_industry}**")

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("사이트 후보", f"{len(site_df):,}")
    c2.metric("네이버 연관어", f"{len(naver_df):,}")
    c3.metric("전체 후보", f"{len(cross_df):,}")
    c4.metric("최우선", f"{(cross_df['최종분류']=='최우선').sum():,}")
    c5.metric("롱테일 고의도", f"{(cross_df['최종분류']=='롱테일 고의도').sum():,}")

    tabs = st.tabs(["⭐ 최종 추천","🎯 최우선","🪴 사이트 추출","N 네이버 API","📌 롱테일 고의도","🔍 검토 필요"])
    with tabs[0]:
        st.dataframe(cross_df, use_container_width=True, height=520)
    with tabs[1]:
        st.dataframe(cross_df[cross_df["최종분류"]=="최우선"], use_container_width=True, height=400)
    with tabs[2]:
        st.dataframe(site_df, use_container_width=True, height=400)
    with tabs[3]:
        st.info("아래 표는 네이버 검색광고 API에서 받은 원본 데이터입니다.")
        st.dataframe(naver_df, use_container_width=True, height=460)
    with tabs[4]:
        st.dataframe(cross_df[cross_df["최종분류"]=="롱테일 고의도"], use_container_width=True, height=400)
    with tabs[5]:
        st.dataframe(cross_df[cross_df["최종분류"]=="검토 필요"], use_container_width=True, height=400)

    st.download_button(
        "📥 크로스체크 결과 Excel 다운로드",
        data=xlsx,
        file_name="검색광고_키워드_크로스체크_v4.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.caption("네이버 검색량/경쟁 데이터는 네이버 검색광고 API 응답이며, 사이트 추출/신뢰도/전환의도/최종분류는 프로그램 자체 분석값입니다.")
