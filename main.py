# main.py

import os
import openai
import requests
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

openai.api_key = os.getenv('OPENAI_API_KEY')
google_api_key = os.getenv('GOOGLE_API_KEY')
google_cse_id = os.getenv('GOOGLE_CSE_ID')
blogger_blog_id = os.getenv('BLOGGER_BLOG_ID')
client_id = os.getenv('GOOGLE_CLIENT_ID')
client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

# OAuth 2.0 setup
def get_google_auth_credentials():
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["http://localhost:8000/"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=["https://www.googleapis.com/auth/blogger"]
    )
    credentials = flow.run_local_server(port=8000)
    return credentials

credentials = get_google_auth_credentials()
service = build('blogger', 'v3', credentials=credentials)

# Your code for fetching trending topics and generating blog posts remains unchanged
