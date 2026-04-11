curl -sS http://192.168.86.173:30080/v1/models
curl -sS http://192.168.86.176:30080/v1/models



curl http://192.168.86.179:30080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-7B-Instruct", "messages": [{"role": "user", "content": "how you introduce new york city"}], 
  "gpu-memory-utilization": 0.8,
  "max_tokens": 1000,
  "max-model-len": 8192, 
  "max-num-seqs": 32
  }'



for p in 20 40 60 80 100 120; do
  echo "=== concurrency $p ==="
  seq 1 200 | xargs -I{} -P $p sh -c '
    curl -s -o /dev/null -w "%{http_code}\n" http://192.168.86.179:8010/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"Qwen/Qwen2.5-7B-Instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"introduce new york city\"}],
\"max_tokens\":50}"
  ' | sort | uniq -c
done



curl http://192.168.86.179:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [{"role":"user","content":"introduce new york city"}],
    "stream": true
  }'