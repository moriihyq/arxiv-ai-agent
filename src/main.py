import requests
import xml.etree.ElementTree as ET
import sqlite3
from datetime import date
import schedule
import time
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
import re

# 确保下载 NLTK 数据
nltk.download('punkt', quiet=True)
nltk.download('stopwords', quiet=True)

# --- SQLite 数据库配置 ---
DB_NAME = "test.db"

# --- 邮箱配置 ---
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
FROM_ADDR = 'huangyq4@gmail.com'
PASSWORD = 'tqtyfunmznseooii'
TO_ADDR = 'huangyouqi_sx@163.com'

def connect_to_db():
    """连接到 SQLite 数据库"""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def save_paper_data(paper):
    """保存论文元数据"""
    conn = connect_to_db()
    cursor = conn.cursor()

    sql = """
    INSERT INTO papers (id, title, authors, abstract, categories, published_date, processed)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
    title = excluded.title,
    authors = excluded.authors,
    abstract = excluded.abstract,
    categories = excluded.categories,
    published_date = excluded.published_date,
    processed = excluded.processed
    """
    val = (
        paper["id"], paper["title"], paper["authors"], paper["summary"],
        paper["categories"], date.today().isoformat(), 0
    )
    
    try:
        cursor.execute(sql, val)
        conn.commit()
        print(f"Saved paper: {paper['id']}")
    except Exception as e:
        print(f"Error saving paper {paper['id']}: {e}")
    finally:
        cursor.close()
        conn.close()

def save_generated_abstract(paper_id, abstract):
    """保存生成的摘要"""
    conn = connect_to_db()
    cursor = conn.cursor()

    sql = """
    INSERT INTO abstracts (paper_id, generated_abstract, generation_date)
    VALUES (?, ?, ?)
    ON CONFLICT(paper_id) DO UPDATE SET
    generated_abstract = excluded.generated_abstract,
    generation_date = excluded.generation_date
    """
    val = (paper_id, abstract, date.today().isoformat())

    try:
        cursor.execute(sql, val)
        cursor.execute("UPDATE papers SET processed = 1 WHERE id = ?", (paper_id,))
        conn.commit()
        print(f"Saved abstract for paper: {paper_id}")
    except Exception as e:
        print(f"Error saving abstract for paper {paper_id}: {e}")
    finally:
        cursor.close()
        conn.close()

def search_arxiv(keyword):
    """搜索 arXiv 论文"""
    base_url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{keyword}",
        "start": 0,
        "max_results": 5,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    }

    response = requests.get(base_url, params=params)
    response.encoding = 'utf-8'

    if response.status_code == 200:
        root = ET.fromstring(response.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        papers = []

        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns).text.strip()
            paper_id = entry.find('atom:id', ns).text
            summary = entry.find('atom:summary', ns).text.strip()
            authors = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)]
            categories = [cat.get('term') for cat in entry.findall('atom:category', ns)]

            papers.append({
                "id": paper_id,
                "title": title,
                "summary": summary,
                "authors": ", ".join(authors),
                "categories": ", ".join(categories)
            })
        return papers
    else:
        print("arXiv API 请求失败")
        return []

def clean_text(text):
    """清理文本"""
    text = re.sub(r'[^\w\s\'-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_abstract(text, num_sentences=3):
    """生成摘要"""
    try:
        text = clean_text(text)
        if not text:
            return ""

        stop_words = set(stopwords.words("english"))
        words = word_tokenize(text)
        
        freq_table = {}
        for word in words:
            word_lower = word.lower()
            if word_lower not in stop_words and word_lower.isalpha():
                freq_table[word_lower] = freq_table.get(word_lower, 0) + 1

        sentences = sent_tokenize(text)
        if not sentences:
            return ""

        sentence_scores = {}
        for sentence in sentences:
            words_in_sent = word_tokenize(sentence)
            word_count = len(words_in_sent)
            if word_count == 0:
                continue
            score = sum(freq_table.get(word.lower(), 0) for word in words_in_sent)
            sentence_scores[sentence] = score / word_count

        avg_score = sum(sentence_scores.values()) / len(sentence_scores)
        threshold = avg_score * 1.2
        summary = [s for s in sentences if sentence_scores.get(s, 0) >= threshold]

        if not summary:
            sorted_sents = sorted(sentence_scores.items(), key=lambda x: x[1], reverse=True)
            summary = [s[0] for s in sorted_sents[:num_sentences]]

        return ' '.join(summary[:num_sentences])
    
    except Exception as e:
        print(f"摘要生成错误: {str(e)}")
        return ""

def send_email(subject, content, to_addr):
    """发送邮件"""
    msg = MIMEText(content, 'html', 'utf-8')
    msg['From'] = Header('arXiv 摘要机器人', 'utf-8')
    msg['To'] = Header(to_addr, 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(FROM_ADDR, PASSWORD)
            server.sendmail(FROM_ADDR, [to_addr], msg.as_string())
        print("邮件发送成功!")
    except Exception as e:
        print(f"邮件发送失败: {str(e)}")

def daily_arxiv_task():
    """每日任务"""
    papers = search_arxiv("artificial intelligence")
    if not papers:
        print("今日未找到论文")
        return

    email_content = "<h1>今日 arXiv AI 论文摘要</h1>\n"
    for paper in papers:
        save_paper_data(paper)
        
        conn = connect_to_db()
        cursor = conn.cursor()
        cursor.execute("SELECT processed FROM papers WHERE id = ?", (paper["id"],))
        processed = cursor.fetchone()
        cursor.close()
        conn.close()

        if not processed or not processed[0]:
            abstract = generate_abstract(paper["summary"])
            if abstract:
                save_generated_abstract(paper["id"], abstract)
                arxiv_id = paper["id"].split('/')[-1]
                email_content += f"""
                <h2>{paper['title']}</h2>
                <p>作者: {paper['authors']}</p>
                <p><a href='https://arxiv.org/abs/{arxiv_id}'>论文链接</a></p>
                <p>{abstract}</p>
                <hr>
                """

    if email_content != "<h1>今日 arXiv AI 论文摘要</h1>\n":
        send_email("今日 arXiv AI 论文摘要", email_content, TO_ADDR)
    else:
        print("今日无新摘要")

# 定时任务配置
schedule.every().day.at("21:41").do(daily_arxiv_task)

if __name__ == "__main__":
    # 初始化数据库
    conn = connect_to_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id TEXT PRIMARY KEY,
        title TEXT,
        authors TEXT,
        abstract TEXT,
        categories TEXT,
        published_date TEXT,
        processed INTEGER DEFAULT 0
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS abstracts (
        paper_id TEXT PRIMARY KEY,
        generated_abstract TEXT,
        generation_date TEXT,
        FOREIGN KEY (paper_id) REFERENCES papers(id)
    )
    """)
    conn.commit()
    cursor.close()
    conn.close()

    print("定时任务已启动...")
    while True:
        schedule.run_pending()
        time.sleep(60)
