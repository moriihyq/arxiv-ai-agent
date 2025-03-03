import requests
import xml.etree.ElementTree as ET
import mysql.connector
from datetime import date
import schedule
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.data import find
import re

# 确保下载 NLTK 数据
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

try:
    find('tokenizers/punkt_tab/english/')
except LookupError:
    nltk.download('punkt_tab')

# --- MySQL 数据库配置 ---
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "307248qwe"
DB_NAME = "mydatabase"

# --- 邮箱配置 ---
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
FROM_ADDR = 'huangyq4@gmail.com'
PASSWORD = 'tqtyfunmznseooii'  # 替换为你的应用专用密码
TO_ADDR = 'huangyouqi_sx@163.com'

def connect_to_db():
    """连接到 MySQL 数据库"""
    mydb = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',  # 指定使用 UTF-8 编码
        use_unicode=True
    )
    return mydb

def save_paper_data(paper):
    """将论文元数据保存到 papers 表中"""
    mydb = connect_to_db()
    mycursor = mydb.cursor()

    sql = """
    INSERT INTO papers (id, title, authors, abstract, categories, published_date, processed)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    title = %s, authors = %s, abstract = %s, categories = %s, published_date = %s, processed = %s
    """
    val = (
        paper["id"], paper["title"], paper["authors"], paper["summary"], paper["categories"],
        date.today(), False,  # 假设 published_date 是今天
        paper["title"], paper["authors"], paper["summary"], paper["categories"], date.today(), False
    )
    try:
        mycursor.execute(sql, val)
        mydb.commit()
        print(f"Saved paper: {paper['id']}")
    except Exception as e:
        print(f"Error saving paper {paper['id']}: {e}")
    finally:
        mycursor.close()
        mydb.close()

def save_generated_abstract(paper_id, abstract):
    """将生成的摘要保存到 abstracts 表中"""
    mydb = connect_to_db()
    mycursor = mydb.cursor()

    # 检查 paper_id 是否已经存在
    check_sql = "SELECT paper_id FROM abstracts WHERE paper_id = %s"
    mycursor.execute(check_sql, (paper_id,))
    result = mycursor.fetchone()

    if result:
        # 如果存在，更新数据
        sql = "UPDATE abstracts SET generated_abstract = %s, generation_date = %s WHERE paper_id = %s"
        val = (abstract, date.today(), paper_id)
    else:
        # 如果不存在，插入数据
        sql = "INSERT INTO abstracts (paper_id, generated_abstract, generation_date) VALUES (%s, %s, %s)"
        val = (paper_id, abstract, date.today())

    try:
        mycursor.execute(sql, val)
        mydb.commit()

        sql = "UPDATE papers SET processed = TRUE WHERE id = %s"
        val = (paper_id,)
        mycursor.execute(sql, val)
        mydb.commit()

        print(f"Saved abstract for paper: {paper_id}")
    except Exception as e:
        print(f"Error saving abstract for paper {paper_id}: {e}")
    finally:
        mycursor.close()
        mydb.close()

def search_arxiv(keyword):
    """
    Searches arXiv for papers related to the given keyword.

    Args:
        keyword (str): The keyword to search for.

    Returns:
        list: A list of dictionaries, where each dictionary contains the
              title, id, summary, and authors of a paper.
              Returns an empty list if the request fails.
    """
    # Define the base URL for the arXiv API
    base_url = "http://export.arxiv.org/api/query"

    # Define the query parameters
    params = {
        "search_query": f"all:{keyword}",  # Search in all fields for the keyword
        "start": 0,                        # Start at the first result
        "max_results": 5,                  # Limit to 5 results for testing
        "sortBy": "submittedDate",         # Sort by submission date
        "sortOrder": "descending"          # Sort in descending order
    }

    # Send the request to the arXiv API
    response = requests.get(base_url, params=params)
    response.encoding = 'utf-8'  # 显式设置编码

    # Check if the request was successful
    if response.status_code == 200:
        xml_data = response.text  # Get the XML response as text
        root = ET.fromstring(xml_data)

        # Define the XML namespace
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        papers = []
        # Iterate through each entry in the XML feed
        for entry in root.findall('atom:entry', ns):
            # Extract the title
            title = entry.find('atom:title', ns).text
            # Extract the id
            id = entry.find('atom:id', ns).text
            # Extract the summary
            summary = entry.find('atom:summary', ns).text
            # Extract the authors
            authors = [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)]
            # Extract the categories
            categories = []
            for category in entry.findall('atom:category', ns):
                term = category.find('atom:term', ns)
                if term is not None:
                    categories.append(term.text)

            paper = {
                "id": id,
                "title": title,
                "summary": summary,
                "authors": ", ".join(authors),
                "categories": ", ".join(categories)
            }
            papers.append(paper)
        return papers
    else:
        print("Failed to retrieve data from arXiv API")
        return []

def clean_text(text):
    """
    清理文本数据，保留必要符号（如连字符、撇号）.
    """
    # 允许字母、数字、空格、连字符、撇号
    text = re.sub(r'[^\w\s\'-]', '', text)  # 修改正则表达式
    text = re.sub(r'\s+', ' ', text).strip()  # 移除多余空格并去除首尾空格
    return text

def generate_abstract(text, num_sentences=3):
    """
    使用 NLTK 生成文本摘要（改进版）.
    """
    try:
        text = clean_text(text)
        
        # 检查清理后的文本是否为空
        if not text:
            print("清理后的文本为空！")
            return ""
            
        # 1. 分词
        stopWords = set(stopwords.words("english"))
        words = word_tokenize(text)
        
        # 2. 计算词频（过滤停用词）
        freqTable = {}
        for word in words:
            word_lower = word.lower()
            if word_lower not in stopWords and word_lower.isalpha():  # 仅保留字母单词
                freqTable[word_lower] = freqTable.get(word_lower, 0) + 1
        
        # 3. 句子分割
        sentences = sent_tokenize(text)
        if not sentences:
            print("无有效句子可处理！")
            return ""
        
        # 4. 计算句子得分（改进版）
        sentenceValue = {}
        for sentence in sentences:
            words_in_sentence = word_tokenize(sentence)
            word_count = len(words_in_sentence)
            if word_count == 0:
                continue  # 跳过空句子
            score = 0
            for word in words_in_sentence:
                word_lower = word.lower()
                score += freqTable.get(word_lower, 0)
            # 归一化得分
            sentenceValue[sentence] = score / word_count
        
        # 5. 选择最佳句子（动态阈值）
        if not sentenceValue:
            return ""
            
        avg_score = sum(sentenceValue.values()) / len(sentenceValue)
        threshold = avg_score * 1.2  # 降低阈值
        
        summary = []
        for sentence in sentences:
            if sentenceValue.get(sentence, 0) >= threshold:
                summary.append(sentence)
        
        # 如果无满足条件的句子，取前N个高分句子
        if not summary:
            sorted_sentences = sorted(sentenceValue.items(), key=lambda x: x[1], reverse=True)
            summary = [s[0] for s in sorted_sentences[:num_sentences]]
        
        return ' '.join(summary[:num_sentences])
        
    except Exception as e:
        import traceback
        print(f"生成摘要失败: {e}\n{traceback.format_exc()}")
        return ""

def send_email(subject, content, to_addr):
    """
    发送邮件.
    """
    # 构建邮件内容
    msg = MIMEText(content, 'html', 'utf-8')  # 使用 HTML 格式，方便显示
    msg['From'] = Header('arXiv 摘要机器人', 'utf-8')
    msg['To'] = Header(to_addr, 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()  # 如果使用 TLS
        server.login(FROM_ADDR, PASSWORD)
        server.sendmail(FROM_ADDR, [to_addr], msg.as_string())
        server.quit()
        print("邮件发送成功!")
    except smtplib.SMTPException as e:
        print(f"邮件发送失败: {e}")


def daily_arxiv_task():
    """
    每天自动从 arXiv 搜集 AI 论文，生成摘要，并存储到数据库中，然后发送邮件。
    """
    keyword = "artificial intelligence" # 替换成你的关键词

    # 1. 获取论文
    papers = search_arxiv(keyword)

    if papers:
        # 构建邮件内容
        email_content = "<h1>今日 arXiv AI 论文摘要</h1>\n"  # 使用 HTML 格式
        for paper in papers:
            # 2. 保存论文元数据 (如果不存在)
            save_paper_data(paper)

            # 3. 生成摘要 (如果还未生成)
            mydb = connect_to_db()
            mycursor = mydb.cursor()
            sql = "SELECT processed FROM papers WHERE id = %s"
            val = (paper["id"],)
            mycursor.execute(sql, val)
            result = mycursor.fetchone()
            mycursor.close()
            mydb.close()

            if result and not result[0]:  # processed is False
                # 使用 NLTK 生成摘要
                abstract = generate_abstract(paper["summary"])
                if abstract:
                    save_generated_abstract(paper["id"], abstract)
                    # 提取论文的 arXiv 编号
                    arxiv_id = paper["id"].split('/')[-1]
                    # 构建论文的网址
                    paper_url = f"https://arxiv.org/abs/{arxiv_id}"
                    email_content += f"<h2>{paper['title']}</h2>\n"
                    email_content += f"<p>作者: {paper['authors']}</p>\n"
                    email_content += f"<p><a href='{paper_url}'>论文链接: {paper_url}</a></p>\n"  # 添加论文链接
                    email_content += f"<p>{abstract}</p>\n"
                    email_content += "<hr>\n"
                else:
                    print(f"Failed to generate abstract for {paper['id']}")
            else:
                print(f"Paper {paper['id']} already processed or not found.")

        # 发送邮件
        if email_content != "<h1>今日 arXiv AI 论文摘要</h1>\n":  # 如果有新的摘要
            send_email("今日 arXiv AI 论文摘要", email_content, TO_ADDR)
        else:
            print("今日没有新的 AI 论文摘要.")
    else:
        print("No papers found today.")

# 使用 schedule 每天定时运行任务
schedule.every().day.at("21:05").do(daily_arxiv_task) # 每天 22 点运行

if __name__ == "__main__":
    # 初始化数据库连接 (创建表如果不存在)
    mydb = connect_to_db()
    mycursor = mydb.cursor()

    mycursor.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id VARCHAR(255) PRIMARY KEY,
        title TEXT,
        authors TEXT,
        abstract TEXT,
        categories TEXT,
        published_date DATE,
        processed BOOLEAN DEFAULT FALSE
    )
    """)

    mycursor.execute("""
    CREATE TABLE IF NOT EXISTS abstracts (
        paper_id VARCHAR(255) PRIMARY KEY,
        generated_abstract TEXT,
        generation_date DATE,
        FOREIGN KEY (paper_id) REFERENCES papers(id)
    )
    """)
    mydb.commit()
    mycursor.close()
    mydb.close()

    print("Starting scheduler...")
    while True:
        schedule.run_pending()
        time.sleep(60) # 每分钟检查一次
