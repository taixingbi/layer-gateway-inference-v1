curl -sS http://192.168.86.173:30080/v1/models
curl -sS http://192.168.86.176:30080/v1/models



curl http://192.168.86.179:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-7B-Instruct", "messages": [{"role": "user", "content": "where is jersey city"}], 
  "gpu-memory-utilization": 0.8,
  "max_tokens": 1000,
  "max-model-len": 8192, 
  "max-num-seqs": 32
  }'


