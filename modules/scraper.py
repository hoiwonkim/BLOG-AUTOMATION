# modules/scraper.py

import requests
from bs4 import BeautifulSoup

def get_trending_topic():
    url = 'https://news.ycombinator.com/'
    response = requests.get(url)
    
    # 요청이 성공적으로 완료되었는지 확인
    if response.status_code != 200:
        raise Exception(f"Failed to fetch page, status code: {response.status_code}")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 'athing' 클래스의 'tr' 요소들을 선택
    articles = soup.find_all('tr', class_='athing')
    if not articles:
        raise Exception("No articles found. The HTML structure might have changed.")
    
    # 첫 번째 'athing' 클래스의 'tr' 요소에서 기사 제목과 링크를 추출
    for article in articles:
        titleline = article.find('span', class_='titleline')
        if titleline:
            title_tag = titleline.find('a')
            if title_tag:
                title = title_tag.text
                link = title_tag['href']
                return title, link
        print(f"No storylink found in article with id: {article.get('id')}")
    
    raise Exception("No valid articles found. The HTML structure might have changed.")

# 테스트 스크립트
if __name__ == "__main__":
    try:
        topic, link = get_trending_topic()
        print(f"Trending topic: {topic}, Link: {link}")
    except Exception as e:
        print(f"An error occurred: {e}")
