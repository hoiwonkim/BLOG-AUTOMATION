# modules/text_generator.py

import openai
from config import OPENAI_API_KEY

openai.api_key = OPENAI_API_KEY

def generate_blog_post(topic, link):
    prompt = f"""
    Write an engaging and detailed blog post about the topic '{topic}'.
    Include the following sections:
    1. Introduction: Briefly introduce the topic.
    2. Background: Provide some context and background information.
    3. Main Content: Discuss the main points in detail, incorporating information from the source {link}.
    4. Conclusion: Summarize the topic and provide any final thoughts.
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )

    return response['choices'][0]['message']['content'].strip()

# 테스트 스크립트
if __name__ == "__main__":
    topic = "Why is Chile so long?"
    link = "https://unchartedterritories.tomaspueyo.com/p/why-is-chile-so-long"
    print(generate_blog_post(topic, link))
