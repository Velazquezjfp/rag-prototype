from openai import OpenAI

client = OpenAI(base_url="https://ollama-javi.duckdns.org:8684/v1", 
                api_key="d1jSb6F5mn3f3YprKS6b9jWX6HLbSHoYJBE0wyEm5CYauq5K")

response = client.chat.completions.create(model="ministral-3:8b",
    messages=[{"role": "user", "content": "hello"}])

print(response.choices[0].message.content)