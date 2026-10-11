import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://www.shouwa.or.jp/newslist/"
OUTPUT = Path(__file__).parent / "shouwakai.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"^(20\d{2})\.(\d{2})\.(\d{2})$"
)

ARTICLE_URL_RE = re.compile(
    r"^https://www\.shouwa\.or\.jp/"
    r"20\d{2}/\d{2}/\d{2}/"
)


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:
        tree = ET.parse(OUTPUT)

        for item in tree.getroot().findall("./channel/item"):

            guid = item.findtext("guid", "")

            if guid:
                old_items[guid] = {
                    "title": item.findtext("title", ""),
                    "link": item.findtext("link", ""),
                    "description": item.findtext(
                        "description", ""
                    ),
                    "pubDate": item.findtext(
                        "pubDate", ""
                    ),
                    "guid": guid,
                }

    except Exception as e:

        print("既存RSS読み込みエラー:", e)
        print("安全のため今回は更新しません。")

        raise SystemExit(0)


print("既存RSS件数:", len(old_items))


# --------------------------------------------------
# ページ取得
# --------------------------------------------------

response = None
MAX_RETRIES = 3

for attempt in range(1, MAX_RETRIES + 1):

    try:

        print(
            f"祥和会 更新情報取得 "
            f"{attempt}/{MAX_RETRIES}"
        )

        response = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        print("HTTP:", response.status_code)

        response.raise_for_status()
        break

    except requests.RequestException as e:

        print("取得失敗:", e)
        response = None

        if attempt < MAX_RETRIES:
            print("10秒待って再試行します。")
            time.sleep(10)


if response is None:

    print()
    print("ページを取得できませんでした。")
    print("既存XMLをそのまま維持します。")

    raise SystemExit(0)


# --------------------------------------------------
# HTML解析
# --------------------------------------------------

soup = BeautifulSoup(
    response.content,
    "html.parser"
)

news_container = soup.select_one(
    "#news_list"
)

if news_container is None:

    print("ニュース一覧を取得できませんでした。")
    print("ページ構造変更の可能性があります。")
    print("既存XMLを維持します。")

    raise SystemExit(0)


current_items = []


# --------------------------------------------------
# 記事取得
# --------------------------------------------------

for dt in news_container.find_all("dt"):

    date_element = dt.select_one(
        "span.date"
    )

    if date_element is None:
        continue

    date_text = date_element.get_text(
        " ",
        strip=True
    )

    match = DATE_RE.match(date_text)

    if not match:
        continue

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))


    # dtの次のddを記事本文側として取得
    dd = dt.find_next_sibling("dd")

    if dd is None:
        continue


    article_a = None

    for a in dd.find_all(
        "a",
        href=True
    ):

        absolute = urljoin(
            SOURCE_URL,
            a["href"]
        )

        if ARTICLE_URL_RE.match(absolute):
            article_a = a
            break


    if article_a is None:
        continue


    title = article_a.get_text(
        " ",
        strip=True
    )

    if not title:
        continue


    link = urljoin(
        SOURCE_URL,
        article_a["href"]
    )


    # --------------------------------------------------
    # dt内の「種別」「施設名」をdescriptionに保存
    # --------------------------------------------------

    metadata = []

    for element in dt.find_all(
        ["span", "a"]
    ):

        text = element.get_text(
            " ",
            strip=True
        )

        if not text:
            continue

        if DATE_RE.match(text):
            continue

        if text not in metadata:
            metadata.append(text)


    description = ""

    if metadata:
        description = " / ".join(metadata)


    pub_dt = datetime(
        year,
        month,
        day,
        12,
        0,
        0,
        tzinfo=JST
    )


    guid = hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


    current_items.append({
        "title": title,
        "link": link,
        "description": description,
        "pubDate": format_datetime(pub_dt),
        "guid": guid,
    })


print()
print(
    "今回取得:",
    len(current_items),
    "件"
)


# --------------------------------------------------
# 安全確認
# --------------------------------------------------

if len(current_items) == 0:

    print("記事を1件も取得できませんでした。")
    print("ページ構造変更の可能性があります。")
    print("既存XMLを維持します。")

    raise SystemExit(0)


# --------------------------------------------------
# 重複除去・既存記事統合
# --------------------------------------------------

all_items = []
seen_guids = set()


for item in current_items:

    if item["guid"] in seen_guids:
        continue

    all_items.append(item)
    seen_guids.add(item["guid"])


for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(item)
    seen_guids.add(guid)


# --------------------------------------------------
# 日付順
# --------------------------------------------------

def get_date(item):

    try:
        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS生成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)

ET.SubElement(
    channel,
    "title"
).text = "祥和会 更新情報"

ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL

ET.SubElement(
    channel,
    "description"
).text = (
    "社会医療法人祥和会グループの更新情報"
)

ET.SubElement(
    channel,
    "language"
).text = "ja"


for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )

    ET.SubElement(
        element,
        "title"
    ).text = item["title"]

    ET.SubElement(
        element,
        "link"
    ).text = item["link"]

    ET.SubElement(
        element,
        "description"
    ).text = item["description"]

    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]

    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# 保存
# --------------------------------------------------

tree = ET.ElementTree(rss)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


print()
print("RSS作成成功")

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)

print()
print("今回取得した記事:")


for i, item in enumerate(
    current_items,
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    if item["description"]:
        print(
            "    ",
            item["description"]
        )

    print(
        "    ",
        item["link"]
    )