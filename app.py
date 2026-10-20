
from flask import Flask, request, jsonify, redirect, session
from flask_cors import CORS
import os, requests, random, json, secrets
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "free_secret_123")
CORS(app, supports_credentials=True)

# Config from .env - FREE
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")  # https://your-app.onrender.com/auth/callback
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "followgate_verify_123")

DB_FILE = "automations.json"
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "automations": {}}
def save_db(d):
    with open(DB_FILE, "w") as f:
        json.dump(d, f, indent=2)

# 1. LOGIN - يوجه العميل لصفحة السماح الرسمية
@app.route("/auth/login")
def auth_login():
    # Scopes المطلوبة للاوتوميشن الحقيقي
    scopes = [
        "instagram_basic",
        "instagram_manage_comments",
        "instagram_manage_messages",
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_metadata"
    ]
    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join(scopes),
        "response_type": "code",
        "state": secrets.token_urlsafe(16)
    }
    # Facebook OAuth Dialog - الرسمي
    fb_dialog = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
    return redirect(fb_dialog)

# 2. CALLBACK - بعد ما العميل يدوس سماح
@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return "فشل تسجيل الدخول", 400

    # بدل الكود بـ access_token
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    r = requests.get(token_url, params={
        "client_id": FB_APP_ID,
        "client_secret": FB_APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    })
    data = r.json()
    short_token = data.get("access_token")

    # حوله لـ long-lived token (60 يوم)
    long_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    r2 = requests.get(long_url, params={
        "grant_type": "fb_exchange_token",
        "client_id": FB_APP_ID,
        "client_secret": FB_APP_SECRET,
        "fb_exchange_token": short_token
    })
    long_token = r2.json().get("access_token", short_token)

    # هات الصفحات بتاعته
    pages_res = requests.get(f"https://graph.facebook.com/v19.0/me/accounts?access_token={long_token}").json()

    # هات اول صفحة مربوطة بانستجرام
    ig_data = None
    for page in pages_res.get("data", []):
        page_id = page["id"]
        page_token = page["access_token"]
        ig_res = requests.get(f"https://graph.facebook.com/v19.0/{page_id}?fields=instagram_business_account&access_token={page_token}").json()
        if "instagram_business_account" in ig_res:
            ig_id = ig_res["instagram_business_account"]["id"]
            ig_info = requests.get(f"https://graph.facebook.com/v19.0/{ig_id}?fields=username,profile_picture_url&access_token={page_token}").json()
            ig_data = {
                "page_id": page_id,
                "page_token": page_token,
                "ig_id": ig_id,
                "username": ig_info.get("username"),
                "profile_pic": ig_info.get("profile_picture_url"),
                "long_token": long_token
            }
            break

    if not ig_data:
        return "مفيش حساب انستجرام بيزنس مربوط بصفحة فيسبوك. لازم تحول حسابك لبيزنس وتربطه بصفحة", 400

    # احفظ اليوزر
    db = load_db()
    db["users"][ig_data["ig_id"]] = ig_data
    save_db(db)

    # رجعه للفرونت مع التوكن
    frontend_url = os.getenv("FRONTEND_URL", "https://your-frontend.com")
    return redirect(f"{frontend_url}?ig_id={ig_data['ig_id']}&username={ig_data['username']}&success=1")

# 3. WEBHOOK + AUTOMATIONS (نفس الكود السابق بس حقيقي)
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "fail", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    # ... نفس كود الرد + Follow Gate ...
    return "ok", 200

@app.route("/api/media/<ig_id>")
def media(ig_id):
    db = load_db()
    user = db["users"].get(ig_id)
    if not user:
        return jsonify({"error": "user not found"}), 404
    url = f"https://graph.facebook.com/v19.0/{ig_id}/media"
    r = requests.get(url, params={
        "access_token": user["page_token"],
        "fields": "id,caption,media_type,thumbnail_url,media_url,timestamp,like_count,comments_count"
    })
    return jsonify(r.json())

@app.route("/")
def home():
    return jsonify({"status": "FollowGate FREE OAuth Running", "login_url": "/auth/login"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
