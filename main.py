# main.py

import os
import openai
import requests
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse

# 환경 변수 로드
load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')
google_api_key = os.getenv('GOOGLE_API_KEY')
google_cse_id = os.getenv('GOOGLE_CSE_ID')
blogger_blog_id = os.getenv('BLOGGER_BLOG_ID')

# 전역 변수로 인증 코드 저장
auth_code = None

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        query_components = urllib.parse.parse_qs(query)
        auth_code = query_components.get('code', [None])[0]
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Authentication successful! You can close this window.')

def start_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, AuthHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    return httpd

def get_google_auth_credentials():
    global auth_code
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/blogger'],
        redirect_uri='http://localhost:8000'
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    print(f'다음 URL로 이동하여 인증을 완료하세요: {auth_url}')
    
    httpd = start_server()
    
    while auth_code is None:
        pass
    
    httpd.shutdown()
    
    flow.fetch_token(code=auth_code)
    return flow.credentials

def get_trending_topics():
    return ["인공지능의 미래", "기후 변화와 지속 가능성", "디지털 트랜스포메이션"]

def generate_blog_post(topic):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that writes blog posts."},
            {"role": "user", "content": f"{topic}에 대한 자세한 블로그 포스트를 작성해주세요."}
        ]
    )
    return response.choices[0].message['content']

def search_image(topic):
    search_url = f"https://www.googleapis.com/customsearch/v1?q={topic}&searchType=image&key={google_api_key}&cx={google_cse_id}"
    response = requests.get(search_url)
    results = response.json().get('items', [])
    if results:
        return results[0]['link']
    return None

def post_to_blogger(service, title, content, image_url):
    body = {
        "content": f"<h1>{title}</h1>\n{content}\n",
        "title": title
    }
    if image_url:
        body["content"] += f'<img src="{image_url}" alt="{title}">'
    
    service.posts().insert(blogId=blogger_blog_id, body=body).execute()

if __name__ == "__main__":
    credentials = get_google_auth_credentials()
    service = build('blogger', 'v3', credentials=credentials)
    trending_topics = get_trending_topics()
    for topic in trending_topics:
        blog_content = generate_blog_post(topic)
        image_url = search_image(topic)
        post_to_blogger(service, topic, blog_content, image_url)
    print("모든 블로그 포스트가 성공적으로 작성되었습니다.")
