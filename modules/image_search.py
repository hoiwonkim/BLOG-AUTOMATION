# modules/image_search.py

import requests
from config import GOOGLE_API_KEY, GOOGLE_CSE_ID

def search_image(query):
    search_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'q': query,
        'cx': GOOGLE_CSE_ID,
        'key': GOOGLE_API_KEY,
        'searchType': 'image',
        'num': 1
    }
    
    response = requests.get(search_url, params=params).json()
    
    if 'items' not in response or len(response['items']) == 0:
        print("No images found in the search results. Using a default image.")
        image_url = "https://via.placeholder.com/150"  # 대체 이미지 URL
    else:
        image_url = response['items'][0]['link']
    
    img_data = requests.get(image_url).content
    image_path = 'image.jpg'
    with open(image_path, 'wb') as handler:
        handler.write(img_data)
    
    return image_path

# 테스트 스크립트
if __name__ == "__main__":
    query = "Why is Chile so long?"
    print(search_image(query))
