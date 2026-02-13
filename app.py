import requests
import re
from flask import Flask, Response, request

app = Flask(__name__)

# আপনার আইপি 
MY_IP = "192.168.31.109"
PORT = "5000"
SERVER_URL = f"http://{MY_IP}:{PORT}/"

BASE_HOST = "https://backend.plusbox.tv"
TOKEN_API = "https://plusbox.tv/token.php"

# আপনার দেওয়া গিটহাব প্লেলিস্ট লিংক
GITHUB_URL = "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/CloudTV.m3u"

HEADERS = {
    "referer": "https://plusbox.tv/",
    "origin": "https://plusbox.tv",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_live_token(ch_name):
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


@app.route('/playlist.m3u')
def generate_full_playlist():
    print("\n[+] GitHub থেকে সম্পূর্ণ প্লেলিস্ট ডাউনলোড করা হচ্ছে...")
    try:
        # GitHub থেকে লেটেস্ট লিস্ট আনা
        resp = requests.get(GITHUB_URL, headers={"User-Agent": "Mozilla/5.0"})
        lines = resp.text.splitlines()
        
        new_lines = []
        channel_count = 0
        
        for line in lines:
            line = line.strip()
            
            # যদি লাইনটি স্ট্রিম লিংক হয়
            if line.startswith("http"):
                # যদি এটি Plusbox এর চ্যানেল হয়, তবে আমাদের প্রক্সি সার্ভারে পাঠাবো
                if "backend.plusbox.tv" in line:
                    parts = line.split('/')
                    if len(parts) > 3:
                        ch_name = parts[3]
                        ch_name = ch_name.split('?')[0] # টোকেন বা এক্সট্রা কিছু থাকলে বাদ দেওয়া
                        
                        # আপনার আইপি দিয়ে লোকাল লিংক তৈরি
                        local_url = f"{SERVER_URL}live/{ch_name}/index.m3u8"
                        new_lines.append(local_url)
                        channel_count += 1
                    else:
                        new_lines.append(line)
                        channel_count += 1
                # যদি অন্য কোনো সার্ভারের লিংক হয়, তবে সরাসরি সেটাই দিয়ে দিবো
                else:
                    new_lines.append(line)
                    channel_count += 1
            else:
                # #EXTINF (চ্যানেলের নাম, লোগো) ইত্যাদি ঠিক রাখা
                new_lines.append(line)
                
        print(f"[+] সফলভাবে {channel_count} টি চ্যানেলের লিস্ট তৈরি হয়েছে!")
        
        # ফাইলটি যেন ডাউনলোড হয় এবং প্লেয়ার বুঝতে পারে, তার জন্য সঠিক হেডার
        return Response(
            "\n".join(new_lines), 
            mimetype="audio/x-mpegurl", 
            headers={"Content-Disposition": "attachment; filename=playlist.m3u"}
        )
        
    except Exception as e:
        print(f"[-] Error loading playlist: {str(e)}")
        return f"Error loading playlist: {str(e)}", 500


@app.route('/live/<ch_name>/index.m3u8')
def master_playlist(ch_name):
    print(f"\n[>] চ্যানেল রিকোয়েস্ট: {ch_name}")
    
    token = get_live_token(ch_name)
    if not token:
        print(f"[-] টোকেন পাওয়া যায়নি! চ্যানেল: {ch_name}")
        return "Auth Failed - Token not found", 403

    print(f"[+] টোকেন পাওয়া গেছে: {token[:10]}...")
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
        print(f"[-] Error: {e}")
        return f"Error: {e}", 500


@app.route('/live/<ch_name>/<path:file_path>')
def dynamic_handler(ch_name, file_path):
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
            return Response(r.iter_content(chunk_size=1024 * 512), content_type=content_type)

    except Exception as e:
        print(f"[-] Segment Error: {e}")
        return "Segment Error", 500

if __name__ == '__main__':
    print("🚀 Auto-Token Server is Running with Full GitHub Playlist!")
    print(f"📺 আপনার প্লেয়ারে এই লিংকটি দিন: http://{MY_IP}:5000/playlist.m3u")
    app.run(host='0.0.0.0', port=5000)