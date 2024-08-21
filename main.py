import os
import requests
import logging
import threading
import urllib.parse
import time
import signal
import random
import json
import re
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler
from openai import OpenAI
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()
google_api_key = os.getenv('GOOGLE_API_KEY')
google_cse_id = os.getenv('GOOGLE_CSE_ID')
blogger_blog_id = os.getenv('BLOGGER_BLOG_ID')
openai_api_key = os.getenv('OPENAI_API_KEY')

client = OpenAI(api_key=openai_api_key)
exit_flag = threading.Event()

def signal_handler(signum, frame):
    exit_flag.set()
    logger.info("프로그램 종료 신호를 받았습니다. 작업을 마무리하고 종료합니다.")

signal.signal(signal.SIGINT, signal_handler)

# 간단한 재시도 데코레이터 구현
def retry_with_backoff(retries=3, backoff_in_seconds=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            x = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if x == retries:
                        logger.error(f"{func.__name__} 함수 실행 중 최종 오류 발생: {e}")
                        raise
                    else:
                        sleep = (backoff_in_seconds * 2 ** x +
                                 random.uniform(0, 1))
                        logger.warning(f"{func.__name__} 함수에서 오류 발생: {e}. {sleep:.2f}초 후 재시도합니다. ({x + 1}/{retries})")
                        time.sleep(sleep)
                        x += 1
        return wrapper
    return decorator

class GoogleAuth:
    def __init__(self):
        self.auth_code = None
        self.server = None

    class AuthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.auth_code = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('code', [None])[0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'Authentication successful! You can close this window.')
            threading.Thread(target=self.server.shutdown).start()

    def start_server(self):
        server_address = ('', 8000)
        self.server = HTTPServer(server_address, self.AuthHandler)
        self.server.auth_code = None
        logger.info("로컬 서버를 시작합니다.")
        self.server.serve_forever()
        logger.info("로컬 서버가 종료되었습니다.")

    def get_credentials(self):
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/blogger'],
            redirect_uri='http://localhost:8000'
        )
        auth_url, _ = flow.authorization_url(prompt='consent')
        logger.info(f'다음 URL로 이동하여 인증을 완료하세요: {auth_url}')
        
        threading.Thread(target=self.start_server).start()
        
        while self.server is None or self.server.auth_code is None:
            if exit_flag.is_set():
                logger.info("프로그램 종료 신호를 받아 인증 과정을 중단합니다.")
                return None
            time.sleep(1)

        logger.info("인증 코드를 받았습니다. 토큰을 가져오는 중...")
        flow.fetch_token(code=self.server.auth_code)
        logger.info("Google 인증이 성공적으로 완료되었습니다.")
        return flow.credentials

@retry_with_backoff(retries=3)
def get_trending_topics():
    url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
    logger.info(f"트렌딩 주제를 가져오는 중... URL: {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        items = soup.find_all('item')
        
        topics = [(item.find('title').text, int(item.find('ht:approx_traffic').text.replace('+', '').replace(',', ''))) for item in items[:20]]
        topics.sort(key=lambda x: x[1], reverse=True)
        
        selected_topics = [topic for topic, _ in topics[:10]]
        logger.info(f"선택된 주제: {', '.join(selected_topics)}")
        return selected_topics
    except requests.RequestException as e:
        logger.error(f"트렌딩 주제 가져오기 실패: {e}")
        raise

@retry_with_backoff(retries=3)
def select_best_topic(service, trending_topics):
    logger.info("최적의 주제 선택 중...")
    try:
        posts = service.posts().list(blogId=blogger_blog_id, fetchBodies=False, maxResults=10).execute()
        if not posts.get('items'):
            logger.warning("블로그에 게시물이 없거나 가져온 게시물이 없습니다. 트렌딩 주제 중에서 선택합니다.")
            selected_topic = random.choice(trending_topics)
            analysis = analyze_topic(selected_topic)
            logger.info(f"선택된 주제: {selected_topic}")
            return selected_topic, analysis

        popular_posts = sorted(posts['items'], key=lambda post: int(post.get('replies', {}).get('totalItems', 0)), reverse=True)[:5]
        popular_titles = [post['title'].lower() for post in popular_posts]

        combined_topics = trending_topics + [f"{title} 관련 최신 동향" for title in popular_titles]
        unique_topics = list(set(combined_topics))
        selected_topic = random.choice(unique_topics)
        analysis = analyze_topic(selected_topic)
        logger.info(f"선택된 주제: {selected_topic}")
        return selected_topic, analysis
    except HttpError as e:
        logger.error(f"Blogger API 호출 중 오류 발생: {e}")
        selected_topic = random.choice(trending_topics) if trending_topics else "일반적인 관심사"
        analysis = analyze_topic(selected_topic)
        return selected_topic, analysis
    except Exception as e:
        logger.error(f"주제 선택 중 오류 발생: {e}")
        selected_topic = random.choice(trending_topics) if trending_topics else "일반적인 관심사"
        analysis = analyze_topic(selected_topic)
        return selected_topic, analysis

def analyze_topic(topic):
    prompt = f"""
    주제: {topic}
    
    이 주제에 대해 다음 정보를 제공해주세요:
    1. 주제의 중요성 (1-10 점수)
    2. 시사성 (1-10 점수)
    3. 대중의 관심도 (1-10 점수)
    4. 글로벌 영향력 (1-10 점수)
    5. 연관 키워드 (10개)
    6. 주요 이슈 또는 논점 (5개)
    7. 관련 통계 또는 데이터 (3개)
    8. 전문가 의견 (3개)
    9. 미래 전망 (3개)
    10. 독자 행동 제안 (5개)
    
    JSON 형식으로 응답해 주세요. 모든 필드는 리스트 형태로 반환해 주세요.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert topic analyzer."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        response_content = response.choices[0].message.content
        logger.info(f"응답 내용: {response_content}")

        # 백틱과 'json' 표시 제거
        clean_content = re.sub(r'```json\s*|\s*```', '', response_content).strip()

        try:
            analysis = json.loads(clean_content)
        except json.JSONDecodeError as e:
            logger.error(f"응답을 JSON으로 파싱하는데 실패했습니다: {e}")
            raise ValueError("JSON 파싱 실패")

        # 필드 유무 확인 및 기본값 설정
        default_values = {
            "중요성": [5],
            "시사성": [5],
            "대중의 관심도": [5],
            "글로벌 영향력": [5],
            "연관 키워드": ["general"] * 10,
            "주요 이슈 또는 논점": ["no major issues reported"] * 5,
            "관련 통계 또는 데이터": ["no data available"] * 3,
            "전문가 의견": ["no expert opinions available"] * 3,
            "미래 전망": ["no future prospects available"] * 3,
            "독자 행동 제안": ["no action suggestions available"] * 5
        }

        # 각 필드에 대해 타입 검증 및 기본값 설정
        for key, default in default_values.items():
            if key not in analysis:
                logger.warning(f"'{key}'이(가) 응답에 없습니다. 기본값을 사용합니다.")
                analysis[key] = default
            elif not isinstance(analysis[key], list):
                logger.warning(f"'{key}'이(가) 리스트가 아닙니다. 리스트로 변환합니다.")
                analysis[key] = [analysis[key]]
            elif len(analysis[key]) < len(default):
                logger.warning(f"'{key}'의 항목 수가 부족합니다. 기본값으로 채웁니다.")
                analysis[key].extend(default[len(analysis[key]):])

        return analysis

    except Exception as e:
        logger.error(f"주제 분석 중 오류 발생: {e}")
        raise

def generate_content_prompt(topic, analysis):
    prompt = f"""
주제: {topic}

분석 결과:
{json.dumps(analysis, indent=2, ensure_ascii=False)}

위 주제와 분석 결과를 바탕으로 다음 지침에 따라 블로그 포스트를 작성해 주세요:

1. 글의 전체 길이는 정확히 2000-3000 단어 사이여야 합니다. 현재 단어 수: [CURRENT_WORD_COUNT]
2. 도입부에서 반드시 주제인 '{topic}'를 언급하고, 그 중요성과 시사성을 강조하며 독자의 관심을 끌어주세요. (최소 150단어)
3. 분석 결과의 '주요 이슈 또는 논점' 5가지를 모두 다루되, 각각에 대해 최소 200단어 이상 설명해 주세요.
4. '연관 키워드' 10개를 모두 사용하고, 각 키워드를 사용할 때마다 굵은 글씨로 강조해 주세요. (예: <strong>키워드</strong>)
5. '관련 통계 또는 데이터' 3가지를 모두 포함하고, 각 데이터를 인용할 때 출처를 명시해 주세요. 각 통계나 데이터에 대해 최소 100단어 이상의 분석을 제공해주세요.
6. '전문가 의견' 3가지를 모두 인용하고, 각 의견에 대한 맥락을 제공해 주세요. 각 전문가 의견에 대해 최소 100단어 이상의 추가 설명이나 분석을 덧붙여주세요.
7. '미래 전망' 3가지를 모두 언급하고, 각 전망이 주제에 미칠 영향을 구체적으로 설명해 주세요. 각 전망에 대해 최소 150단어 이상 작성해주세요.
8. '독자 행동 제안' 5가지를 모두 포함하고, 각 제안에 대한 구체적인 실행 방법과 예상되는 효과를 제시해 주세요. 각 제안에 대해 최소 100단어 이상 설명해주세요.
9. 글로벌한 시각에서 주제를 다루되, 한국 독자들에게 특히 의미 있는 내용을 포함해 주세요.
10. 각 문단을 자연스럽게 연결하고, 읽기 쉬운 톤을 유지해 주세요.
11. HTML 태그를 사용하여 구조를 명확히 하되, 섹션 제목은 <h2> 태그를 사용해 주세요.
12. 주제인 '{topic}'를 최소 30번 이상 언급해 주세요. 현재 언급 횟수: [CURRENT_TOPIC_MENTIONS]

다음 HTML 구조를 반드시 사용해 주세요:
<article>
    <h1>[제목: 반드시 '{topic}' 포함]</h1>
    <p>[도입부: 주제의 중요성과 시사성 강조, 최소 150단어]</p>
    <h2>배경 및 현황</h2>
    <p>[주제 소개 및 배경, 최소 200단어]</p>
    <h2>주요 이슈 및 논점</h2>
    <p>[본문 내용 - 여러 개의 <p> 태그 사용, 각 이슈별 최소 200단어]</p>
    <h2>관련 통계 및 데이터</h2>
    <p>[실제 사례 또는 통계, 각 데이터별 최소 100단어 분석]</p>
    <h2>전문가 의견</h2>
    <p>[전문가 의견 인용 및 분석, 각 의견별 최소 100단어 추가 설명]</p>
    <h2>미래 전망</h2>
    <p>[향후 전망, 각 전망별 최소 150단어]</p>
    <h2>독자 행동 제안</h2>
    <p>[독자 행동 제안, 각 제안별 최소 100단어 설명]</p>
    <h2>결론</h2>
    <p>[주제의 중요성 재강조 및 요약, 최소 200단어]</p>
</article>

주의: 
1. 모든 내용은 반드시 주제인 '{topic}'와 직접적으로 연관되어야 합니다. 주제와 관련 없는 내용은 포함하지 마세요.
2. 위의 모든 요구사항을 반드시 충족해야 합니다. 하나라도 누락되면 안 됩니다.
3. 각 섹션에서 주제인 '{topic}'를 반복적으로 언급하세요.
4. 모든 연관 키워드, 통계, 전문가 의견, 미래 전망, 독자 행동 제안을 반드시 포함해야 합니다.
5. 글의 길이가 2000-3000 단어 사이가 되도록 주의해주세요.
6. 각 섹션의 내용이 충분히 상세하고 깊이 있게 다뤄져야 합니다.
"""
    return prompt

def generate_feedback(topic, analysis, content):
    soup = BeautifulSoup(content, 'html.parser')
    content_lower = content.lower()
    topic_lower = topic.lower()
    word_count = len(content.split())
    topic_mentions = content_lower.count(topic_lower)
    
    feedback = "이전 응답은 다음 요구사항을 충족하지 않았습니다:\n"
    
    if word_count < 2000 or word_count > 3000:
        feedback += f"- 단어 수가 {word_count}로, 2000-3000 범위를 벗어났습니다. 정확히 이 범위 내로 작성해주세요.\n"
    
    if topic_mentions < 30:
        feedback += f"- '{topic}' 주제가 {topic_mentions}번 언급되어, 최소 30번 언급되어야 하는 요구사항을 충족하지 못했습니다. 더 자주 언급해주세요.\n"
    
    keywords = [kw.lower() for kw in analysis['연관 키워드']]
    missing_keywords = [kw for kw in keywords if kw not in content_lower]
    if missing_keywords:
        feedback += f"- 다음 키워드가 포함되지 않았습니다: {', '.join(missing_keywords)}. 모든 키워드를 반드시 포함해주세요.\n"
    
    sections = soup.find_all(['h1', 'h2', 'p'])
    section_word_counts = [len(section.get_text().split()) for section in sections]
    
    if len(soup.find_all('h2')) < 7:
        feedback += "- 일부 필수 섹션이 누락되었습니다. 모든 필수 섹션을 포함해주세요.\n"
    
    for i, count in enumerate(section_word_counts[1:], 1):  # 첫 번째 섹션(제목)을 제외
        if count < 100:
            feedback += f"- 섹션 {i}의 단어 수가 {count}로, 최소 100단어 요구사항을 충족하지 못했습니다. 더 상세히 작성해주세요.\n"
    
    if sum(1 for stat in analysis['관련 통계 또는 데이터'] if stat.lower() in content_lower) < len(analysis['관련 통계 또는 데이터']):
        feedback += "- 일부 통계 또는 데이터가 포함되지 않았습니다. 모든 통계와 데이터를 반드시 포함하고, 각각에 대한 분석을 추가해주세요.\n"
    
    if sum(1 for opinion in analysis['전문가 의견'] if opinion.lower() in content_lower) < len(analysis['전문가 의견']):
        feedback += "- 일부 전문가 의견이 포함되지 않았습니다. 모든 전문가 의견을 반드시 포함하고, 각 의견에 대한 추가 설명을 제공해주세요.\n"
    
    if sum(1 for prospect in analysis['미래 전망'] if prospect.lower() in content_lower) < len(analysis['미래 전망']):
        feedback += "- 일부 미래 전망이 포함되지 않았습니다. 모든 미래 전망을 반드시 포함하고, 각 전망이 주제에 미칠 영향을 상세히 설명해주세요.\n"
    
    if sum(1 for suggestion in analysis['독자 행동 제안'] if suggestion.lower() in content_lower) < len(analysis['독자 행동 제안']):
        feedback += "- 일부 독자 행동 제안이 포함되지 않았습니다. 모든 독자 행동 제안을 반드시 포함하고, 각 제안에 대한 구체적인 실행 방법과 예상 효과를 설명해주세요.\n"
    
    return feedback

@retry_with_backoff(retries=5)
def generate_blog_content(topic, analysis):
    logger.info(f"'{topic}' 주제로 블로그 콘텐츠 생성 중...")
    prompt = generate_content_prompt(topic, analysis)

    for attempt in range(5):  # 최대 5번 시도
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo-16k",
                messages=[
                    {"role": "system", "content": "You are an expert blog writer who always follows instructions precisely. You must create content that exactly matches the given criteria."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            content = response.choices[0].message.content.strip()
            
            if is_content_relevant(topic, analysis, content):
                return content
            else:
                logger.warning(f"생성된 내용이 '{topic}' 주제와 충분히 일치하지 않습니다. 다시 시도합니다. (시도 {attempt + 1}/5)")
                
                # 피드백 제공
                feedback = generate_feedback(topic, analysis, content)
                
                prompt = prompt.replace("[CURRENT_WORD_COUNT]", str(len(content.split())))
                prompt = prompt.replace("[CURRENT_TOPIC_MENTIONS]", str(content.lower().count(topic.lower())))
                prompt += f"\n\n이전 응답에 대한 피드백:\n{feedback}\n위의 피드백을 반영하여 다시 작성해 주세요. 모든 요구사항을 반드시 충족해야 합니다."

        except Exception as e:
            logger.error(f"{topic} 주제의 콘텐츠 생성 중 오류 발생: {e}")
            raise

    logger.error(f"'{topic}' 주제의 블로그 포스트 생성에 최종적으로 실패했습니다.")
    return None

@retry_with_backoff(retries=5)
def search_images(topic, analysis, num_images=5):
    logger.info(f"'{topic}' 주제에 대한 이미지 검색 중...")
    
    keywords = analysis['연관 키워드'][:5]  # 상위 5개 키워드 사용
    image_urls = []
    
    for keyword in keywords:
        if len(image_urls) >= num_images:
            break
        
        search_query = f"{topic} {keyword}"
        
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional translator."},
                    {"role": "user", "content": f"Translate the following search query to English: {search_query}"}
                ],
                max_tokens=50
            )
            english_query = response.choices[0].message.content.strip()
            
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.google.com'}
            search_url = f"https://www.googleapis.com/customsearch/v1?q={urllib.parse.quote(english_query)}&searchType=image&key={google_api_key}&cx={google_cse_id}&num={num_images - len(image_urls)}&rights=cc_publicdomain|cc_attribute|cc_sharealike|cc_noncommercial|cc_nonderived"
            
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            search_results = response.json()
            
            if 'items' in search_results:
                for item in search_results['items']:
                    if is_image_valid(item):
                        image_urls.append((item['link'], item.get('snippet', '')))
                        logger.info(f"이미지 찾음: {item['link']} (쿼리: {english_query})")
                    if len(image_urls) >= num_images:
                        break
            else:
                logger.warning(f"'{english_query}' 검색어에 대한 결과가 없습니다.")
        
        except Exception as e:
            logger.error(f"이미지 검색 중 오류 발생: {e}")
    
    logger.info(f"'{topic}' 주제에 대한 이미지 {len(image_urls)}개를 찾았습니다.")
    return image_urls

def is_image_valid(image_item):
    try:
        response = requests.get(image_item['link'], timeout=5)
        img = Image.open(BytesIO(response.content))
        width, height = img.size
        if width < 300 or height < 300:
            logger.warning(f"이미지 크기가 너무 작습니다: {width}x{height}")
            return False
        if img.format.lower() not in ['jpeg', 'png', 'gif']:  # 여기서 'gif'를 문자열로 변경
            logger.warning(f"지원하지 않는 이미지 포맷입니다: {img.format}")
            return False
        return True
    except Exception as e:
        logger.warning(f"이미지 체크 중 오류 발생: {e}")
        return False

@retry_with_backoff(retries=3)
def post_to_blogger(service, title, content, image_urls):
    logger.info(f"'{title}' 제목의 블로그 포스트를 Blogger에 게시 중...")
    
    css = """
    <style>
        body { font-family: 'Nanum Gothic', sans-serif; line-height: 1.8; color: #333; background-color: #f4f4f4; }
        .container { max-width: 800px; margin: 0 auto; padding: 20px; background-color: #fff; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; font-size: 2.5em; margin-bottom: 0.5em; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        p { margin-bottom: 1.5em; text-align: justify; }
        .highlight { background-color: #f9f871; padding: 2px 5px; border-radius: 3px; }
        .animated-text { animation: fadeIn 1s ease-in-out; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        img { max-width: 100%; height: auto; margin: 20px 0; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }
        figcaption { text-align: center; font-style: italic; margin-top: 10px; color: #666; }
        blockquote { background-color: #f9f9f9; border-left: 5px solid #3498db; padding: 15px; margin: 20px 0; font-style: italic; }
        .conclusion { background-color: #e8f4f8; padding: 15px; border-radius: 5px; margin-top: 30px; }
    </style>
    """
    
    # HTML 파싱
    soup = BeautifulSoup(content, 'html.parser')
    
    # 이미지 추가
    paragraphs = soup.find_all('p')
    for i, img_info in enumerate(image_urls):
        if i < len(paragraphs):
            image_url, image_description = img_info
            image_tag = soup.new_tag('figure')
            img = soup.new_tag('img', src=image_url, alt=image_description)
            caption = soup.new_tag('figcaption')
            caption.string = image_description
            image_tag.append(img)
            image_tag.append(caption)
            paragraphs[i].insert_after(image_tag)
    
    content_with_images = str(soup)
    
    body = {
        "title": title,
        "content": f"{css}<div class='container'><div class='animated-text'>{content_with_images}</div></div>"
    }
    
    try:
        post = service.posts().insert(blogId=blogger_blog_id, body=body).execute()
        logger.info(f"'{title}' 제목의 블로그 포스트가 성공적으로 게시되었습니다. (포스트 ID: {post['id']})")
    except Exception as e:
        logger.error(f"'{title}' 제목의 블로그 포스트 게시 중 오류 발생: {e}")
        raise

def main():
    logger.info("블로그 자동화 프로세스 시작")
    try:
        auth = GoogleAuth()
        credentials = auth.get_credentials()
        if credentials is None:
            logger.error("Google 인증 실패. 프로그램을 종료합니다.")
            return

        logger.info("Google 서비스 빌드 중...")
        service = build('blogger', 'v3', credentials=credentials)
        logger.info("Google 서비스 빌드 완료")
        
        while not exit_flag.is_set():
            try:
                logger.info("새로운 블로그 포스트 작성 주기 시작")
                trending_topics = get_trending_topics()
                if not trending_topics:
                    logger.error("트렌딩 주제를 가져오지 못했습니다. 30분 후 다시 시도합니다.")
                    time.sleep(1800)
                    continue

                for topic in trending_topics:
                    logger.info(f"'{topic}' 주제 분석 중...")
                    analysis = analyze_topic(topic)
                    
                    logger.info(f"'{topic}' 주제에 대한 블로그 내용 생성 중...")
                    blog_content = generate_blog_content(topic, analysis)
                    
                    if not blog_content:
                        logger.error(f"'{topic}' 주제의 블로그 포스트 생성에 실패했습니다. 다음 주제로 넘어갑니다.")
                        continue

                    logger.info(f"'{topic}' 주제에 대한 이미지 검색 중...")
                    image_urls = search_images(topic, analysis, num_images=5)
                    if not image_urls:
                        logger.warning(f"'{topic}' 주제에 대한 이미지를 찾지 못했습니다. 이미지 없이 진행합니다.")
                    
                    logger.info(f"'{topic}' 주제의 블로그 포스트 게시 중...")
                    post_to_blogger(service, topic, blog_content, image_urls)
                    
                    logger.info(f"'{topic}' 주제의 블로그 포스트 작성 및 게시가 완료되었습니다.")
                    logger.info("1시간 대기 후 다음 포스트 작성을 시작합니다.")
                    time.sleep(3600)  # 1시간 대기 후 다음 포스트 작성
                    break  # 성공적으로 포스트를 작성했으므로 루프 종료

                else:  # for 루프가 break 없이 완료된 경우 (모든 주제에 대해 실패)
                    logger.warning("모든 주제에 대해 포스트 작성에 실패했습니다. 30분 후 다시 시도합니다.")
                    time.sleep(1800)

            except Exception as e:
                logger.error(f"블로그 포스트 작성 중 오류 발생: {e}")
                logger.info("5분 후 다시 시도합니다.")
                time.sleep(300)  # 오류 발생 시 5분 대기 후 다시 시도

    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {e}")
    finally:
        if exit_flag.is_set():
            logger.info("프로그램이 안전하게 종료되었습니다.")

if __name__ == "__main__":
    main()
