#!/data/data/com.termux/files/usr/bin/bash
cd /data/data/com.termux/files/home/ntawebsearchapi
pkill -f "python3.*search_server\.py" 2>/dev/null || true
sleep 1
nohup python3 search_server.py >> search_server.log 2>&1 &
echo "Search server launched with PID $!"
