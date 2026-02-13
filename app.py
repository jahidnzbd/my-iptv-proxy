import requests
import re
from flask import Flask, Response, request

app = Flask(__name__)

BASE_HOST = "https://backend.plusbox.tv"
TOKEN_API = "https://plusbox.tv/token.php"

# GitHub থেকে অটোমেটিক আপডেট হওয়া প্লেলিস্ট
GITHUB_URL = "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/CloudTV.m3u"

HEADERS = {
    "referer": "https://plusbox.tv/",
    "origin": "https://plusbox.tv",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_server_url():
    """ক্লাউড সার্ভারের জন্য ডাইনামিক এবং সিকিউর (HTTPS) URL তৈরি করা"""
    url = request.host_url
    # Render.com-এ হোস্ট করলে যাতে লিংকটি সব সময় https:// থাকে
    if "onrender.com" in url and url.startswith("http://"):
        url = url.replace("http://", "https://")
    return url

def get_live_token(ch_name):
    """Plusbox থেকে ফ্রেশ টোকেন নিয়ে আসা"""
    try:
        payload = {"ch_name": ch_name}
        resp = requests.post(TOKEN_API, data=payload, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            token = resp.text.strip()
            if token and "<" not in token:
                return token
    except Exception as e:
        print(f"[-] Token Error: {e}")
    return None

def rewrite_m3u8(m3u8_text, query_string):
    """প্লেলিস্টের ভেতরের ভিডিও খণ্ডগুলোতে টোকেন ইনজেক্ট করা"""
    if not query_string:
        return m3u8_text
        
    lines = m3u8_text.splitlines()
    new_lines = []
    
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if not line.startswith('http'):
                connector = '&' if '?' in line else '?'
                line = f"{line}{connector}{query_string}"
                
        elif line.startswith('#EXT-X-KEY') and 'URI="' in line:
            match = re.search(r'URI="([^"]+)"', line)
            if match:
                original_uri = match.group(1)
                if not original_uri.startswith('http'):
                    connector = '&' if '?' in original_uri else '?'
                    new_uri = f"{original_uri}{connector}{query_string}"
                    line = line.replace(f'URI="{original_uri}"', f'URI="{new_uri}"')
                    
        new_lines.append(line)
        
    return "\n".join(new_lines)


@app.route('/')
def home():
    """হোমপেজ চেক করার জন্য"""
    server_url = get_server_url()
    return f"<h3>✅ Cloud IPTV Server is Running!</h3><p>আপনার প্লেয়ারে এই লিংকটি দিন: <b>{server_url}playlist.m3u</b></p>"


@app.route('/playlist.m3u')
def generate_full_playlist():
    """ফাইনাল প্লেলিস্ট জেনারেটর"""
    try:
        resp = requests.get(GITHUB_URL, headers={"User-Agent": "Mozilla/5.0"})
        lines = resp.text.splitlines()
        
        server_url = get_server_url()
        new_lines = []
        
        for line in lines:
            line = line.strip()
            if line.startswith("http"):
                # Plusbox-এর লিংক হলে আমাদের সার্ভারের লিংক দিয়ে রিপ্লেস করবে
                if "backend.plusbox.tv" in line:
                    parts = line.split('/')
                    if len(parts) > 3:
                        ch_name = parts[3]
                        ch_name = ch_name.split('?')[0] 
                        
                        local_url = f"{server_url}live/{ch_name}/index.m3u8"
                        new_lines.append(local_url)
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        return Response(
            "\n".join(new_lines), 
            mimetype="audio/x-mpegurl", 
            headers={"Content-Disposition": "attachment; filename=playlist.m3u"}
        )
        
    except Exception as e:
        return f"Error loading playlist: {str(e)}", 500


@app.route('/live/<ch_name>/index.m3u8')
def master_playlist(ch_name):
    """অরিজিনাল চ্যানেল থেকে ডেটা টেনে প্রক্সি করা"""
    token = get_live_token(ch_name)
    if not token:
        return "Auth Failed - Token not found", 403

    remote_url = f"{BASE_HOST}/{ch_name}/index.m3u8?token={token}"

    try:
        r = requests.get(remote_url, headers=HEADERS)
        if r.status_code == 404:
            remote_url = f"{BASE_HOST}/{ch_name}/index.fmp4.m3u8?token={token}"
            r = requests.get(remote_url, headers=HEADERS)

        query_string = f"token={token}"
        modified_m3u8 = rewrite_m3u8(r.text, query_string)
        
        return Response(modified_m3u8, mimetype="application/vnd.apple.mpegurl")

    except Exception as e:
        return f"Error: {e}", 500


@app.route('/live/<ch_name>/<path:file_path>')
def dynamic_handler(ch_name, file_path):
    """ভিডিও সেগমেন্ট (.ts) প্রক্সি এবং বাফারিং হ্যান্ডলার"""
    query_string = request.query_string.decode("utf-8")
    remote_url = f"{BASE_HOST}/{ch_name}/{file_path}"
    
    if query_string:
        remote_url += f"?{query_string}"

    try:
        r = requests.get(remote_url, headers=HEADERS, stream=True)

        if r.status_code != 200:
            return Response(r.content, status=r.status_code)

        if file_path.endswith('.m3u8'):
            modified_m3u8 = rewrite_m3u8(r.text, query_string)
            return Response(modified_m3u8, mimetype="application/vnd.apple.mpegurl")
        
        else:
            content_type = r.headers.get('Content-Type', 'video/mp2t')
            # বাফারিং কমানোর জন্য চাংক সাইজ 1MB করা হয়েছে
            return Response(r.iter_content(chunk_size=1024 * 1024), content_type=content_type)

    except Exception as e:
        return "Segment Error", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
