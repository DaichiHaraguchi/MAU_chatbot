

import os
import requests
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin, urlparse
import time
import re
import json
import argparse
# --- 設定 ---

SAVE_DIR = os.path.join(os.path.dirname(__file__), '..','data','scraped_data_student_menu')
WAIT_TIME = 1
SKIPPED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.mov', '.mp4', '.xls', '.xlsx', '.doc', '.docx', '.ppt', '.pptx']

def get_student_menu_links(url, session):
    """
    トップページから「在学生の方（学2課程）」メニューに関連するリンクを収集する。
    """
    target_links = set()
    print(f"Fetching top page to find student menu links: {url}")
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        trigger_link = soup.find('a', class_='js-accordion-trigger', attrs={'href': '/campus-2nd'})
        if trigger_link:
            parent_li = trigger_link.find_parent('li', class_='js-accordion')
            if parent_li:
                link_container = parent_li.find('div', class_='l-global-nav__second')
                if link_container:
                    for a_tag in link_container.find_all('a', href=True):
                        href = a_tag['href']
                        full_url = urljoin('https://cc.musabi.ac.jp', href).split('#')[0]
                        if any(full_url.lower().endswith(ext) for ext in SKIPPED_EXTENSIONS):
                            continue
                        if '/campus-2nd' in full_url:
                            target_links.add(full_url)
    except requests.exceptions.RequestException as e:
        print(f"Could not get page {url}: {e}")
    except Exception as e:
        print(f"An error occurred while finding links: {e}")
    return list(target_links)

def parse_table(table_tag):
    """
    BeautifulSoupのtableタグを解析し、構造化された辞書を返す。
    """
    headers = []
    rows = []

    # ヘッダーの抽出
    header_row = table_tag.find('thead')
    if header_row:
        for th in header_row.find_all('th'):
            headers.append(th.get_text(strip=True))
    else: # theadがない場合、最初のtrをヘッダーとみなす
        first_tr = table_tag.find('tr')
        if first_tr:
            ths = first_tr.find_all('th')
            if ths: # thがあればヘッダー
                headers = [th.get_text(strip=True) for th in ths]
            else: # thがなければtdをヘッダーとみなす（まれなケース）
                headers = [td.get_text(strip=True) for td in first_tr.find_all('td')]

    # 行データの抽出
    for tr in table_tag.find_all('tr'):
        row_data = []
        # thとtdの両方を考慮（ヘッダー行以外にもthがある場合があるため）
        cells = tr.find_all(['th', 'td'])
        if not cells: # 空の行はスキップ
            continue

        # ヘッダーが抽出できていれば、ヘッダーの数だけデータを取得
        # ヘッダーがない場合は、その行のセルをそのまま取得
        for cell in cells:
            row_data.append(cell.get_text(strip=True))
        
        if any(row_data): # 空でない行のみ追加
            rows.append(row_data)

    # ヘッダー行がrowsに含まれてしまう場合があるので除去
    if headers and rows and rows[0] == headers:
        rows = rows[1:]

    return {
        "type": "table",
        "headers": headers,
        "rows": rows
    }

def parse_element_to_structured_data(element, base_url):
    """
    単一のbs4要素を解析し、構造化された辞書のリストに変換する。
    """
    structured_data = []
    
    # NavigableStringの場合はテキストとして処理
    if isinstance(element, NavigableString):
        text = element.strip()
        if text:
            structured_data.append({"type": "text", "text": text})
        return structured_data

    # HTMLタグの場合
    if not hasattr(element, 'name') or element.name is None:
        return []

    # 見出しタグ
    if re.match(r'h[1-6]', element.name):
        text = element.get_text(strip=True)
        if text:
            structured_data.append({
                "type": "heading",
                "level": int(element.name[1]),
                "text": text
            })
    # 段落タグ
    elif element.name == 'p':
        text_content = ''
        links = []
        for content in element.contents:
            if isinstance(content, NavigableString):
                text_content += content.string
            elif content.name == 'a' and content.has_attr('href'):
                link_text = content.get_text(strip=True)
                link_url = urljoin(base_url, content['href'])
                text_content += link_text
                links.append({"text": link_text, "url": link_url})
        
        text_content = text_content.strip()
        if text_content:
            p_data = {"type": "paragraph", "text": re.sub(r'\s+', ' ', text_content)}
            if links:
                p_data['links'] = links
            structured_data.append(p_data)
    # リストタグ
    elif element.name in ['ul', 'ol']:
        items = []
        for li in element.find_all('li', recursive=False):
            item_text = li.get_text(strip=True)
            if item_text:
                items.append(item_text)
        if items:
            structured_data.append({
                "type": "list",
                "style": "unordered" if element.name == 'ul' else "ordered",
                "items": items
            })
    # テーブルタグの処理を追加
    elif element.name == 'table':
        table_data = parse_table(element)
        if table_data['headers'] or table_data['rows']:
            structured_data.append(table_data)
    # その他のコンテナタグは再帰的に解析
    elif element.name in ['div', 'section', 'article', 'main', 'body']:
        for child in element.children:
            structured_data.extend(parse_element_to_structured_data(child, base_url))

    return structured_data

def scrape_and_save_structured_json(url, session):
    """
    URLからコンテンツをスクレイピングし、構造化されたJSONとして保存する。
    """
    try:
        time.sleep(WAIT_TIME)
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        title = soup.find('title').get_text(strip=True) if soup.find('title') else 'No Title'
        main_content = soup.find('main')

        if main_content:
            for tag in main_content.select('header, footer, nav, script, style, .p-main-visual__campus-link, .p-carousel, .p-utility-link, .p-conversion, .f-small, .c-local-nav, .p-section__button'):
                tag.decompose()

            # 構造化データに変換
            content_structure = []
            for child in main_content.children:
                content_structure.extend(parse_element_to_structured_data(child, url))

            data = {
                'url': url,
                'title': title,
                'content': content_structure
            }

            parsed_url = urlparse(url)
            path_segment = parsed_url.path.replace('/campus-2nd', '').strip('/').replace('/', '_')
            if not path_segment:
                path_segment = 'top'
            
            filename = os.path.join(SAVE_DIR, f"{path_segment}.json")

            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Saved: {filename}")
            return True

    except requests.exceptions.RequestException as e:
        print(f"Could not scrape {url}: {e}")
    except Exception as e:
        print(f"Error processing {url} for saving: {e}")
    return False

if __name__ == '__main__':
    os.makedirs(SAVE_DIR, exist_ok=True)
    print(f"Data will be saved in: {SAVE_DIR}")
    parser = argparse.ArgumentParser(description="Syllabusクローラー")
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://cc.musabi.ac.jp/campus-2nd/",
        help="ベースとなるURL（例: https://example.com/）"
    )
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")

    with requests.Session() as session:
        target_links = get_student_menu_links(BASE_URL, session)
        if BASE_URL not in target_links:
            target_links.append(BASE_URL)

        if not target_links:
            print("Could not find any target links. The HTML structure may have changed.")
        else:
            print(f"\nFound {len(target_links)} pages to scrape from the student menu.")
            print("\nTarget URLs:")
            for link in sorted(target_links):
                print(f"- {link}")
            print("")

            saved_count = 0
            for link in sorted(target_links):
                 if scrape_and_save_structured_json(link, session):
                     saved_count += 1
            print(f"\nScraping finished. Saved {saved_count} pages.")

