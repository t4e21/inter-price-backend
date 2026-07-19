"""
app.py — باكيند Inter Price Car (ملف واحد شامل: قاعدة البيانات + واتساب OTP + دفع KNET + كل الـ API)
تشغيل: python app.py  ثم افتح http://localhost:5000/api/health

هذا الملف مدمج بالكامل (بدل عدة ملفات منفصلة) لتسهيل رفعه يدويًا لأي منصة استضافة أو GitHub
حتى من الجوال بدون الحاجة لرفع عدة ملفات بايثون منفصلة. باقي ملفين فقط مطلوبين بجنبه:
requirements.txt (المكتبات) و .env (مفاتيح Twilio/MyFatoorah الاختيارية).
"""
import base64
import os
import random
import sqlite3
import string
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)


# ============================================================
# ============  SECTION 1: DATABASE (SQLite)  ================
# ============================================================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inter_price_car.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    loyalty_points INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    daily_rate REAL,
    seats INTEGER,
    transmission TEXT,
    fuel TEXT,
    branch TEXT,
    rating REAL,
    reviews_count INTEGER,
    image_url TEXT,
    status TEXT DEFAULT 'available',
    financing_eligible INTEGER DEFAULT 0,
    cash_price REAL,
    monthly_from REAL,
    discount_percent INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rental_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_ref TEXT UNIQUE,
    user_id INTEGER REFERENCES users(id),
    car_id INTEGER REFERENCES cars(id),
    start_date TEXT,
    end_date TEXT,
    days INTEGER,
    branch_pickup TEXT,
    branch_dropoff TEXT,
    insurance INTEGER DEFAULT 1,
    promo_code TEXT,
    discount_amount REAL DEFAULT 0,
    total_price REAL,
    status TEXT DEFAULT 'confirmed',
    payment_id TEXT,
    payment_status TEXT DEFAULT 'paid',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    phone TEXT,
    car_model TEXT,
    plate TEXT,
    rating REAL,
    status TEXT DEFAULT 'online',
    trips_today INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ride_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    base_fare REAL,
    eta_minutes INTEGER,
    image_url TEXT
);

CREATE TABLE IF NOT EXISTS driver_rides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_ref TEXT UNIQUE,
    user_id INTEGER REFERENCES users(id),
    trip_type TEXT,
    pickup TEXT,
    dropoff TEXT,
    ride_class_id INTEGER REFERENCES ride_classes(id),
    hours INTEGER,
    timing_mode TEXT,
    scheduled_at TEXT,
    fare REAL,
    eta_minutes INTEGER,
    driver_id INTEGER REFERENCES drivers(id),
    status TEXT DEFAULT 'requested',
    rating INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financing_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_ref TEXT UNIQUE,
    user_id INTEGER REFERENCES users(id),
    car_id INTEGER REFERENCES cars(id),
    car_price REAL,
    down_payment REAL,
    duration_months INTEGER,
    monthly_installment REAL,
    status TEXT DEFAULT 'received',
    documents_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    type TEXT,
    title TEXT,
    body TEXT,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT,
    role TEXT DEFAULT 'operations'
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    fresh = not os.path.exists(DB_PATH)
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    if fresh:
        seed_db(conn)
    conn.close()


def seed_db(conn):
    cars = [
        ("لاندكروزر GXR 2025", "suv", 35, 7, "أوتوماتيك", "بنزين", "السالمية", 4.9, 128,
         "https://images.unsplash.com/photo-1756443773455-22e4f3d8d823?w=700&q=80&auto=format&fit=crop",
         "rented", 0, None, None, 0),
        ("نيسان صني 2024", "economy", 9, 5, "أوتوماتيك", "اقتصادي", "السالمية", 4.6, 64,
         "https://images.unsplash.com/photo-1564988190211-cfee63481d3a?w=700&q=80&auto=format&fit=crop",
         "available", 1, 198, 174, 12),
        ("لكزس ES 350 2025", "luxury", 28, 5, "أوتوماتيك", "بنزين", "الفروانية", 4.8, 91,
         "https://images.unsplash.com/photo-1567784431148-dbcd19d0ddce?w=700&q=80&auto=format&fit=crop",
         "available", 1, 380, 312, 18),
        ("فورد موستنج GT 2024", "sport", 45, 4, "أوتوماتيك", "بنزين", "حولي", 4.7, 53,
         "https://images.unsplash.com/photo-1694407910970-1ecd5f7e5df9?w=700&q=80&auto=format&fit=crop",
         "maintenance", 1, 570, 520, 9),
    ]
    conn.executemany(
        """INSERT INTO cars (name, category, daily_rate, seats, transmission, fuel, branch,
           rating, reviews_count, image_url, status, financing_eligible, cash_price, monthly_from, discount_percent)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        cars,
    )

    ride_classes = [
        ("اقتصادي", 6.5, 6, "https://images.unsplash.com/photo-1567784431148-dbcd19d0ddce?w=200&q=70&auto=format&fit=crop"),
        ("تنفيذي", 11.0, 4, "https://images.unsplash.com/photo-1632656269435-77b10f3fcbc6?w=200&q=70&auto=format&fit=crop"),
        ("فاخر VIP", 18.0, 8, "https://images.unsplash.com/photo-1756443773455-22e4f3d8d823?w=200&q=70&auto=format&fit=crop"),
    ]
    conn.executemany(
        "INSERT INTO ride_classes (name, base_fare, eta_minutes, image_url) VALUES (?,?,?,?)",
        ride_classes,
    )

    drivers = [
        ("محمد العنزي", "+96555511122", "لكزس ES 350", "123 ن ك", 4.9, "online", 7),
        ("طلال الحمود", "+96555533344", "لاندكروزر GXR", "445 س ب", 4.8, "online", 5),
        ("راشد الصالح", "+96555577788", "نيسان صني", "781 م ج", 4.6, "offline", 0),
    ]
    conn.executemany(
        "INSERT INTO drivers (name, phone, car_model, plate, rating, status, trips_today) VALUES (?,?,?,?,?,?,?)",
        drivers,
    )

    conn.execute(
        "INSERT INTO admin_users (username, password_hash, role) VALUES (?,?,?)",
        ("admin", generate_password_hash("IPC@2026"), "operations_manager"),
    )
    conn.execute(
        "INSERT INTO users (name, phone, loyalty_points) VALUES (?,?,?)",
        ("عبدالله الفهد", "+96555555555", 920),
    )
    conn.commit()


# ============================================================
# ======  SECTION 2: SMS / WHATSAPP OTP (Twilio Verify)  ======
# ============================================================
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_VERIFY_SERVICE_SID = os.environ.get("TWILIO_VERIFY_SERVICE_SID", "")
VERIFY_BASE = "https://verify.twilio.com/v2"

SMS_DRY_RUN = not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_VERIFY_SERVICE_SID)
SMS_DRY_RUN_CODE = "1234"


class SmsServiceError(Exception):
    pass


def _twilio_auth_header():
    token = base64.b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def sms_start_verification(phone: str, channel: str = "whatsapp") -> dict:
    if SMS_DRY_RUN:
        print(f"[DRY RUN] رمز التحقق لرقم {phone} عبر {channel}: {SMS_DRY_RUN_CODE}")
        return {"ok": True, "dry_run": True, "channel": channel, "demo_code": SMS_DRY_RUN_CODE}

    url = f"{VERIFY_BASE}/Services/{TWILIO_VERIFY_SERVICE_SID}/Verifications"
    try:
        resp = requests.post(url, headers=_twilio_auth_header(), data={"To": phone, "Channel": channel}, timeout=10)
    except requests.RequestException as e:
        raise SmsServiceError(f"تعذّر الاتصال بمزوّد الرسائل: {e}")
    if resp.status_code >= 300:
        raise SmsServiceError(f"فشل إرسال رمز التحقق ({resp.status_code}): {resp.text}")
    body = resp.json()
    return {"ok": True, "dry_run": False, "channel": channel, "status": body.get("status")}


def sms_check_verification(phone: str, code: str) -> bool:
    if SMS_DRY_RUN:
        return code.strip() == SMS_DRY_RUN_CODE

    url = f"{VERIFY_BASE}/Services/{TWILIO_VERIFY_SERVICE_SID}/VerificationCheck"
    try:
        resp = requests.post(url, headers=_twilio_auth_header(), data={"To": phone, "Code": code}, timeout=10)
    except requests.RequestException as e:
        raise SmsServiceError(f"تعذّر الاتصال بمزوّد الرسائل: {e}")
    if resp.status_code >= 300:
        raise SmsServiceError(f"فشل التحقق من الرمز ({resp.status_code}): {resp.text}")
    body = resp.json()
    return body.get("status") == "approved"


# ============================================================
# ========  SECTION 3: PAYMENT (MyFatoorah / KNET)  ==========
# ============================================================
MYFATOORAH_API_KEY = os.environ.get("MYFATOORAH_API_KEY", "")
MYFATOORAH_BASE_URL = os.environ.get("MYFATOORAH_BASE_URL", "https://apitest.myfatoorah.com")
PAYMENT_DRY_RUN = not MYFATOORAH_API_KEY
KNET_PAYMENT_METHOD_ID_TEST = 1


class PaymentServiceError(Exception):
    pass


def _myfatoorah_headers():
    return {"Accept": "application/json", "Authorization": f"Bearer {MYFATOORAH_API_KEY}", "Content-Type": "application/json"}


def payment_create(amount: float, customer_name: str, customer_mobile: str,
                    invoice_ref: str, callback_url: str, error_url: str,
                    payment_method_id: int = None) -> dict:
    if PAYMENT_DRY_RUN:
        return {"ok": True, "dry_run": True, "invoice_id": "DRYRUN-" + invoice_ref, "payment_url": None, "status": "PAID"}

    payload = {
        "PaymentMethodId": payment_method_id or KNET_PAYMENT_METHOD_ID_TEST,
        "CustomerName": customer_name,
        "DisplayCurrencyIso": "KWD",
        "MobileCountryCode": "+965",
        "CustomerMobile": customer_mobile,
        "InvoiceValue": amount,
        "CallBackUrl": callback_url,
        "ErrorUrl": error_url,
        "UserDefinedField": invoice_ref,
    }
    try:
        resp = requests.post(f"{MYFATOORAH_BASE_URL}/v2/ExecutePayment", headers=_myfatoorah_headers(), json=payload, timeout=10)
    except requests.RequestException as e:
        raise PaymentServiceError(f"تعذّر الاتصال ببوابة الدفع: {e}")
    body = resp.json()
    if not body.get("IsSuccess"):
        raise PaymentServiceError(body.get("Message", "فشل إنشاء فاتورة الدفع"))
    data = body["Data"]
    return {"ok": True, "dry_run": False, "invoice_id": data.get("InvoiceId"), "payment_url": data.get("PaymentURL"), "status": "PENDING"}


def payment_get_status(payment_id: str) -> dict:
    if PAYMENT_DRY_RUN or str(payment_id).startswith("DRYRUN-"):
        return {"status": "PAID", "invoice_id": payment_id}

    try:
        resp = requests.post(f"{MYFATOORAH_BASE_URL}/v2/getPaymentStatus", headers=_myfatoorah_headers(),
                              json={"Key": payment_id, "KeyType": "PaymentId"}, timeout=10)
    except requests.RequestException as e:
        raise PaymentServiceError(f"تعذّر الاتصال ببوابة الدفع: {e}")
    body = resp.json()
    if not body.get("IsSuccess"):
        raise PaymentServiceError(body.get("Message", "فشل التحقق من حالة الدفع"))
    invoice = body["Data"]["InvoiceTransactions"][0] if body["Data"].get("InvoiceTransactions") else {}
    return {"status": body["Data"].get("InvoiceStatus", "UNKNOWN"), "invoice_id": payment_id, "transaction": invoice}


# ============================================================
# ==================  SECTION 4: API ROUTES  ==================
# ============================================================
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return "", 204


def gen_ref(prefix):
    return f"{prefix}-KW-{''.join(random.choices(string.digits, k=5))}"


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "Inter Price Car API",
        "time": datetime.utcnow().isoformat(),
        "sms_mode": "dry_run (local testing, no real WhatsApp/SMS sent)" if SMS_DRY_RUN else "live (Twilio WhatsApp/SMS)",
        "payment_mode": "dry_run (local testing, no real charge)" if PAYMENT_DRY_RUN else "live (MyFatoorah/KNET)",
    })


# ---------------- AUTH ----------------
@app.route("/api/auth/request-otp", methods=["POST"])
def request_otp():
    data = request.get_json(force=True)
    phone = data.get("phone", "").strip()
    channel = data.get("channel", "whatsapp")
    if not phone:
        return jsonify({"error": "رقم الهاتف مطلوب"}), 400
    try:
        result = sms_start_verification(phone, channel=channel)
    except SmsServiceError as e:
        return jsonify({"error": str(e)}), 502
    response = {"ok": True, "message": "تم إرسال رمز التحقق", "channel": result["channel"]}
    if result.get("dry_run"):
        response["demo_code"] = result["demo_code"]
        response["dry_run"] = True
    return jsonify(response)


@app.route("/api/auth/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json(force=True)
    phone = data.get("phone", "").strip()
    code = data.get("code", "").strip()
    try:
        is_valid = sms_check_verification(phone, code)
    except SmsServiceError as e:
        return jsonify({"error": str(e)}), 502
    if not is_valid:
        return jsonify({"error": "رمز التحقق غير صحيح"}), 401

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    if not user:
        db.execute("INSERT INTO users (name, phone) VALUES (?,?)", ("مستخدم جديد", phone))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    db.close()
    token = f"demo-token-{user['id']}"
    return jsonify({"ok": True, "token": token, "user": row_to_dict(user)})


# ---------------- CARS / RENTAL ----------------
@app.route("/api/cars")
def list_cars():
    category = request.args.get("category")
    financing_only = request.args.get("financing_eligible")
    db = get_db()
    q = "SELECT * FROM cars WHERE 1=1"
    params = []
    if category:
        q += " AND category=?"
        params.append(category)
    if financing_only == "1":
        q += " AND financing_eligible=1"
    rows = db.execute(q, params).fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/cars/<int:car_id>")
def get_car(car_id):
    db = get_db()
    row = db.execute("SELECT * FROM cars WHERE id=?", (car_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "السيارة غير موجودة"}), 404
    return jsonify(row_to_dict(row))


RENTAL_INSURANCE_FEE = 12


@app.route("/api/rentals", methods=["POST"])
def create_rental():
    data = request.get_json(force=True)
    car_id = data["car_id"]
    user_id = data["user_id"]
    start_date = data["start_date"]
    days = int(data["days"])
    branch_pickup = data.get("branch_pickup", "السالمية")
    branch_dropoff = data.get("branch_dropoff", branch_pickup)
    insurance = 1 if data.get("insurance", True) else 0
    promo_code = data.get("promo_code")

    db = get_db()
    car = db.execute("SELECT * FROM cars WHERE id=?", (car_id,)).fetchone()
    if not car:
        db.close()
        return jsonify({"error": "السيارة غير موجودة"}), 404

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=days)

    subtotal = car["daily_rate"] * days + (RENTAL_INSURANCE_FEE if insurance else 0)
    discount = 0
    if promo_code and promo_code.upper() == "IPC10":
        discount = round(subtotal * 0.10, 3)
    total = round(subtotal - discount, 3)

    ref = gen_ref("RENT")
    try:
        payment = payment_create(
            amount=total,
            customer_name=data.get("customer_name", "عميل إنتر برايس كار"),
            customer_mobile=data.get("customer_mobile", ""),
            invoice_ref=ref,
            callback_url=data.get("callback_url", "https://example.com/payment/success"),
            error_url=data.get("error_url", "https://example.com/payment/failed"),
        )
    except PaymentServiceError as e:
        db.close()
        return jsonify({"error": "تعذّر إنشاء عملية الدفع: " + str(e)}), 502

    booking_status = "confirmed" if payment["status"] == "PAID" else "pending_payment"
    payment_status = "paid" if payment["status"] == "PAID" else "pending"

    cur = db.execute(
        """INSERT INTO rental_bookings
           (booking_ref, user_id, car_id, start_date, end_date, days, branch_pickup,
            branch_dropoff, insurance, promo_code, discount_amount, total_price, status,
            payment_id, payment_status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ref, user_id, car_id, start_date, end_dt.strftime("%Y-%m-%d"), days, branch_pickup,
         branch_dropoff, insurance, promo_code, discount, total, booking_status,
         payment["invoice_id"], payment_status),
    )
    db.execute(
        "INSERT INTO notifications (user_id, type, title, body) VALUES (?,?,?,?)",
        (user_id, "rental", "تم تأكيد حجز " + car["name"], f"يبدأ {start_date} لمدة {days} أيام"),
    )
    db.commit()
    booking = db.execute("SELECT * FROM rental_bookings WHERE id=?", (cur.lastrowid,)).fetchone()
    db.close()
    result = row_to_dict(booking)
    result["payment_url"] = payment.get("payment_url")
    return jsonify(result), 201


@app.route("/api/rentals/<int:booking_id>")
def get_rental(booking_id):
    db = get_db()
    row = db.execute("SELECT * FROM rental_bookings WHERE id=?", (booking_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "الحجز غير موجود"}), 404
    return jsonify(row_to_dict(row))


@app.route("/api/payments/confirm/<booking_ref>", methods=["POST"])
def confirm_payment(booking_ref):
    db = get_db()
    booking = db.execute("SELECT * FROM rental_bookings WHERE booking_ref=?", (booking_ref,)).fetchone()
    if not booking:
        db.close()
        return jsonify({"error": "الحجز غير موجود"}), 404
    try:
        status = payment_get_status(booking["payment_id"])
    except PaymentServiceError as e:
        db.close()
        return jsonify({"error": str(e)}), 502
    if status["status"] == "PAID":
        db.execute("UPDATE rental_bookings SET status='confirmed', payment_status='paid' WHERE booking_ref=?", (booking_ref,))
        db.commit()
        result_status = "confirmed"
    else:
        result_status = booking["status"]
    db.close()
    return jsonify({"booking_ref": booking_ref, "payment_status": status["status"], "booking_status": result_status})


# ---------------- DRIVER RIDES ----------------
@app.route("/api/ride-classes")
def ride_classes():
    db = get_db()
    rows = db.execute("SELECT * FROM ride_classes").fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


HOURLY_RATE = 6


def pick_available_driver(db):
    return db.execute("SELECT * FROM drivers WHERE status='online' ORDER BY trips_today ASC LIMIT 1").fetchone()


@app.route("/api/rides", methods=["POST"])
def create_ride():
    data = request.get_json(force=True)
    user_id = data["user_id"]
    trip_type = data.get("trip_type", "single")
    pickup = data.get("pickup", "")
    dropoff = data.get("dropoff", "")
    timing_mode = data.get("timing_mode", "asap")
    scheduled_at = data.get("scheduled_at")

    db = get_db()
    driver = pick_available_driver(db)
    if not driver:
        db.close()
        return jsonify({"error": "لا يوجد سائقين متاحين حاليًا"}), 409

    if trip_type == "hourly":
        hours = int(data.get("hours", 2))
        fare = round(hours * HOURLY_RATE, 3)
        eta = 5
        ride_class_id = None
    else:
        ride_class_id = data["ride_class_id"]
        rc = db.execute("SELECT * FROM ride_classes WHERE id=?", (ride_class_id,)).fetchone()
        if not rc:
            db.close()
            return jsonify({"error": "فئة السيارة غير موجودة"}), 404
        hours = None
        fare = rc["base_fare"]
        eta = rc["eta_minutes"]

    ref = gen_ref("RIDE")
    cur = db.execute(
        """INSERT INTO driver_rides
           (ride_ref, user_id, trip_type, pickup, dropoff, ride_class_id, hours,
            timing_mode, scheduled_at, fare, eta_minutes, driver_id, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'ongoing')""",
        (ref, user_id, trip_type, pickup, dropoff, ride_class_id, hours,
         timing_mode, scheduled_at, fare, eta, driver["id"]),
    )
    db.execute("UPDATE drivers SET trips_today = trips_today + 1 WHERE id=?", (driver["id"],))
    db.execute(
        "INSERT INTO notifications (user_id, type, title, body) VALUES (?,?,?,?)",
        (user_id, "ride", f"السائق {driver['name']} في الطريق", f"يصل خلال {eta} دقائق تقريبًا"),
    )
    db.commit()
    ride = db.execute(
        """SELECT dr.*, d.name as driver_name, d.car_model, d.plate, d.rating as driver_rating
           FROM driver_rides dr JOIN drivers d ON dr.driver_id = d.id WHERE dr.id=?""",
        (cur.lastrowid,),
    ).fetchone()
    db.close()
    return jsonify(row_to_dict(ride)), 201


@app.route("/api/rides/<int:ride_id>/complete", methods=["PATCH"])
def complete_ride(ride_id):
    db = get_db()
    db.execute("UPDATE driver_rides SET status='completed' WHERE id=?", (ride_id,))
    db.commit()
    row = db.execute("SELECT * FROM driver_rides WHERE id=?", (ride_id,)).fetchone()
    db.close()
    return jsonify(row_to_dict(row))


@app.route("/api/rides/<int:ride_id>/rating", methods=["PATCH"])
def rate_ride(ride_id):
    data = request.get_json(force=True)
    rating = int(data.get("rating", 5))
    db = get_db()
    db.execute("UPDATE driver_rides SET rating=? WHERE id=?", (rating, ride_id))
    db.commit()
    row = db.execute("SELECT * FROM driver_rides WHERE id=?", (ride_id,)).fetchone()
    db.close()
    return jsonify(row_to_dict(row))


# ---------------- FINANCING ----------------
@app.route("/api/financing/offers")
def financing_offers():
    db = get_db()
    rows = db.execute("SELECT * FROM cars WHERE financing_eligible=1").fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


ANNUAL_RATE = 0.039


@app.route("/api/financing/calculate", methods=["POST"])
def financing_calculate():
    data = request.get_json(force=True)
    car_price = float(data["car_price"])
    down_payment = float(data.get("down_payment", car_price * 0.20))
    months = int(data.get("months", 36))
    principal = car_price - down_payment
    r = ANNUAL_RATE / 12
    if r == 0:
        monthly = principal / months
    else:
        monthly = principal * (r * (1 + r) ** months) / ((1 + r) ** months - 1)
    return jsonify({
        "car_price": car_price, "down_payment": round(down_payment, 3), "months": months,
        "monthly_installment": round(monthly, 3), "total_financed": round(principal, 3),
        "annual_rate_percent": ANNUAL_RATE * 100,
    })


@app.route("/api/financing/requests", methods=["POST"])
def create_financing_request():
    data = request.get_json(force=True)
    user_id = data["user_id"]
    car_id = data["car_id"]
    car_price = float(data["car_price"])
    down_payment = float(data["down_payment"])
    months = int(data["months"])
    monthly_installment = float(data["monthly_installment"])
    documents = data.get("documents", {})

    ref = gen_ref("FIN")
    db = get_db()
    cur = db.execute(
        """INSERT INTO financing_requests
           (request_ref, user_id, car_id, car_price, down_payment, duration_months,
            monthly_installment, status, documents_json)
           VALUES (?,?,?,?,?,?,?, 'received', ?)""",
        (ref, user_id, car_id, car_price, down_payment, months, monthly_installment, str(documents)),
    )
    db.commit()
    row = db.execute("SELECT * FROM financing_requests WHERE id=?", (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(row_to_dict(row)), 201


@app.route("/api/financing/requests/<int:req_id>")
def get_financing_request(req_id):
    db = get_db()
    row = db.execute("SELECT * FROM financing_requests WHERE id=?", (req_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "الطلب غير موجود"}), 404
    return jsonify(row_to_dict(row))


# ---------------- UNIFIED BOOKINGS + NOTIFICATIONS ----------------
@app.route("/api/users/<int:user_id>/bookings")
def user_bookings(user_id):
    db = get_db()
    rentals = db.execute(
        """SELECT rb.*, c.name as car_name, c.image_url FROM rental_bookings rb
           JOIN cars c ON rb.car_id=c.id WHERE rb.user_id=?""", (user_id,)
    ).fetchall()
    rides = db.execute(
        """SELECT dr.*, d.name as driver_name FROM driver_rides dr
           LEFT JOIN drivers d ON dr.driver_id=d.id WHERE dr.user_id=?""", (user_id,)
    ).fetchall()
    financing = db.execute(
        """SELECT fr.*, c.name as car_name FROM financing_requests fr
           JOIN cars c ON fr.car_id=c.id WHERE fr.user_id=?""", (user_id,)
    ).fetchall()
    db.close()
    return jsonify({"rentals": rows_to_list(rentals), "rides": rows_to_list(rides), "financing": rows_to_list(financing)})


@app.route("/api/users/<int:user_id>/notifications")
def user_notifications(user_id):
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


# ---------------- ADMIN ----------------
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")
    db = get_db()
    row = db.execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
    db.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "بيانات الدخول غير صحيحة"}), 401
    token = f"admin-demo-token-{row['id']}"
    return jsonify({"ok": True, "token": token, "role": row["role"]})


@app.route("/api/admin/stats/overview")
def admin_stats():
    db = get_db()
    bookings_today = db.execute("SELECT COUNT(*) c FROM rental_bookings WHERE date(created_at)=date('now')").fetchone()["c"]
    revenue_today = db.execute("SELECT COALESCE(SUM(total_price),0) s FROM rental_bookings WHERE date(created_at)=date('now')").fetchone()["s"]
    available_cars = db.execute("SELECT COUNT(*) c FROM cars WHERE status='available'").fetchone()["c"]
    total_cars = db.execute("SELECT COUNT(*) c FROM cars").fetchone()["c"]
    pending_financing = db.execute("SELECT COUNT(*) c FROM financing_requests WHERE status='received' OR status='review'").fetchone()["c"]
    db.close()
    return jsonify({
        "bookings_today": bookings_today, "revenue_today": revenue_today,
        "available_cars": available_cars, "total_cars": total_cars,
        "pending_financing_requests": pending_financing,
    })


@app.route("/api/admin/bookings")
def admin_bookings():
    db = get_db()
    rows = db.execute(
        """SELECT rb.*, u.name as customer_name, c.name as car_name
           FROM rental_bookings rb JOIN users u ON rb.user_id=u.id JOIN cars c ON rb.car_id=c.id
           ORDER BY rb.created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/admin/fleet")
def admin_fleet():
    db = get_db()
    rows = db.execute("SELECT * FROM cars").fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/admin/drivers")
def admin_drivers():
    db = get_db()
    rows = db.execute("SELECT * FROM drivers").fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/admin/financing-requests")
def admin_financing_requests():
    db = get_db()
    rows = db.execute(
        """SELECT fr.*, u.name as customer_name, u.phone, c.name as car_name
           FROM financing_requests fr JOIN users u ON fr.user_id=u.id JOIN cars c ON fr.car_id=c.id
           ORDER BY fr.created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/admin/financing-requests/<int:req_id>", methods=["PATCH"])
def admin_update_financing_request(req_id):
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("received", "review", "approved", "rejected"):
        return jsonify({"error": "حالة غير صحيحة"}), 400
    db = get_db()
    db.execute("UPDATE financing_requests SET status=? WHERE id=?", (status, req_id))
    db.commit()
    row = db.execute("SELECT * FROM financing_requests WHERE id=?", (req_id,)).fetchone()
    db.close()
    return jsonify(row_to_dict(row))


if __name__ == "__main__":
    init_db()
    print("Inter Price Car API يعمل الآن على http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
