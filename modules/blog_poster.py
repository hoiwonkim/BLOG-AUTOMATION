# modules/blog_poster.py

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os.path
import pickle
import datetime
from config import BLOGGER_BLOG_ID

def authenticate_google_api():
    SCOPES = ['https://www.googleapis.com/auth/blogger']
    creds = None

    # token.pickle 파일이 있는지 확인하고 있으면 로드합니다.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # 자격 증명이 없거나 만료된 경우 새로 인증합니다.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # 자격 증명을 저장합니다.
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('blogger', 'v3', credentials=creds)
    return service

def post_to_blogger(title, content):
    service = authenticate_google_api()
    blog_id = BLOGGER_BLOG_ID
    body = {
        'kind': 'blogger#post',
        'title': title,
        'content': content,
        'published': datetime.datetime.now().isoformat()
    }
    posts = service.posts()
    request = posts.insert(blogId=blog_id, body=body)
    response = request.execute()
    return response

# 테스트 스크립트
if __name__ == "__main__":
    title = "Test Post"
    content = "This is a test post content."
    print(post_to_blogger(title, content))

