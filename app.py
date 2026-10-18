from flask import Flask, jsonify, redirect, request, Response
import asyncio
import aiohttp
import re
import time
from urllib.parse import unquote, urljoin

app = Flask(__name__)

# Kanal ID'sine göre dinamik API URL üreten fonksiyon
def get_channel_api_url(channel_id):
    return f"https://aloula.faulio.com/api/v1.1/channels/{channel_id}/player"

# Her kanal için ayrı cache tutmak adına sözlük yapısı
cache = {}

async def fetch_fresh_hls(channel_id):
    """Belirtilen kanal ID'si için dış API'den en taze HLS master linkini çeker."""
    api_url = get_channel_api_url(channel_id)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=4) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("streams", {}).get("hls")
    except Exception as e:
        print(f"Kanal {channel_id} API İstek Hatası: {e}")
    return None

async def get_latest_hls_url(channel_id):
    """Her kanal için ayrı cache mekanizması (1 saniye taze tutma)."""
    current_time = time.time()
    
    if channel_id not in cache:
        cache[channel_id] = {"hls_url": None, "timestamp": 0}
        
    channel_cache = cache[channel_id]
    
    if not channel_cache["hls_url"] or (current_time - channel_cache["timestamp"]) >= 1.0:
        new_url = await fetch_fresh_hls(channel_id)
        if new_url:
            channel_cache["hls_url"] = new_url
            channel_cache["timestamp"] = current_time
            
    return channel_cache["hls_url"]

def extract_token_from_url(url):
    match = re.search(r'(hdntl=[^/&"\']+)', url)
    return match.group(1) if match else None

@app.route('/api/latest/<int:channel_id>', methods=['GET'])
def api_latest(channel_id):
    """Dinamik JSON API Endpoint'i"""
    hls_url = asyncio.run(get_latest_hls_url(channel_id))
    if not hls_url:
        return jsonify({"error": "Yayın kaynağına ulaşılamadı"}), 500
    
    server_host = f"{request.scheme}://{request.host}"
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    return jsonify({
        "status": "success",
        "channel_id": channel_id,
        "server_host": server_host,
        "client_ip": client_ip,
        "hls_url": hls_url,
        "token": extract_token_from_url(hls_url),
        "timestamp": cache[channel_id]["timestamp"]
    })

@app.route('/live/<int:channel_id>.m3u8', methods=['GET'])
def dynamic_m3u8_redirect(channel_id):
    """Kanal ID'sine göre ana m3u8 yönlendirme endpoint'i (HTTP 302)"""
    hls_url = asyncio.run(get_latest_hls_url(channel_id))
    if not hls_url:
        return "Yayın kaynağına ulaşılamadı!", 500

    latest_token = extract_token_from_url(hls_url)
    target_url = hls_url
    if latest_token:
        old_token = extract_token_from_url(target_url)
        if old_token:
            target_url = target_url.replace(old_token, latest_token)

    return redirect(target_url, code=302)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
