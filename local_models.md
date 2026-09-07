Available models: 
lokaler-coder-qwen: ollama/qwen2.5-coder:32k
granite4: ollama_chat/granite4:latest
bge-m3: ollama/bge-m3:latest  


  URLs

  ┌───────────────────────────────┬────────────────────────────────────────────────┐
  │             What              │                      URL                       │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Base URL (for OpenAI clients) │ http://localhost:4000/v1                       │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Chat completions              │ POST http://localhost:4000/v1/chat/completions │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Embeddings                    │ POST http://localhost:4000/v1/embeddings       │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ List models                   │ GET http://localhost:4000/v1/models            │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Model → backend mapping       │ GET http://localhost:4000/model/info           │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Health                        │ GET http://localhost:4000/health/liveliness    │
  ├───────────────────────────────┼────────────────────────────────────────────────┤
  │ Admin UI                      │ http://localhost:4000/ui                       │
  └───────────────────────────────┴────────────────────────────────────────────────┘

  API key: sk-123456789 (as Authorization: Bearer sk-123456789).

  Bound to 0.0.0.0, so from your Windows host or another machine use http://172.30.90.147:4000/v1 — note WSL2
  reassigns that IP on reboot.

  Usage examples

  Python — OpenAI SDK

  from openai import OpenAI

  client = OpenAI(
      base_url="http://localhost:4000/v1",
      api_key="sk-123456789",
  )

  # Chat
  resp = client.chat.completions.create(
      model="granite4",                     # or lokaler-coder-qwen
      messages=[{"role": "user", "content": "Write a Python one-liner to reverse a list."}],
  )
  print(resp.choices[0].message.content)

  # Embeddings
  emb = client.embeddings.create(
      model="bge-m3",
      input=["Hallo Welt", "hello world", "hola mundo"],
  )
  print(len(emb.data), "vectors,", len(emb.data[0].embedding), "dims")

  Python — tool calling (confirmed working on both chat models)

  tools = [{
      "type": "function",
      "function": {
          "name": "get_weather",
          "description": "Get weather for a city",
          "parameters": {
              "type": "object",
              "properties": {"city": {"type": "string"}},
              "required": ["city"],
          },
      },
  }]

  resp = client.chat.completions.create(
      model="granite4",
      messages=[{"role": "user", "content": "Weather in Berlin?"}],
      tools=tools,
  )
  print(resp.choices[0].message.tool_calls)

  Node — openai package

  import OpenAI from "openai";

  const client = new OpenAI({
    baseURL: "http://localhost:4000/v1",
    apiKey: "sk-123456789",
  });

  const r = await client.chat.completions.create({
    model: "lokaler-coder-qwen",
    messages: [{ role: "user", content: "Explain async/await in one sentence." }],
  });
  console.log(r.choices[0].message.content);

  curl

  curl http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer sk-123456789" \
    -H "Content-Type: application/json" \
    -d '{"model":"granite4","messages":[{"role":"user","content":"Hi"}]}'

  curl http://localhost:4000/v1/embeddings \
    -H "Authorization: Bearer sk-123456789" \
    -H "Content-Type: application/json" \
    -d '{"model":"bge-m3","input":"Hallo Welt"}'

  Streaming works too — add "stream": true (or stream=True in the SDK).