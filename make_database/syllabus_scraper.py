import requests
from bs4 import BeautifulSoup
import re
import time
import csv
import os
from datetime import datetime
import argparse
from urllib.parse import urljoin  #
# CSV保存先のディレクトリ
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..","data")

def _fetch_page(session, url, method='GET', payload=None):
    """指定されたURLとメソッドでページを取得するヘルパー関数 (sessionを使用)"""
    try:
        if method == 'POST':
            response = session.post(url, data=payload)
        else: # GET
            response = session.get(url)
        
        response.encoding = response.apparent_encoding
        response.raise_for_status() # HTTPエラーがあれば例外を発生させる
        
        # --- DEBUG ADDITION ---
        print(f"DEBUG: Fetched URL: {url}")
        print(f"DEBUG: Response Status Code: {response.status_code}")
        print(f"DEBUG: Response HTML Length: {len(response.text)}")
        if len(response.text) == 0:
            print(f"WARNING: ページ {url} のHTMLコンテンツが空です。")
        # --- END DEBUG ADDITION ---
        
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"ページの取得中にエラーが発生しました ({url}): {e}")
        raise # エラーを再発生させる
    except Exception as e:
        print(f"ページの取得中に予期せぬエラーが発生しました ({url}): {e}")
        raise # エラーを再発生させる

def _extract_data_from_search_page(soup):
    """検索結果のHTMLからカテゴリ、開講期間、科目名、時間割、教員名、詳細URLの情報を抽出する"""
    data = []
    
    # 2番目の <table class="list"> を取得
    all_list_tables = soup.find_all('table', class_='list')
    if len(all_list_tables) < 2:
        print("DEBUG: 2番目のテーブル (class='list') が見つかりませんでした。")
        return data
    
    main_data_table = all_list_tables[1] # 2番目のテーブルを選択
    # print("DEBUG: 2番目のメインのテーブル (class='list') が見つかりました。") # Debug

    # tbody内のすべての<tr>要素を取得
    tbody = main_data_table.find('tbody')
    if not tbody:
        print("DEBUG: メインのテーブル内に<tbody>が見つかりませんでした。")
        return data

    data_rows = tbody.find_all('tr') 
    # print(f"DEBUG: <table><tbody>直下の<tr>要素の数: {len(data_rows)}") # Debug
    
    # 最初の<tr>はヘッダーなのでスキップ (<th>タグがある行)
    if len(data_rows) > 0 and data_rows[0].find('th'):
        data_rows = data_rows[1:] 
        # print(f"DEBUG: ヘッダーをスキップした後のデータ行の数: {len(data_rows)}") # Debug
    
    if not data_rows:
        # print("DEBUG: データ行が見つかりませんでした。")
        return data

    for i, row in enumerate(data_rows):
        # 各行の<td>要素を取得 (class='list-odd-left' は指定せず、すべてのtdを取得)
        tds = row.find_all('td')
        # print(f"DEBUG: 行 {i+1}: <td>要素の数: {len(tds)}") # Debug
        
        # 必要な情報が含まれる<td>が十分にあるか確認
        if len(tds) >= 5: # カテゴリ、開講期間、科目名、時間割、教員の5つ
            category = tds[0].get_text(strip=True)
            period = tds[1].get_text(strip=True) # 開講期間
            
            subject_link_tag = tds[2].find('a', href=re.compile(r"JavaScript:showSbs"))
            subject_name = subject_link_tag.get_text(strip=True) if subject_link_tag else ""
            
            schedule = tds[3].get_text(strip=True) # 時間割
            teacher_name = tds[4].get_text(strip=True)

            detail_url = ""
            if subject_link_tag:
                href_text = subject_link_tag.get('href') # href属性を取得
                print(f"DEBUG: Row {i+1}, Subject Link href: {href_text}") # Debug: href属性の値を表示
                if href_text: # href属性が存在する場合のみ処理
                    year = ""
                    sno = ""
                    try:
                        # "JavaScript:showSbs(" を取り除く
                        temp_str = href_text.replace("JavaScript:showSbs(", "")
                        # ");" を取り除く
                        temp_str = temp_str.rstrip(");")
                        
                        # "," で分割
                        parts = temp_str.split(',', 1) # 最初のカンマで分割
                        if len(parts) == 2:
                            year = parts[0].strip()
                            sno = parts[1].strip().strip("'") # シングルクォートを取り除く
                            
                            # yearとsnoが数字であることを確認
                            if year.isdigit() and sno.isdigit():
                                detail_url = f"{SYLLABUS_DETAIL_BASE_URL}{year}_{sno}.html"
                                print(f"DEBUG: Row {i+1}, Constructed Detail URL (String Manip): {detail_url}") # Debug: 構築されたURLを表示
                            else:
                                print(f"DEBUG: Row {i+1}, String manipulation failed: year or sno not digits. temp_str: {temp_str}")
                        else:
                            print(f"DEBUG: Row {i+1}, String manipulation failed: not enough parts after split. temp_str: {temp_str}")
                    except Exception as e:
                        print(f"DEBUG: Row {i+1}, Error during string manipulation: {e}. href_text: {href_text}")
                else:
                    print(f"DEBUG: Row {i+1}, Subject link tag found but href attribute is missing.") # Debug: href属性がない場合
            else:
                print(f"DEBUG: Row {i+1}, Subject link tag not found in tds[2]. HTML of tds[2]: {tds[2]}") # Debug: リンクタグが見つからない場合

            if subject_name: # 科目名が取得できた場合のみ追加
                data.append({
                    'category': category,
                    'period': period,
                    'subject_name': subject_name,
                    'schedule': schedule,
                    'teacher_name': teacher_name,
                    'detail_url': detail_url
                })
            else:
                print(f"DEBUG: 行 {i+1}: 科目名が見つからないか、空です。") # Debug
        else:
            print(f"DEBUG: 行 {i+1}: 必要な数の<td>要素が見つかりませんでした (期待値 >= 5, 取得値 {len(tds)})。") # Debug
    return data

def get_syllabus_overview(session, detail_url): # session を引数に追加
    """科目詳細ページから「授業の概要と目標」を抽出する"""
    if not detail_url:
        print(f"DEBUG: 詳細URLが空のため、概要を抽出できません。")
        raise ValueError("詳細URLが空です。") # エラーを発生させる

    print(f"DEBUG: 概要抽出中 - 詳細ページURL: {detail_url}") # デバッグ出力
    try:
        response = session.get(detail_url) # session を使用
        response.encoding = response.apparent_encoding
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        overview_text = ""
        
        # <th>タグで「授業の概要と目標」を探す
        th_tag = soup.find('th', class_='sbs-show', string=re.compile(r'【授業の概要と目標】'))
        
        if th_tag:
            print(f"DEBUG: '【授業の概要と目標】' のthタグが見つかりました。") # デバッグ出力
            # thタグの親の<tr>を取得し、その次の兄弟<tr>を探す
            tr_overview_container = th_tag.find_parent('tr').find_next_sibling('tr')
            
            if tr_overview_container:
                # その<tr>の中の<td>タグを探す
                td_overview = tr_overview_container.find('td', class_='sbs-show')
                if td_overview:
                    # その<td>タグの中の<p class="ct">タグからテキストを抽出
                    p_tag = td_overview.find('p', class_='ct')
                    if p_tag:
                        overview_text = p_tag.get_text(strip=True)
                        print(f"DEBUG: 概要を抽出しました (先頭100文字): {overview_text[:100]}...") # デバッグ出力
                    else:
                        print(f"DEBUG: td.sbs-show 内に p.ct タグが見つかりませんでした。")
                else:
                    print(f"DEBUG: 概要コンテナのtr内に td.sbs-show タグが見つかりませんでした。")
            else:
                print(f"DEBUG: '【授業の概要と目標】' のthタグの次のtrが見つかりませんでした。")
        else:
            print(f"DEBUG: '【授業の概要と目標】' のthタグが見つかりませんでした。") # デバッグ出力
            # h3タグが見つからない場合、HTML全体を一部出力して構造を確認
            # print(f"DEBUG: 詳細ページHTML (thタグが見つからなかった場合、先頭1000文字):\n{response.text[:1000]}...") # デバッグ出力
        
        if not overview_text:
            raise ValueError(f"詳細ページ {detail_url} から「授業の概要と目標」を抽出できませんでした。")

        return overview_text
    except requests.exceptions.RequestException as e:
        print(f"詳細ページの取得中にエラーが発生しました ({detail_url}): {e}")
        raise # エラーを再発生させる
    except Exception as e:
        print(f"「授業の概要と目標」の抽出中に予期せぬエラーが発生しました ({detail_url}): {e}")
        raise # エラーを再発生させる

def scrape_all_syllabus_data_with_overview(year='2025'):
    """
    全シラバス検索結果からカテゴリ、科目名、教員名、授業概要をスクレイピングする (ページネーション対応)
    """
    all_extracted_data = []
    current_url = SEARCH_URL
    page_num = 1
    
    # requests.Session() を作成
    with requests.Session() as session:
        # 最初のページはPOSTリクエストで取得
        initial_payload = {
            'sbj': '',  # 全件取得のため空
            'tch': '',
            'txt': '',
            'year': year
        }
        html_content = _fetch_page(session, current_url, method='POST', payload=initial_payload) # session を渡す

        if not html_content:
            print("初期ページの取得に失敗しました。")
            return all_extracted_data

        while True:
            print(f"スクレイピング中: ページ {page_num}")
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # データ抽出
            page_data = _extract_data_from_search_page(soup)
            
            # 各科目に対して詳細情報を取得
            for item in page_data:
                try: # 個別の概要取得でエラーが発生しても全体を止めないようにtry-exceptを追加
                    overview = get_syllabus_overview(session, item['detail_url'])
                    item['overview'] = overview
                except (requests.exceptions.RequestException, ValueError, Exception) as e:
                    print(f"WARNING: 科目 '{item.get('subject_name', '不明')}' の概要取得中にエラー: {e}")
                    item['overview'] = f"エラー: {e}" # エラーメッセージを概要として記録
                all_extracted_data.append(item)
                time.sleep(0.5) # 詳細ページ取得間の短い待機を延長
                
            # 次のページへのリンクを探す
            next_page_tag = soup.find('a', title="next page")
            
            if next_page_tag and next_page_tag.has_attr('href'):
                next_page_relative_url = next_page_tag['href'].replace('&amp;', '&')
                # current_url = f"{BASE_URL}{next_page_relative_url.lstrip('/')}" # 絶対URLを構築
                current_url = urljoin(current_url, next_page_relative_url) 
                page_num += 1
                time.sleep(2) # ページ間の待機を延長
                html_content = _fetch_page(session, current_url, method='GET') # session を渡す
                if not html_content:
                    print(f"ページ {page_num} の取得に失敗しました。")
                    break # 取得失敗時は終了
            else:
                print(f"ページ {page_num} で 'Next >>' リンクが見つかりませんでした。最終ページです。")
                break # 次のページへのリンクがなければ終了
                
        return all_extracted_data

if __name__ == "__main__":
    print("全シラバス検索結果と授業概要のスクレイピングを開始します...\n")
    parser = argparse.ArgumentParser(description="Syllabusクローラー")
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://ccap02.musabi.ac.jp/",
        help="ベースとなるURL（例: https://example.com/）"
    )
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")
    SEARCH_URL = f"{BASE_URL}/syllabus/pubSearchResult.php"
    SYLLABUS_DETAIL_BASE_URL = f"{BASE_URL}/syllabus/html/"

    # 出力ディレクトリが存在しない場合は作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    extracted_data = scrape_all_syllabus_data_with_overview()
    
    if extracted_data:
        print(f"\n合計で {len(extracted_data)} 件の科目情報が見つかりました。")
        
        # CSVファイル名にタイムスタンプを追加
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = os.path.join(OUTPUT_DIR, f"all_syllabus_with_overview.csv")
        
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['category', 'period', 'subject_name', 'schedule', 'teacher_name', 'detail_url', 'overview']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            writer.writerows(extracted_data)
                
        print(f"\nスクレイピング結果を {csv_filename} に保存しました。")
    else:
        print("科目情報が見つかりませんでした。スクレイピングを終了します。")