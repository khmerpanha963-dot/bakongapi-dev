from flask import Flask, request, jsonify, send_file, render_template
from bakong_khqr import KHQR
import qrcode
import io
import random
import string
import time
import threading
from dotenv import load_dotenv
import requests

# =============================
# LOAD ENV
# =============================
load_dotenv()

# =============================
# CONFIG
# =============================
API_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiOTg4YTA0ZGVhMTYyNGY1MCJ9LCJpYXQiOjE3NjY5OTc3MDksImV4cCI6MTc3NDc3MzcwOX0.9RDVxBx5kWMnckgp8TKj-bUNa5n9DWo_mxbmkBNqgkk"

QR_EXPIRE_SECONDS = 15 * 60   # 15 minutes
PAID_DELETE_DELAY = 2 * 60    # 2 minutes

# Telegram Configuration
TELEGRAM_BOT_TOKEN = "8509549331:AAF1ll4RxErMq3iO6fff9QuuT4TX0Gny0rc"
GROUP_SEND_MD5 = "-1003316684204"

# Initialize Flask & KHQR
app = Flask(__name__)
khqr = KHQR(API_TOKEN)

# In-memory storage
PAYMENTS = {}

# =============================
# UTILS
# =============================
def random_id(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def schedule_paid_delete(md5):
    """Mark payment QR deleted after PAID_DELETE_DELAY"""
    def delayed():
        time.sleep(PAID_DELETE_DELAY)
        payment = PAYMENTS.get(md5)
        if payment and payment["status"] == "PAID":
            payment["qr_deleted"] = True
    threading.Thread(target=delayed, daemon=True).start()

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not GROUP_SEND_MD5:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": GROUP_SEND_MD5, "text": text}, timeout=10)
    except Exception as e:
        print(f"Error sending to Telegram: {e}")

def is_valid_bakong_id(bakong_id):
    try:
        resp = requests.get("https://bakong-id-check.vercel.app/api/bakong_id", timeout=5)
        if resp.status_code != 200:
            return False
        return bakong_id in resp.json().get("bakong_ids", [])
    except Exception as e:
        print("Error checking bakong_id:", e)
        return False

# =============================
# CREATE KHQR
# =============================
@app.route("/api/khqr/create", methods=["GET"])
def create_khqr():
    try:
        bakong_id = request.args.get("bakong_id")
        merchant_name = request.args.get("merchantname")
        amount = request.args.get("amount")

        if not bakong_id or not merchant_name or not amount:
            return jsonify({"success": False, "error": "Missing bakong_id, merchantname, or amount"}), 400

        if not is_valid_bakong_id(bakong_id):
            return jsonify({"success": False, "error": "bakong_id not allowed"}), 403

        amount = float(amount)
        ref_id = random_id()

        khqr_string = khqr.create_qr(
            bank_account=bakong_id,
            merchant_name=merchant_name,
            merchant_city="PhnomPenh",
            amount=amount,
            currency="USD",
            store_label="Store",
            phone_number="85512345678",
            bill_number=ref_id,
            terminal_label="T-01",
            static=False
        )

        md5 = khqr.generate_md5(khqr_string)

        # Save in memory
        PAYMENTS[md5] = {
            "bakong_id": bakong_id,
            "amount": amount,
            "khqr_string": khqr_string,
            "created_at": time.time(),
            "status": "PENDING",
            "qr_deleted": False
        }

        # Send MD5 to Telegram
        send_telegram_message(md5)

        # Return JSON with URL
        return jsonify({
            "khqrString": khqr_string,
            "md5": md5,
            "bakong_qr": f"www.bakongapi-dev.shop/bakong-qr?md5={md5}"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# =============================
# SERVE QR IMAGE
# =============================
@app.route("/bakong-qr")
def serve_qr():
    md5 = request.args.get("md5")
    if not md5 or md5 not in PAYMENTS:
        return "QR not found", 404

    payment = PAYMENTS[md5]
    if payment.get("qr_deleted"):
        return "QR expired", 410

    qr_img = qrcode.make(payment["khqr_string"])
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# =============================
# CHECK PAYMENT (EXTERNAL API)
# =============================
@app.route("/api/khqr/check", methods=["GET"])
def check_khqr_payment():
    md5 = request.args.get("md5")
    bakong_id = request.args.get("bakong_id")

    if not md5 or not bakong_id:
        return jsonify({"success": False, "error": "Missing md5 or bakong_id"}), 400

    if not is_valid_bakong_id(bakong_id):
        return jsonify({"success": False, "error": "bakong_id not allowed"}), 403

    # Always query external API
    try:
        resp = requests.get(
            "https://panhakoko999.pythonanywhere.com/api/check",
            params={"md5": md5},
            timeout=10
        )
        data = resp.json()
        status = data.get("status", "PENDING")  # default PENDING if unknown
    except Exception as e:
        status = "PENDING"  # if external API fails, default PENDING

    # Save/update in memory (optional)
    PAYMENTS[md5] = PAYMENTS.get(md5, {})
    PAYMENTS[md5]["status"] = status

    return jsonify({
        "success": True,
        "status": status,
        "bakong_id": bakong_id,
        "amount": PAYMENTS.get(md5, {}).get("amount", 0)
    })

@app.route("/")
def api_doc():
    return render_template(
        "doc.html",
        title="Bakong KHQR API Documentation",
        description="KHQR payment API for Bakong Cambodia. Create QR codes, check payment status"
    )


# =============================
# RUN SERVER
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)






