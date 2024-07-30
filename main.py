# main.py

import os
import openai
import requests
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

openai.api_key = os.getenv('OPENAI_API_KEY')
google_api_key = os.getenv('GOOGLE_API_KEY')
google_cse_id = os.getenv('GOOGLE_CSE_ID')
blogger_blog_id = os.getenv('BLOGGER_BLOG_ID')

# OAuth 2.0 설정
def get_google_auth_credentials():
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/blogger'],
        redirect_uri='http://localhost:8000'
    )
    
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    print(f'다음 URL로 이동하여 인증을 완료하세요: {auth_url}')
    auth_code = input('인증 코드를 입력하세요: ')
    
    flow.fetch_token(code=auth_code)
    return flow.credentials

credentials = get_google_auth_credentials()
service = build('blogger', 'v3', credentials=credentials)

def get_trending_topics():
    return ["인공지능의 미래"]

def generate_blog_post(topic):
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"{topic}에 대한 자세한 블로그 포스트를 작성해주세요.",
        max_tokens=500
    )
    return response.choices[0].text

def search_image(topic):
    search_url = f"https://www.googleapis.com/customsearch/v1?q={topic}&searchType=image&key={google_api_key}&cx={google_cse_id}"
    response = requests.get(search_url)
    results = response.json().get('items', [])
    if results:
        return results[0]['link']
    return None

def post_to_blogger(title, content, image_url):
    body = {
        "content": f"<h1>{title}</h1><br><img src='{image_url}'><br><p>{content}</p>",
        "title": title
    }
    service.posts().insert(blogId=blogger_blog_id, body=body).execute()

if __name__ == "__main__":
    trending_topics = get_trending_topics()
    for topic in trending_topics:
        blog_content = generate_blog_post(topic)
        image_url = search_image(topic)
        post_to_blogger(topic, blog_content, image_url)
