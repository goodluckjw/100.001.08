import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import re
import os
import unicodedata
from collections import defaultdict

OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"

def get_law_list_from_api(query):
    exact_query = f'"{query}"'
    encoded_query = quote(exact_query)
    page = 1
    laws = []
    while True:
        url = f"{BASE}/DRF/lawSearch.do?OC={OC}&target=law&type=XML&display=100&page={page}&search=2&knd=A0002&query={encoded_query}"
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            break
        root = ET.fromstring(res.content)
        for law in root.findall("law"):
            laws.append({
                "법령명": law.findtext("법령명한글", "").strip(),
                "MST": law.findtext("법령일련번호", "")
            })
        total_count = int(root.findtext("totalCnt", "0"))
        if len(laws) >= total_count:
            break
        page += 1
    return laws

def get_law_text_by_mst(mst):
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&MST={mst}&type=XML"
    try:
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        return res.content if res.status_code == 200 else None
    except:
        return None

def clean(text):
    return re.sub(r"\s+", "", text or "")

def 조사_을를(word):
    if not word:
        return "을"
    code = ord(word[-1]) - 0xAC00
    jong = code % 28
    return "를" if jong == 0 else "을"

def 조사_으로로(word):
    if not word:
        return "으로"
    code = ord(word[-1]) - 0xAC00
    jong = code % 28
    return "로" if jong == 0 or jong == 8 else "으로"

def highlight(text, keyword):
    return text.replace(keyword, f"<span style='color:red'>{keyword}</span>") if text else ""

def remove_unicode_number_prefix(text):
    return re.sub(r"^[①-⑳]+", "", text)

def run_search_logic(query, unit):
    result_dict = {}
    keyword_clean = clean(query)

    for law in get_law_list_from_api(query):
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue

        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        law_results = []

        for article in articles:
            조내용 = article.findtext("조문내용") or ""
            항들 = article.findall("항")
            출력덩어리 = []
            첫_항출력됨 = False
            첫_항내용_텍스트 = ""

            조출력 = keyword_clean in clean(조내용)
            if 조출력:
                출력덩어리.append(highlight(조내용, query))

            for 항 in 항들:
                항내용 = 항.findtext("항내용") or ""
                항내용 = remove_unicode_number_prefix(항내용.strip())
                항출력 = keyword_clean in clean(항내용)
                항덩어리 = []
                호출력된 = False

                for 호 in 항.findall("호"):
                    호내용 = 호.findtext("호내용") or ""
                    if keyword_clean in clean(호내용):
                        if not 항출력:
                            항덩어리.append(highlight(항내용, query))
                            항출력 = True
                        항덩어리.append("&nbsp;&nbsp;" + highlight(호내용, query))
                        호출력된 = True

                    for 목 in 호.findall("목"):
                        목내용_list = 목.findall("목내용")
                        if 목내용_list:
                            combined_lines = []
                            for m in 목내용_list:
                                if m.text and keyword_clean in clean(m.text):
                                    combined_lines.extend([
                                        highlight(line.strip(), query)
                                        for line in m.text.splitlines() if line.strip()
                                    ])
                            if combined_lines:
                                if not 항출력:
                                    항덩어리.append(highlight(항내용, query))
                                    항출력 = True
                                if not 호출력된:
                                    항덩어리.append("&nbsp;&nbsp;" + highlight(호내용, query))
                                항덩어리.extend(["&nbsp;&nbsp;&nbsp;&nbsp;" + l for l in combined_lines])

                if 항출력 or 항덩어리:
                    if not 조출력 and not 첫_항출력됨:
                        if 항덩어리:
                            출력덩어리.append(highlight(조내용, query) + " " + 항덩어리[0])
                            출력덩어리.extend(항덩어리[1:])
                        else:
                            출력덩어리.append(highlight(조내용, query) + " " + highlight(항내용, query))
                        첫_항내용_텍스트 = 항내용.strip()
                        첫_항출력됨 = True
                        조출력 = True
                    elif 항내용.strip() != 첫_항내용_텍스트:
                        if 항출력:
                            출력덩어리.append(highlight(항내용, query))
                        출력덩어리.extend(항덩어리)

            if 출력덩어리:
                law_results.append("<br>".join(출력덩어리))

        if law_results:
            result_dict[law["법령명"]] = law_results

    return result_dict

def extract_locations(xml_data, keyword):
    tree = ET.fromstring(xml_data)
    articles = tree.findall(".//조문단위")
    keyword_clean = clean(keyword)
    locations = defaultdict(list)

    for article in articles:
        조 = article.findtext("조문번호", "").strip()
        조제목 = article.findtext("조문제목", "") or ""
        조내용 = article.findtext("조문내용", "") or ""

        if keyword_clean in clean(조제목):
            locations["제" + 조 + "조 제목"].append((조제목.strip(), keyword))
        if keyword_clean in clean(조내용):
            locations["제" + 조 + "조"].append((조내용.strip(), keyword))

        for 항 in article.findall("항"):
            항번호 = 항.findtext("항번호", "").strip()
            항내용 = 항.findtext("항내용", "") or ""
            if keyword_clean in clean(항내용):
                clean_text = remove_unicode_number_prefix(항내용.strip())
                locations[f"제{조}조제{항번호}항"].append((clean_text, keyword))

    return locations

def deduplicate(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]

def format_location_list(loc_dict):
    parts = []
    for loc, text_pairs in loc_dict.items():
        parts.append(loc)
    if not parts:
        return ""
    return ", ".join(parts[:-1]) + " 및 " + parts[-1] if len(parts) > 1 else parts[0]

def run_amendment_logic(find_word, replace_word):
    을를 = 조사_을를(find_word)
    으로로 = 조사_으로로(replace_word)
    amendment_results = []
    for idx, law in enumerate(get_law_list_from_api(find_word)):
        law_name = law["법령명"]
        mst = law["MST"]
        xml = get_law_text_by_mst(mst)
        if not xml:
            continue
        loc_dict = extract_locations(xml, find_word)
        if not loc_dict:
            continue

        덩어리별문장 = []
        for chunk, text_pairs in loc_dict.items():
            new_chunk = [t[0].replace(find_word, replace_word) for t in text_pairs][0]
            각각 = "각각 " if len(text_pairs) > 1 else ""
            덩어리별문장.append(f"{chunk} 중 “{find_word}”{을를} {각각}“{replace_word}”{으로로} 한다.")

        amendment_text = (
            f"{chr(9311 + idx + 1)} {law_name} 일부를 다음과 같이 개정한다.<br>" +
            "<br>".join(덩어리별문장)
        )
        amendment_results.append(amendment_text)

    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]
# 여기에 law_processor.py의 최신 통합본 내용을 붙여넣습니다.
# (이전 코드 분량 관계상 생략)
