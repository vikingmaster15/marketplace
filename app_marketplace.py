import os
import sqlite3
import secrets
import datetime
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import requests

from flask import Flask, current_app, g, redirect, render_template_string, request, session, url_for, jsonify, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


DATABASE = os.environ.get("DATABASE", os.path.join(os.path.dirname(__file__), "farm_market.db"))
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS farmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            farm_name TEXT NOT NULL,
            location TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            description TEXT,
            image_url TEXT,
            business_hours TEXT,
            is_verified INTEGER DEFAULT 0,
            verification_token TEXT,
            reset_token TEXT,
            reset_token_expiry TEXT,
            google_id TEXT,
            facebook_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity TEXT NOT NULL,
            price TEXT NOT NULL,
            unit TEXT NOT NULL,
            status TEXT NOT NULL,
            image_url TEXT,
            description TEXT,
            seasonal_start TEXT,
            seasonal_end TEXT,
            bulk_discount_threshold INTEGER,
            bulk_discount_percent REAL,
            FOREIGN KEY(farmer_id) REFERENCES farmers(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            items TEXT NOT NULL,
            total TEXT NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'pickup',
            delivery_date TEXT,
            delivery_time TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            payment_status TEXT DEFAULT 'pending',
            payment_method TEXT,
            stripe_payment_intent_id TEXT,
            paypal_order_id TEXT,
            invoice_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            farmer_id INTEGER,
            FOREIGN KEY(farmer_id) REFERENCES farmers(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            item_id INTEGER,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(farmer_id) REFERENCES farmers(id),
            FOREIGN KEY(item_id) REFERENCES inventory_items(id)
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            farmer_id INTEGER NOT NULL,
            box_type TEXT NOT NULL,
            frequency TEXT NOT NULL,
            total TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            next_delivery_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(farmer_id) REFERENCES farmers(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES farmers(id),
            FOREIGN KEY(receiver_id) REFERENCES farmers(id)
        );

        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_type TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "farmer_id" not in session:
            return redirect(url_for("farmer_login"))
        return view(*args, **kwargs)

    return wrapped


def get_cart():
    return session.get("cart", [])


def save_cart(cart):
    session["cart"] = cart


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def send_email(to_email, subject, html_content):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


def send_sms(phone_number, message):
    # Placeholder for SMS integration (would use Twilio or similar service)
    print(f"SMS to {phone_number}: {message}")
    return True


def create_notification(user_id, user_type, message):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, user_type, message) VALUES (?, ?, ?)",
        (user_id, user_type, message)
    )
    db.commit()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(SECRET_KEY="dev-secret-key", DATABASE=DATABASE)
    if test_config is not None:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    @app.route("/")
    def home():
        db = get_db()
        search = request.args.get("search", "").strip()
        category_filter = request.args.get("category", "").strip()
        
        query = "SELECT i.*, f.farm_name FROM inventory_items i JOIN farmers f ON f.id = i.farmer_id WHERE i.status != 'Out of stock'"
        params = []
        
        if search:
            query += " AND (i.name LIKE ? OR f.farm_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        
        if category_filter:
            query += " AND i.category = ?"
            params.append(category_filter)
        
        query += " ORDER BY i.id DESC"
        
        items = db.execute(query, params).fetchall()
        categories = db.execute("SELECT DISTINCT category FROM inventory_items").fetchall()
        cart_count = sum(item["quantity"] for item in get_cart())
        
        # Get ratings for each item
        item_ratings = {}
        for item in items:
            avg_rating = db.execute(
                "SELECT AVG(rating) FROM reviews WHERE item_id = ?",
                (item["id"],)
            ).fetchone()[0] or 0
            item_ratings[item["id"]] = round(avg_rating, 1) if avg_rating else 0
        return render_template_string(
            """
            <!doctype html>
            <html>
              <head><meta charset="utf-8"><title>FarmFresh Market</title>
              <style>body{font-family:Arial,sans-serif;margin:0;background:#f6fff4;color:#1f3b22}.header{background:linear-gradient(135deg,#2f7d32,#1f5a23);color:white;padding:24px}.wrap{max-width:1100px;margin:0 auto;padding:24px}.card{background:white;padding:16px;border-radius:12px;margin-bottom:16px;box-shadow:0 8px 16px rgba(0,0,0,0.08)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.btn{display:inline-block;padding:10px 14px;background:#2f7d32;color:white;text-decoration:none;border-radius:8px;margin-right:8px}input,select,textarea{padding:10px;border:1px solid #cce4ce;border-radius:8px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef7eb;color:#2f7d32;font-size:12px}</style></head>
              <body>
                <div class="header">
                  <div class="wrap">
                    <h1>FarmFresh Market</h1>
                    <p>Fresh fruits and vegetables from local farms, delivered right to your neighborhood.</p>
                    <a class="btn" href="/farmers/login">Farmer Login</a>
                    <a class="btn" href="/farmers/register">Farmer Register</a>
                    {% if google_key %}
                    <a class="btn" href="/auth/google" style="background:#4285f4;">Login with Google</a>
                    {% endif %}
                    {% if facebook_key %}
                    <a class="btn" href="/auth/facebook" style="background:#1877f2;">Login with Facebook</a>
                    {% endif %}
                    <a class="btn" href="/cart">Cart ({{ cart_count }})</a>
                    <a class="btn" href="/checkout">Checkout</a>
                    <a class="btn" href="/orders">My Orders</a>
                    <a class="btn" href="/subscribe">Subscribe</a>
                    <a class="btn" href="/admin/setup">Admin</a>
                  </div>
                </div>
                <div class="wrap">
                  <div class="card">
                    <h2>Available produce</h2>
                    <form method='get' style='margin-bottom:16px;display:flex;gap:8px;'>
                      <input name='search' placeholder='Search produce or farm...' value='{{ search }}'>
                      <select name='category'>
                        <option value=''>All Categories</option>
                        {% for cat in categories %}
                        <option value='{{ cat[0] }}' {% if category_filter == cat[0] %}selected{% endif %}>{{ cat[0] }}</option>
                        {% endfor %}
                      </select>
                      <button type='submit'>Filter</button>
                    </form>
                    <div class="grid">
                      {% for item in items %}
                      <div class="card">
                        <h3>{{ item['name'] }}</h3>
                        <p><strong>Farm:</strong> {{ item['farm_name'] }}</p>
                        <p><strong>Quantity:</strong> {{ item['quantity'] }}</p>
                        <p><strong>Price:</strong> ${{ item['price'] }} / {{ item['unit'] }}</p>
                        <p><strong>Rating:</strong> {{ item_ratings[item['id']] }}/5 ★</p>
                        <span class="pill">{{ item['status'] }}</span>
                        <form method='post' action='/cart/add'>
                          <input type='hidden' name='item_id' value='{{ item['id'] }}'>
                          <input name='quantity' type='number' min='1' value='1'>
                          <button type='submit'>Add to cart</button>
                        </form>
                        <form method='post' action='/reviews/add/{{ item['id'] }}' style='margin-top:8px;'>
                          <input name='customer_name' placeholder='Your name' required style='width:100%;padding:4px;'>
                          <input name='customer_email' type='email' placeholder='Email' required style='width:100%;padding:4px;'>
                          <select name='rating' style='padding:4px;width:100%;'>
                            <option value='5'>★★★★★</option>
                            <option value='4'>★★★★</option>
                            <option value='3'>★★★</option>
                            <option value='2'>★★</option>
                            <option value='1'>★</option>
                          </select>
                          <input name='comment' placeholder='Review (optional)' style='width:100%;padding:4px;'>
                          <button type='submit' style='padding:4px 8px;'>Review</button>
                        </form>
                      </div>
                      {% else %}
                      <p>No inventory yet. Farmers can add produce from the dashboard.</p>
                      {% endfor %}
                    </div>
                  </div>
                </div>
              </body>
            </html>
            """,
            items=items,
            cart_count=cart_count,
            search=search,
            category_filter=category_filter,
            categories=categories,
            item_ratings=item_ratings,
            google_key=GOOGLE_CLIENT_ID,
            facebook_key=FACEBOOK_APP_ID,
        )

    @app.route("/farmers/register", methods=["GET", "POST"])
    def farmer_register():
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            farm_name = request.form["farm_name"].strip()
            location = request.form["location"].strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            description = request.form.get("description", "").strip()
            
            verification_token = secrets.token_urlsafe(32)
            
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO farmers (username, password, farm_name, location, email, phone, description, verification_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (username, generate_password_hash(password), farm_name, location, email or None, phone or None, description or None, verification_token),
                )
                db.commit()
                
                # Send verification email
                if email:
                    verification_url = f"{request.host_url}verify/{verification_token}"
                    html_content = f"""
                    <h2>Verify your email</h2>
                    <p>Click the link below to verify your email address:</p>
                    <a href="{verification_url}">Verify Email</a>
                    """
                    send_email(email, "Verify your FarmFresh Market account", html_content)
                
                farmer = db.execute("SELECT id FROM farmers WHERE username = ?", (username,)).fetchone()
                session["farmer_id"] = farmer[0]
                return redirect(url_for("farmer_dashboard"))
            except sqlite3.IntegrityError:
                return render_template_string("<h2>Username or email already exists.</h2><a href='/farmers/register'>Try again</a>")

        return render_template_string(
            """
            <!doctype html><html><head><title>Farmer Register</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input,textarea{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Farmer Register</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <input name='email' type='email' placeholder='Email (optional)'>
                <input name='phone' placeholder='Phone (optional)'>
                <input name='farm_name' placeholder='Farm name' required>
                <input name='location' placeholder='Location' required>
                <textarea name='description' placeholder='Farm description' rows='3'></textarea>
                <button type='submit'>Register</button>
              </form>
              <p><a href='/farmers/login'>Already have an account? Login</a></p>
            </body></html>
            """
        )

    @app.route("/verify/<token>")
    def verify_email(token):
        db = get_db()
        farmer = db.execute("SELECT id FROM farmers WHERE verification_token = ?", (token,)).fetchone()
        if farmer:
            db.execute("UPDATE farmers SET is_verified = 1, verification_token = NULL WHERE id = ?", (farmer["id"],))
            db.commit()
            return render_template_string("<h2>Email verified successfully!</h2><a href='/farmers/login'>Login now</a>")
        return render_template_string("<h2>Invalid verification link.</h2><a href='/'>Back home</a>")

    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password_request():
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            farmer = get_db().execute("SELECT id, username FROM farmers WHERE email = ?", (email,)).fetchone()
            if farmer:
                reset_token = secrets.token_urlsafe(32)
                expiry = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
                get_db().execute(
                    "UPDATE farmers SET reset_token = ?, reset_token_expiry = ? WHERE id = ?",
                    (reset_token, expiry, farmer["id"])
                )
                get_db().commit()
                
                reset_url = f"{request.host_url}reset-password/{reset_token}"
                html_content = f"""
                <h2>Reset your password</h2>
                <p>Click the link below to reset your password:</p>
                <a href="{reset_url}">Reset Password</a>
                <p>This link expires in 1 hour.</p>
                """
                send_email(email, "Reset your FarmFresh Market password", html_content)
            
            return render_template_string("<h2>If an account with that email exists, you'll receive a reset link.</h2><a href='/'>Back home</a>")
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Reset Password</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Reset Password</h2>
              <form method='post'>
                <input name='email' type='email' placeholder='Email' required>
                <button type='submit'>Send Reset Link</button>
              </form>
              <p><a href='/farmers/login'>Back to login</a></p>
            </body></html>
            """
        )

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        db = get_db()
        farmer = db.execute("SELECT id, reset_token_expiry FROM farmers WHERE reset_token = ?", (token,)).fetchone()
        
        if not farmer:
            return render_template_string("<h2>Invalid reset link.</h2><a href='/reset-password'>Request new link</a>")
        
        expiry = datetime.datetime.fromisoformat(farmer["reset_token_expiry"])
        if datetime.datetime.now() > expiry:
            return render_template_string("<h2>Reset link expired.</h2><a href='/reset-password'>Request new link</a>")
        
        if request.method == "POST":
            new_password = request.form.get("password", "").strip()
            if new_password:
                db.execute(
                    "UPDATE farmers SET password = ?, reset_token = NULL, reset_token_expiry = NULL WHERE id = ?",
                    (generate_password_hash(new_password), farmer["id"])
                )
                db.commit()
                return render_template_string("<h2>Password reset successfully!</h2><a href='/farmers/login'>Login now</a>")
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Reset Password</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Set New Password</h2>
              <form method='post'>
                <input name='password' type='password' placeholder='New password' required>
                <button type='submit'>Reset Password</button>
              </form>
            </body></html>
            """
        )

    @app.route("/farmers/login", methods=["GET", "POST"])
    def farmer_login():
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            farmer = get_db().execute("SELECT id, username, password FROM farmers WHERE username = ?", (username,)).fetchone()
            if farmer is not None and check_password_hash(farmer["password"], password):
                session["farmer_id"] = farmer["id"]
                return redirect(url_for("farmer_dashboard"))
            return render_template_string("<h2>Invalid login.</h2><a href='/farmers/login'>Try again</a>")

        return render_template_string(
            """
            <!doctype html><html><head><title>Farmer Login</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}.oauth-btn{width:100%;padding:10px;margin:5px 0;border:none;border-radius:4px;cursor:pointer;color:white;}.google-btn{background:#4285f4;}.facebook-btn{background:#1877f2;}</style></head><body>
              <h2>Farmer Login</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <button type='submit'>Login</button>
              </form>
              {% if google_key %}
              <a href='/auth/google' class='oauth-btn google-btn' style='text-decoration:none;display:block;text-align:center;'>Login with Google</a>
              {% endif %}
              {% if facebook_key %}
              <a href='/auth/facebook' class='oauth-btn facebook-btn' style='text-decoration:none;display:block;text-align:center;'>Login with Facebook</a>
              {% endif %}
              <p><a href='/farmers/register'>Register</a></p>
              <p><a href='/reset-password'>Forgot password?</a></p>
            </body></html>
            """,
            google_key=GOOGLE_CLIENT_ID,
            facebook_key=FACEBOOK_APP_ID,
        )

    @app.route("/dashboard")
    @login_required
    def farmer_dashboard():
        farmer_id = session["farmer_id"]
        farmer = get_db().execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        items = get_db().execute("SELECT * FROM inventory_items WHERE farmer_id = ? ORDER BY id DESC", (farmer_id,)).fetchall()
        orders = get_db().execute(
            "SELECT * FROM orders WHERE farmer_id = ? ORDER BY created_at DESC",
            (farmer_id,)
        ).fetchall()
        reviews = get_db().execute("SELECT * FROM reviews WHERE farmer_id = ? ORDER BY created_at DESC", (farmer_id,)).fetchall()
        subscriptions = get_db().execute("SELECT * FROM subscriptions WHERE farmer_id = ? ORDER BY created_at DESC", (farmer_id,)).fetchall()
        messages = get_db().execute(
            "SELECT m.*, f1.farm_name as sender_name, f2.farm_name as receiver_name FROM messages m JOIN farmers f1 ON m.sender_id = f1.id JOIN farmers f2 ON m.receiver_id = f2.id WHERE m.receiver_id = ? OR m.sender_id = ? ORDER BY m.created_at DESC",
            (farmer_id, farmer_id)
        ).fetchall()
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Farmer Dashboard</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:1200px;margin:0 auto;}.section{margin:20px 0;padding:20px;background:#f9f9f9;border-radius:8px;}table{width:100%;border-collapse:collapse;}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd;}.btn{background:#2f7d32;color:white;padding:8px 16px;text-decoration:none;border-radius:4px;display:inline-block;margin:2px;}input,select,textarea{padding:8px;margin:4px 0;border:1px solid #ccc;border-radius:4px;}</style></head><body>
              <h2>Farmer Dashboard - {{ farmer['farm_name'] }}</h2>
              <p>Email: {{ farmer['email'] or 'Not set' }} | Phone: {{ farmer['phone'] or 'Not set' }} | Verified: {% if farmer['is_verified'] %}✓{% else %}✗{% endif %}</p>
              
              <div class='section'>
                <h3>Update Profile</h3>
                <form method='post' action='/profile/update'>
                  <input name='email' type='email' placeholder='Email' value='{{ farmer['email'] or "" }}'>
                  <input name='phone' placeholder='Phone' value='{{ farmer['phone'] or "" }}'>
                  <input name='business_hours' placeholder='Business Hours (e.g., Mon-Fri 9am-5pm)' value='{{ farmer['business_hours'] or "" }}'>
                  <textarea name='description' placeholder='Farm description' rows='3'>{{ farmer['description'] or "" }}</textarea>
                  <input type='file' name='image' accept='image/*'>
                  <button type='submit'>Update Profile</button>
                </form>
              </div>
              
              <div class='section'>
                <h3>Add produce</h3>
                <form method='post' action='/inventory/add' enctype='multipart/form-data'>
                  <input name='name' placeholder='Produce name' required>
                  <input name='category' placeholder='Category' required>
                  <input name='quantity' placeholder='Quantity' required>
                  <input name='price' placeholder='Price' required>
                  <input name='unit' placeholder='Unit (lb, box, bunch)' required>
                  <textarea name='description' placeholder='Description' rows='2'></textarea>
                  <input type='file' name='image' accept='image/*'>
                  <select name='status'>
                    <option>Available</option>
                    <option>Almost gone</option>
                    <option>Out of stock</option>
                  </select>
                  <label>Seasonal Availability:</label>
                  <input name='seasonal_start' type='date' placeholder='Start date'>
                  <input name='seasonal_end' type='date' placeholder='End date'>
                  <label>Bulk Discount:</label>
                  <input name='bulk_threshold' type='number' placeholder='Min quantity for discount'>
                  <input name='bulk_percent' type='number' step='0.01' placeholder='Discount percent (e.g., 10 for 10%)'>
                  <button type='submit'>Add inventory</button>
                </form>
              </div>
              
              <div class='section'>
                <h3>Your inventory</h3>
                <table>
                  <tr><th>Name</th><th>Category</th><th>Quantity</th><th>Price</th><th>Status</th><th>Actions</th></tr>
                  {% for item in items %}
                  <tr>
                    <td>{{ item['name'] }}{% if item['image_url'] %} <img src='{{ item['image_url'] }}' width='50'>{% endif %}</td>
                    <td>{{ item['category'] }}</td>
                    <td>{{ item['quantity'] }}</td>
                    <td>${{ item['price'] }}/{{ item['unit'] }}</td>
                    <td>{{ item['status'] }}</td>
                    <td>
                      <a class='btn' href='/inventory/edit/{{ item['id'] }}'>Edit</a>
                      <a class='btn' href='/inventory/delete/{{ item['id'] }}' onclick='return confirm("Delete?")'>Delete</a>
                    </td>
                  </tr>
                  {% else %}
                  <tr><td colspan='6'>No items yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              
              <div class='section'>
                <h3>Orders for your farm</h3>
                <table>
                  <tr><th>Order #</th><th>Customer</th><th>Total</th><th>Status</th><th>Payment</th><th>Actions</th></tr>
                  {% for order in orders %}
                  <tr>
                    <td>{{ order['id'] }}</td>
                    <td>{{ order['customer_name'] }}</td>
                    <td>${{ order['total'] }}</td>
                    <td>{{ order['status'] }}</td>
                    <td>{{ order['payment_status'] or 'Pending' }}</td>
                    <td>
                      <form method='post' action='/orders/update/{{ order['id'] }}' style='display:inline'>
                        <select name='status'>
                          <option value='pending' {% if order['status'] == 'pending' %}selected{% endif %}>Pending</option>
                          <option value='confirmed' {% if order['status'] == 'confirmed' %}selected{% endif %}>Confirmed</option>
                          <option value='ready' {% if order['status'] == 'ready' %}selected{% endif %}>Ready</option>
                          <option value='completed' {% if order['status'] == 'completed' %}selected{% endif %}>Completed</option>
                        </select>
                        <button type='submit'>Update</button>
                      </form>
                      {% if order['invoice_url'] %}
                      <a class='btn' href='{{ order['invoice_url'] }}' target='_blank'>Invoice</a>
                      {% endif %}
                    </td>
                  </tr>
                  {% else %}
                  <tr><td colspan='6'>No orders yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              
              <div class='section'>
                <h3>Reviews</h3>
                <table>
                  <tr><th>Customer</th><th>Rating</th><th>Comment</th><th>Date</th></tr>
                  {% for review in reviews %}
                  <tr>
                    <td>{{ review['customer_name'] }}</td>
                    <td>{{ '★' * review['rating'] }}</td>
                    <td>{{ review['comment'] or '' }}</td>
                    <td>{{ review['created_at'] }}</td>
                  </tr>
                  {% else %}
                  <tr><td colspan='4'>No reviews yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              
              <div class='section'>
                <h3>Subscriptions</h3>
                <table>
                  <tr><th>Customer</th><th>Box Type</th><th>Frequency</th><th>Total</th><th>Status</th><th>Next Delivery</th></tr>
                  {% for sub in subscriptions %}
                  <tr>
                    <td>{{ sub['customer_name'] }}</td>
                    <td>{{ sub['box_type'] }}</td>
                    <td>{{ sub['frequency'] }}</td>
                    <td>${{ sub['total'] }}</td>
                    <td>{{ sub['status'] }}</td>
                    <td>{{ sub['next_delivery_date'] or 'TBD' }}</td>
                  </tr>
                  {% else %}
                  <tr><td colspan='6'>No subscriptions yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              
              <div class='section'>
                <h3>Messages</h3>
                <form method='post' action='/messages/send'>
                  <input name='receiver_id' type='number' placeholder='Recipient Farmer ID' required>
                  <textarea name='message' placeholder='Your message' required></textarea>
                  <button type='submit'>Send Message</button>
                </form>
                <table>
                  <tr><th>From</th><th>To</th><th>Message</th><th>Date</th></tr>
                  {% for msg in messages %}
                  <tr>
                    <td>{{ msg['sender_name'] }}</td>
                    <td>{{ msg['receiver_name'] }}</td>
                    <td>{{ msg['message'] }}{% if not msg['is_read'] %} 🔔{% endif %}</td>
                    <td>{{ msg['created_at'] }}</td>
                  </tr>
                  {% else %}
                  <tr><td colspan='4'>No messages yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              
              <p><a class='btn' href='/'>Back to market</a> <a class='btn' href='/analytics'>View Analytics</a></p>
            </body></html>
            """,
            farmer=farmer,
            items=items,
            orders=orders,
            reviews=reviews,
            subscriptions=subscriptions,
            messages=messages,
        )

    @app.route("/inventory/add", methods=["POST"])
    @login_required
    def add_inventory():
        farmer_id = session["farmer_id"]
        
        # Handle image upload
        image_url = None
        if "image" in request.files:
            file = request.files["image"]
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_url = f"/uploads/{filename}"
        
        get_db().execute(
            "INSERT INTO inventory_items (farmer_id, name, category, quantity, price, unit, status, image_url, description, seasonal_start, seasonal_end, bulk_discount_threshold, bulk_discount_percent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                farmer_id,
                request.form["name"].strip(),
                request.form["category"].strip(),
                request.form["quantity"].strip(),
                request.form["price"].strip(),
                request.form["unit"].strip(),
                request.form["status"].strip(),
                image_url,
                request.form.get("description", "").strip() or None,
                request.form.get("seasonal_start", "").strip() or None,
                request.form.get("seasonal_end", "").strip() or None,
                request.form.get("bulk_threshold", "").strip() or None,
                request.form.get("bulk_percent", "").strip() or None,
            ),
        )
        get_db().commit()
        return redirect(url_for("farmer_dashboard"))

    @app.route("/profile/update", methods=["POST"])
    @login_required
    def update_profile():
        farmer_id = session["farmer_id"]
        
        # Handle image upload
        image_url = None
        if "image" in request.files:
            file = request.files["image"]
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_url = f"/uploads/{filename}"
        
        get_db().execute(
            "UPDATE farmers SET email=?, phone=?, business_hours=?, description=?, image_url=? WHERE id=?",
            (
                request.form.get("email", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("business_hours", "").strip() or None,
                request.form.get("description", "").strip() or None,
                image_url,
                farmer_id,
            ),
        )
        get_db().commit()
        return redirect(url_for("farmer_dashboard"))

    @app.route("/uploads/<filename>")
    def uploaded_file(filename):
        return send_from_directory(UPLOAD_FOLDER, filename)

    @app.route("/inventory/edit/<int:item_id>", methods=["GET", "POST"])
    @login_required
    def edit_inventory(item_id):
        farmer_id = session["farmer_id"]
        item = get_db().execute("SELECT * FROM inventory_items WHERE id = ? AND farmer_id = ?", (item_id, farmer_id)).fetchone()
        if item is None:
            return redirect(url_for("farmer_dashboard"))
        
        if request.method == "POST":
            get_db().execute(
                "UPDATE inventory_items SET name=?, category=?, quantity=?, price=?, unit=?, status=? WHERE id=?",
                (
                    request.form["name"].strip(),
                    request.form["category"].strip(),
                    request.form["quantity"].strip(),
                    request.form["price"].strip(),
                    request.form["unit"].strip(),
                    request.form["status"].strip(),
                    item_id,
                ),
            )
            get_db().commit()
            return redirect(url_for("farmer_dashboard"))
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Edit Inventory</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>Edit Inventory</h2>
              <form method='post'>
                <input name='name' placeholder='Produce name' required value='{{ item['name'] }}'>
                <input name='category' placeholder='Category' required value='{{ item['category'] }}'>
                <input name='quantity' placeholder='Quantity' required value='{{ item['quantity'] }}'>
                <input name='price' placeholder='Price' required value='{{ item['price'] }}'>
                <input name='unit' placeholder='Unit (lb, box, bunch)' required value='{{ item['unit'] }}'>
                <select name='status'>
                  <option {% if item['status'] == 'Available' %}selected{% endif %}>Available</option>
                  <option {% if item['status'] == 'Almost gone' %}selected{% endif %}>Almost gone</option>
                  <option {% if item['status'] == 'Out of stock' %}selected{% endif %}>Out of stock</option>
                </select>
                <button type='submit'>Update</button>
              </form>
              <p><a href='/dashboard'>Back to dashboard</a></p>
            </body></html>
            """,
            item=item,
        )

    @app.route("/inventory/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_inventory(item_id):
        farmer_id = session["farmer_id"]
        get_db().execute("DELETE FROM inventory_items WHERE id = ? AND farmer_id = ?", (item_id, farmer_id))
        get_db().commit()
        return redirect(url_for("farmer_dashboard"))

    @app.route("/orders/update/<int:order_id>", methods=["POST"])
    @login_required
    def update_order_status(order_id):
        farmer_id = session["farmer_id"]
        status = request.form.get("status", "pending").strip()
        get_db().execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        get_db().commit()
        return redirect(url_for("farmer_dashboard"))

    @app.route("/messages/send", methods=["POST"])
    @login_required
    def send_message():
        sender_id = session["farmer_id"]
        receiver_id = int(request.form["receiver_id"])
        message = request.form["message"].strip()
        
        get_db().execute(
            "INSERT INTO messages (sender_id, receiver_id, message) VALUES (?, ?, ?)",
            (sender_id, receiver_id, message)
        )
        get_db().commit()
        create_notification(receiver_id, "farmer", f"New message from farmer {sender_id}")
        return redirect(url_for("farmer_dashboard"))

    @app.route("/reviews/add/<int:item_id>", methods=["POST"])
    def add_review(item_id):
        item = get_db().execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return redirect(url_for("home"))
        
        rating = int(request.form["rating"])
        comment = request.form.get("comment", "").strip()
        customer_name = request.form["customer_name"].strip()
        customer_email = request.form["customer_email"].strip()
        
        get_db().execute(
            "INSERT INTO reviews (farmer_id, item_id, customer_name, customer_email, rating, comment) VALUES (?, ?, ?, ?, ?, ?)",
            (item["farmer_id"], item_id, customer_name, customer_email, rating, comment or None)
        )
        get_db().commit()
        create_notification(item["farmer_id"], "farmer", f"New review for {item['name']}")
        return redirect(url_for("home"))

    @app.route("/subscribe", methods=["GET", "POST"])
    def subscribe():
        if request.method == "POST":
            farmer_id = int(request.form["farmer_id"])
            customer_name = request.form["customer_name"].strip()
            customer_email = request.form["customer_email"].strip()
            box_type = request.form["box_type"].strip()
            frequency = request.form["frequency"].strip()
            total = request.form["total"].strip()
            
            # Calculate next delivery date based on frequency
            next_delivery = datetime.datetime.now()
            if frequency == "weekly":
                next_delivery += datetime.timedelta(days=7)
            elif frequency == "biweekly":
                next_delivery += datetime.timedelta(days=14)
            elif frequency == "monthly":
                next_delivery += datetime.timedelta(days=30)
            
            get_db().execute(
                "INSERT INTO subscriptions (customer_name, customer_email, farmer_id, box_type, frequency, total, next_delivery_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (customer_name, customer_email, farmer_id, box_type, frequency, total, next_delivery.isoformat())
            )
            get_db().commit()
            create_notification(farmer_id, "farmer", f"New subscription from {customer_name}")
            
            return render_template_string("<h2>Subscription created successfully!</h2><a href='/'>Back home</a>")
        
        farmers = get_db().execute("SELECT id, farm_name FROM farmers").fetchall()
        return render_template_string(
            """
            <!doctype html><html><head><title>Subscribe</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input,select{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Subscribe to a Farm Box</h2>
              <form method='post'>
                <select name='farmer_id' required>
                  <option value=''>Select a farm</option>
                  {% for farmer in farmers %}
                  <option value='{{ farmer['id'] }}'>{{ farmer['farm_name'] }}</option>
                  {% endfor %}
                </select>
                <input name='customer_name' placeholder='Your name' required>
                <input name='customer_email' type='email' placeholder='Your email' required>
                <select name='box_type' required>
                  <option value='small'>Small Box ($25)</option>
                  <option value='medium'>Medium Box ($40)</option>
                  <option value='large'>Large Box ($60)</option>
                </select>
                <select name='frequency' required>
                  <option value='weekly'>Weekly</option>
                  <option value='biweekly'>Bi-weekly</option>
                  <option value='monthly'>Monthly</option>
                </select>
                <input name='total' placeholder='Total amount' required>
                <button type='submit'>Subscribe</button>
              </form>
              <p><a href='/'>Back to market</a></p>
            </body></html>
            """,
            farmers=farmers,
        )

    @app.route("/analytics")
    @login_required
    def analytics():
        farmer_id = session["farmer_id"]
        
        # Sales data
        sales = get_db().execute(
            "SELECT DATE(created_at) as date, SUM(CAST(total as REAL)) as total FROM orders WHERE farmer_id = ? AND status = 'completed' GROUP BY DATE(created_at) ORDER BY date DESC LIMIT 30",
            (farmer_id,)
        ).fetchall()
        
        # Popular items
        popular_items = get_db().execute(
            "SELECT name, COUNT(*) as count FROM inventory_items i JOIN orders o ON o.items LIKE '%\"name\":\"' || i.name || '%\" WHERE i.farmer_id = ? GROUP BY i.name ORDER BY count DESC LIMIT 10",
            (farmer_id,)
        ).fetchall()
        
        # Total revenue
        total_revenue = get_db().execute(
            "SELECT SUM(CAST(total as REAL)) FROM orders WHERE farmer_id = ? AND status = 'completed'",
            (farmer_id,)
        ).fetchone()[0] or 0
        
        # Average rating
        avg_rating = get_db().execute(
            "SELECT AVG(rating) FROM reviews WHERE farmer_id = ?",
            (farmer_id,)
        ).fetchone()[0] or 0
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Analytics</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:1200px;margin:0 auto;}.section{margin:20px 0;padding:20px;background:#f9f9f9;border-radius:8px;}table{width:100%;border-collapse:collapse;}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd;}.stat{font-size:24px;font-weight:bold;color:#2f7d32;}</style></head><body>
              <h2>Sales Analytics</h2>
              <div class='section'>
                <h3>Overview</h3>
                <p>Total Revenue: <span class='stat'>${{ total_revenue }}</span></p>
                <p>Average Rating: <span class='stat'>{{ "%.1f"|format(avg_rating) }}/5</span></p>
              </div>
              <div class='section'>
                <h3>Recent Sales</h3>
                <table>
                  <tr><th>Date</th><th>Total</th></tr>
                  {% for sale in sales %}
                  <tr><td>{{ sale['date'] }}</td><td>${{ sale['total'] }}</td></tr>
                  {% else %}
                  <tr><td colspan='2'>No sales yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              <div class='section'>
                <h3>Popular Items</h3>
                <table>
                  <tr><th>Item</th><th>Orders</th></tr>
                  {% for item in popular_items %}
                  <tr><td>{{ item['name'] }}</td><td>{{ item['count'] }}</td></tr>
                  {% else %}
                  <tr><td colspan='2'>No data yet.</td></tr>
                  {% endfor %}
                </table>
              </div>
              <p><a href='/dashboard'>Back to dashboard</a></p>
            </body></html>
            """,
            sales=sales,
            popular_items=popular_items,
            total_revenue=total_revenue,
            avg_rating=avg_rating,
        )

    @app.route("/cart/add", methods=["POST"])
    def add_to_cart():
        item_id = request.form.get("item_id", "").strip()
        quantity = int(request.form.get("quantity", 1) or 1)
        item = get_db().execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            return redirect(url_for("home"))
        cart = get_cart()
        existing = next((entry for entry in cart if entry["item_id"] == item_id), None)
        if existing is None:
            cart.append({"item_id": item_id, "name": item["name"], "price": item["price"], "quantity": quantity})
        else:
            existing["quantity"] += quantity
        save_cart(cart)
        return redirect(url_for("home"))

    @app.route("/cart", methods=["GET", "POST"])
    def cart():
        if request.method == "POST":
            cart_items = get_cart()
            action = request.form.get("action", "")
            item_id = request.form.get("item_id", "")
            if action == "remove":
                cart_items = [item for item in cart_items if item["item_id"] != item_id]
            elif action == "update":
                new_quantity = int(request.form.get("quantity", 1) or 1)
                for item in cart_items:
                    if item["item_id"] == item_id:
                        item["quantity"] = new_quantity
                        break
            save_cart(cart_items)
            return redirect(url_for("cart"))

        cart_items = get_cart()
        subtotal = round(sum(float(item["price"]) * item["quantity"] for item in cart_items), 2)
        return render_template_string(
            """
            <!doctype html><html><head><title>Your Cart</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>Your cart</h2>
              {% if cart_items %}
                {% for item in cart_items %}
                <div>
                  <strong>{{ item['name'] }}</strong> - Qty {{ item['quantity'] }} - ${{ item['price'] }} each
                  <form method='post' style='display:inline'>
                    <input type='hidden' name='item_id' value='{{ item['item_id'] }}'>
                    <input type='hidden' name='action' value='update'>
                    <input name='quantity' type='number' min='1' value='{{ item['quantity'] }}'>
                    <button type='submit'>Update</button>
                  </form>
                  <form method='post' style='display:inline'>
                    <input type='hidden' name='item_id' value='{{ item['item_id'] }}'>
                    <input type='hidden' name='action' value='remove'>
                    <button type='submit'>Remove</button>
                  </form>
                </div>
                {% endfor %}
                <p><strong>Subtotal:</strong> ${{ subtotal }}</p>
                <p><a href='/checkout'>Proceed to checkout</a></p>
              {% else %}
                <p>Your cart is empty.</p>
              {% endif %}
              <p><a href='/'>Back to market</a></p>
            </body></html>
            """,
            cart_items=cart_items,
            subtotal=subtotal,
        )

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        cart_items = get_cart()
        subtotal = round(sum(float(item["price"]) * item["quantity"] for item in cart_items), 2)
        
        # Get farmer_id from cart items
        farmer_id = None
        if cart_items:
            item = get_db().execute("SELECT farmer_id FROM inventory_items WHERE id = ?", (cart_items[0]["item_id"],)).fetchone()
            if item:
                farmer_id = item["farmer_id"]
        
        if request.method == "POST":
            if not cart_items:
                return render_template_string("<h2>Your cart is empty.</h2><a href='/'>Back home</a>")
            
            payment_method = request.form.get("payment_method", "cash")
            payment_status = "pending"
            payment_intent_id = None
            paypal_order_id = None
            
            # Handle Stripe payment
            if payment_method == "stripe" and STRIPE_SECRET_KEY:
                try:
                    import stripe
                    stripe.api_key = STRIPE_SECRET_KEY
                    
                    # Create payment intent
                    payment_intent = stripe.PaymentIntent.create(
                        amount=int(subtotal * 100),  # Convert to cents
                        currency="usd",
                        metadata={"order_type": "farm_market"},
                    )
                    payment_intent_id = payment_intent.id
                    payment_status = "processing"
                    
                    # Store payment intent in session for confirmation
                    session["payment_intent_id"] = payment_intent_id
                    session["checkout_data"] = {
                        "customer_name": request.form["customer_name"].strip(),
                        "customer_email": request.form["customer_email"].strip(),
                        "phone": request.form["phone"].strip(),
                        "address": request.form["address"].strip(),
                        "order_type": request.form.get("order_type", "pickup").strip(),
                        "delivery_date": request.form.get("delivery_date", "").strip(),
                        "delivery_time": request.form.get("delivery_time", "").strip(),
                        "subtotal": subtotal,
                        "farmer_id": farmer_id,
                    }
                    
                    return render_template_string(
                        """
                        <!doctype html><html><head><title>Stripe Payment</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}</style></head><body>
                          <h2>Complete Payment</h2>
                          <p>Amount: ${{ subtotal }}</p>
                          <form id='payment-form'>
                            <div id='card-element'></div>
                            <button id='submit-button'>Pay ${{ subtotal }}</button>
                          </form>
                          <script src='https://js.stripe.com/v3/'></script>
                          <script>
                            var stripe = Stripe('{{ stripe_key }}');
                            var elements = stripe.elements();
                            var card = elements.create('card');
                            card.mount('#card-element');
                            
                            var form = document.getElementById('payment-form');
                            form.addEventListener('submit', function(event) {
                              event.preventDefault();
                              stripe.confirmCardPayment('{{ client_secret }}', {
                                payment_method: {card: card}
                              }).then(function(result) {
                                if (result.error) {
                                  alert(result.error.message);
                                } else {
                                  window.location.href = '/checkout/stripe/confirm';
                                }
                              });
                            });
                          </script>
                        </body></html>
                        """,
                        subtotal=subtotal,
                        stripe_key=STRIPE_PUBLISHABLE_KEY,
                        client_secret=payment_intent.client_secret,
                    )
                except Exception as e:
                    print(f"Stripe error: {e}")
                    return render_template_string("<h2>Payment processing error. Please try another method.</h2><a href='/checkout'>Back</a>")
            
            # Handle PayPal payment
            elif payment_method == "paypal" and PAYPAL_CLIENT_ID:
                try:
                    # Create PayPal order
                    paypal_order_url = "https://api-m.sandbox.paypal.com/v2/checkout/orders"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {PAYPAL_CLIENT_ID}:{PAYPAL_SECRET}"
                    }
                    order_data = {
                        "intent": "CAPTURE",
                        "purchase_units": [{
                            "amount": {
                                "currency_code": "USD",
                                "value": f"{subtotal:.2f}"
                            }
                        }]
                    }
                    
                    response = requests.post(paypal_order_url, json=order_data, headers=headers)
                    if response.status_code == 201:
                        paypal_order = response.json()
                        paypal_order_id = paypal_order["id"]
                        payment_status = "processing"
                        
                        # Store PayPal order ID in session
                        session["paypal_order_id"] = paypal_order_id
                        session["checkout_data"] = {
                            "customer_name": request.form["customer_name"].strip(),
                            "customer_email": request.form["customer_email"].strip(),
                            "phone": request.form["phone"].strip(),
                            "address": request.form["address"].strip(),
                            "order_type": request.form.get("order_type", "pickup").strip(),
                            "delivery_date": request.form.get("delivery_date", "").strip(),
                            "delivery_time": request.form.get("delivery_time", "").strip(),
                            "subtotal": subtotal,
                            "farmer_id": farmer_id,
                        }
                        
                        return render_template_string(
                            """
                            <!doctype html><html><head><title>PayPal Payment</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}</style></head><body>
                              <h2>Complete Payment with PayPal</h2>
                              <p>Amount: ${{ subtotal }}</p>
                              <div id='paypal-button-container'></div>
                              <script src='https://www.paypal.com/sdk/js?client-id={{ paypal_key }}&currency=USD'></script>
                              <script>
                                paypal.Buttons({
                                  createOrder: function(data, actions) {
                                    return actions.order.create({
                                      purchase_units: [{
                                        amount: {value: '{{ subtotal }}'}
                                      }]
                                    });
                                  },
                                  onApprove: function(data, actions) {
                                    return actions.order.capture().then(function(details) {
                                      window.location.href = '/checkout/paypal/confirm?orderID=' + data.orderID;
                                    });
                                  }
                                }).render('#paypal-button-container');
                              </script>
                            </body></html>
                            """,
                            subtotal=subtotal,
                            paypal_key=PAYPAL_CLIENT_ID,
                        )
                    else:
                        print(f"PayPal error: {response.text}")
                        return render_template_string("<h2>Payment processing error. Please try another method.</h2><a href='/checkout'>Back</a>")
                except Exception as e:
                    print(f"PayPal error: {e}")
                    return render_template_string("<h2>Payment processing error. Please try another method.</h2><a href='/checkout'>Back</a>")
            
            # Cash payment
            else:
                payment_status = "pending"
            
            get_db().execute(
                "INSERT INTO orders (customer_name, customer_email, phone, address, items, total, order_type, delivery_date, delivery_time, payment_method, payment_status, farmer_id, stripe_payment_intent_id, paypal_order_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.form["customer_name"].strip(),
                    request.form["customer_email"].strip(),
                    request.form["phone"].strip(),
                    request.form["address"].strip(),
                    str(cart_items),
                    f"{subtotal:.2f}",
                    request.form.get("order_type", "pickup").strip(),
                    request.form.get("delivery_date", "").strip(),
                    request.form.get("delivery_time", "").strip(),
                    payment_method,
                    payment_status,
                    farmer_id,
                    payment_intent_id,
                    paypal_order_id,
                ),
            )
            get_db().commit()
            
            # Send notifications
            if farmer_id:
                create_notification(farmer_id, "farmer", f"New order from {request.form['customer_name'].strip()}")
                farmer = get_db().execute("SELECT email, phone FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
                if farmer:
                    if farmer["email"]:
                        send_email(farmer["email"], "New Order Received", f"<h2>New Order</h2><p>You have a new order from {request.form['customer_name'].strip()} for ${subtotal}</p>")
                    if farmer["phone"]:
                        send_sms(farmer["phone"], f"New order from {request.form['customer_name'].strip()} for ${subtotal}")
            
            save_cart([])
            return render_template_string("<h2>Thanks for your order!</h2><p>Your pickup or delivery request was received.</p><a href='/orders'>View your orders</a> | <a href='/'>Back home</a>")

        return render_template_string(
            """
            <!doctype html><html><head><title>Checkout</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input,select,textarea{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Checkout</h2>
              <p><strong>Subtotal:</strong> ${{ subtotal }}</p>
              <form method='post'>
                <input name='customer_name' placeholder='Your name' required>
                <input name='customer_email' placeholder='Email' required>
                <input name='phone' placeholder='Phone' required>
                <textarea name='address' placeholder='Pickup or delivery address' required></textarea>
                <select name='order_type'>
                  <option value='pickup'>Pickup</option>
                  <option value='delivery'>Delivery</option>
                </select>
                <input name='delivery_date' type='date'>
                <input name='delivery_time' type='time'>
                <h3>Payment Method</h3>
                <select name='payment_method'>
                  <option value='cash'>Cash on Pickup/Delivery</option>
                  {% if stripe_key %}
                  <option value='stripe'>Credit Card (Stripe)</option>
                  {% endif %}
                  {% if paypal_key %}
                  <option value='paypal'>PayPal</option>
                  {% endif %}
                </select>
                <button type='submit'>Continue to Payment</button>
              </form>
              <p><a href='/cart'>Back to cart</a></p>
            </body></html>
            """,
            subtotal=subtotal,
            stripe_key=STRIPE_PUBLISHABLE_KEY,
            paypal_key=PAYPAL_CLIENT_ID,
        )

    @app.route("/checkout/stripe/confirm")
    def stripe_confirm():
        payment_intent_id = session.get("payment_intent_id")
        checkout_data = session.get("checkout_data")
        
        if not payment_intent_id or not checkout_data:
            return redirect(url_for("home"))
        
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            if payment_intent.status == "succeeded":
                # Create order
                cart_items = get_cart()
                get_db().execute(
                    "INSERT INTO orders (customer_name, customer_email, phone, address, items, total, order_type, delivery_date, delivery_time, payment_method, payment_status, farmer_id, stripe_payment_intent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        checkout_data["customer_name"],
                        checkout_data["customer_email"],
                        checkout_data["phone"],
                        checkout_data["address"],
                        str(cart_items),
                        f"{checkout_data['subtotal']:.2f}",
                        checkout_data["order_type"],
                        checkout_data["delivery_date"],
                        checkout_data["delivery_time"],
                        "stripe",
                        "paid",
                        checkout_data["farmer_id"],
                        payment_intent_id,
                    ),
                )
                get_db().commit()
                
                # Send notifications
                if checkout_data["farmer_id"]:
                    create_notification(checkout_data["farmer_id"], "farmer", f"New order from {checkout_data['customer_name']}")
                    farmer = get_db().execute("SELECT email, phone FROM farmers WHERE id = ?", (checkout_data["farmer_id"],)).fetchone()
                    if farmer:
                        if farmer["email"]:
                            send_email(farmer["email"], "New Order Received", f"<h2>New Order</h2><p>You have a new order from {checkout_data['customer_name']} for ${checkout_data['subtotal']}</p>")
                        if farmer["phone"]:
                            send_sms(farmer["phone"], f"New order from {checkout_data['customer_name']} for ${checkout_data['subtotal']}")
                
                # Clear session
                session.pop("payment_intent_id", None)
                session.pop("checkout_data", None)
                save_cart([])
                
                return render_template_string("<h2>Payment Successful!</h2><p>Your order has been placed.</p><a href='/orders'>View your orders</a> | <a href='/'>Back home</a>")
            else:
                return render_template_string("<h2>Payment not completed.</h2><a href='/checkout'>Try again</a>")
        except Exception as e:
            print(f"Stripe confirm error: {e}")
            return render_template_string("<h2>Payment confirmation error.</h2><a href='/checkout'>Try again</a>")

    @app.route("/checkout/paypal/confirm")
    def paypal_confirm():
        paypal_order_id = request.args.get("orderID")
        checkout_data = session.get("checkout_data")
        
        if not paypal_order_id or not checkout_data:
            return redirect(url_for("home"))
        
        try:
            # Verify PayPal order
            paypal_order_url = f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{paypal_order_id}"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Basic {PAYPAL_CLIENT_ID}:{PAYPAL_SECRET}"
            }
            response = requests.get(paypal_order_url, headers=headers)
            
            if response.status_code == 200:
                order_data = response.json()
                if order_data["status"] == "APPROVED" or order_data["status"] == "COMPLETED":
                    # Create order
                    cart_items = get_cart()
                    get_db().execute(
                        "INSERT INTO orders (customer_name, customer_email, phone, address, items, total, order_type, delivery_date, delivery_time, payment_method, payment_status, farmer_id, paypal_order_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            checkout_data["customer_name"],
                            checkout_data["customer_email"],
                            checkout_data["phone"],
                            checkout_data["address"],
                            str(cart_items),
                            f"{checkout_data['subtotal']:.2f}",
                            checkout_data["order_type"],
                            checkout_data["delivery_date"],
                            checkout_data["delivery_time"],
                            "paypal",
                            "paid",
                            checkout_data["farmer_id"],
                            paypal_order_id,
                        ),
                    )
                    get_db().commit()
                    
                    # Send notifications
                    if checkout_data["farmer_id"]:
                        create_notification(checkout_data["farmer_id"], "farmer", f"New order from {checkout_data['customer_name']}")
                        farmer = get_db().execute("SELECT email, phone FROM farmers WHERE id = ?", (checkout_data["farmer_id"],)).fetchone()
                        if farmer:
                            if farmer["email"]:
                                send_email(farmer["email"], "New Order Received", f"<h2>New Order</h2><p>You have a new order from {checkout_data['customer_name']} for ${checkout_data['subtotal']}</p>")
                            if farmer["phone"]:
                                send_sms(farmer["phone"], f"New order from {checkout_data['customer_name']} for ${checkout_data['subtotal']}")
                    
                    # Clear session
                    session.pop("paypal_order_id", None)
                    session.pop("checkout_data", None)
                    save_cart([])
                    
                    return render_template_string("<h2>Payment Successful!</h2><p>Your order has been placed.</p><a href='/orders'>View your orders</a> | <a href='/'>Back home</a>")
            
            return render_template_string("<h2>Payment not completed.</h2><a href='/checkout'>Try again</a>")
        except Exception as e:
            print(f"PayPal confirm error: {e}")
            return render_template_string("<h2>Payment confirmation error.</h2><a href='/checkout'>Try again</a>")

    @app.route("/orders")
    def customer_orders():
        customer_email = session.get("customer_email", "")
        if not customer_email:
            return render_template_string(
                """
                <!doctype html><html><head><title>My Orders</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
                  <h2>My Orders</h2>
                  <p>Please enter your email to view your orders:</p>
                  <form method='post'>
                    <input name='email' placeholder='Email' required>
                    <button type='submit'>View Orders</button>
                  </form>
                </body></html>
                """
            )
        
        if request.method == "POST":
            customer_email = request.form.get("email", "").strip()
            session["customer_email"] = customer_email
        
        orders = get_db().execute("SELECT * FROM orders WHERE customer_email = ? ORDER BY created_at DESC", (customer_email,)).fetchall()
        return render_template_string(
            """
            <!doctype html><html><head><title>My Orders</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>My Orders</h2>
              {% if orders %}
                {% for order in orders %}
                <div class='card' style='border:1px solid #ddd;padding:16px;margin-bottom:16px;'>
                  <h3>Order #{{ order['id'] }}</h3>
                  <p><strong>Date:</strong> {{ order['created_at'] }}</p>
                  <p><strong>Total:</strong> ${{ order['total'] }}</p>
                  <p><strong>Type:</strong> {{ order['order_type'] }}</p>
                  <p><strong>Status:</strong> {{ order['status'] }}</p>
                  {% if order['delivery_date'] %}
                  <p><strong>Delivery Date:</strong> {{ order['delivery_date'] }} at {{ order['delivery_time'] }}</p>
                  {% endif %}
                  <p><strong>Items:</strong> {{ order['items'] }}</p>
                </div>
                {% endfor %}
              {% else %}
                <p>No orders found for {{ customer_email }}.</p>
              {% endif %}
              <p><a href='/'>Back to market</a></p>
            </body></html>
            """,
            orders=orders,
            customer_email=customer_email,
        )

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            admin = get_db().execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
            if admin and check_password_hash(admin["password"], password):
                session["admin_id"] = admin["id"]
                return redirect(url_for("admin_dashboard"))
            return render_template_string("<h2>Invalid login.</h2><a href='/admin/login'>Try again</a>")
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Admin Login</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Admin Login</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <button type='submit'>Login</button>
              </form>
            </body></html>
            """
        )

    @app.route("/admin")
    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "admin_id" not in session:
                return redirect(url_for("admin_login"))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/admin/dashboard")
    @admin_required
    def admin_dashboard():
        farmers = get_db().execute("SELECT * FROM farmers ORDER BY created_at DESC").fetchall()
        orders = get_db().execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 50").fetchall()
        total_revenue = get_db().execute("SELECT SUM(CAST(total as REAL)) FROM orders WHERE payment_status = 'paid'").fetchone()[0] or 0
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Admin Dashboard</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:1400px;margin:0 auto;}.section{margin:20px 0;padding:20px;background:#f9f9f9;border-radius:8px;}table{width:100%;border-collapse:collapse;}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd;}.btn{background:#2f7d32;color:white;padding:8px 16px;text-decoration:none;border-radius:4px;display:inline-block;margin:2px;}.stat{font-size:24px;font-weight:bold;color:#2f7d32;}</style></head><body>
              <h2>Admin Dashboard</h2>
              <div class='section'>
                <h3>Overview</h3>
                <p>Total Farmers: <span class='stat'>{{ farmers|length }}</span></p>
                <p>Total Revenue: <span class='stat'>${{ total_revenue }}</span></p>
              </div>
              <div class='section'>
                <h3>Farmers</h3>
                <table>
                  <tr><th>ID</th><th>Farm Name</th><th>Email</th><th>Verified</th><th>Created</th><th>Actions</th></tr>
                  {% for farmer in farmers %}
                  <tr>
                    <td>{{ farmer['id'] }}</td>
                    <td>{{ farmer['farm_name'] }}</td>
                    <td>{{ farmer['email'] or 'N/A' }}</td>
                    <td>{% if farmer['is_verified'] %}✓{% else %}✗{% endif %}</td>
                    <td>{{ farmer['created_at'] }}</td>
                    <td>
                      <a class='btn' href='/admin/farmer/{{ farmer['id'] }}/verify'>Verify</a>
                      <a class='btn' href='/admin/farmer/{{ farmer['id'] }}/delete' onclick='return confirm("Delete?")'>Delete</a>
                    </td>
                  </tr>
                  {% endfor %}
                </table>
              </div>
              <div class='section'>
                <h3>Recent Orders</h3>
                <table>
                  <tr><th>ID</th><th>Customer</th><th>Total</th><th>Status</th><th>Payment</th><th>Date</th></tr>
                  {% for order in orders %}
                  <tr>
                    <td>{{ order['id'] }}</td>
                    <td>{{ order['customer_name'] }}</td>
                    <td>${{ order['total'] }}</td>
                    <td>{{ order['status'] }}</td>
                    <td>{{ order['payment_status'] }}</td>
                    <td>{{ order['created_at'] }}</td>
                  </tr>
                  {% endfor %}
                </table>
              </div>
              <p><a class='btn' href='/'>Back to market</a></p>
            </body></html>
            """,
            farmers=farmers,
            orders=orders,
            total_revenue=total_revenue,
        )

    @app.route("/admin/farmer/<int:farmer_id>/verify")
    @admin_required
    def verify_farmer(farmer_id):
        get_db().execute("UPDATE farmers SET is_verified = 1 WHERE id = ?", (farmer_id,))
        get_db().commit()
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/farmer/<int:farmer_id>/delete")
    @admin_required
    def delete_farmer(farmer_id):
        get_db().execute("DELETE FROM farmers WHERE id = ?", (farmer_id,))
        get_db().commit()
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/setup", methods=["GET", "POST"])
    def admin_setup():
        # Check if admin already exists
        admin = get_db().execute("SELECT * FROM admins LIMIT 1").fetchone()
        if admin:
            return render_template_string("<h2>Admin already exists. <a href='/admin/login'>Login</a></h2>")
        
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            email = request.form["email"].strip()
            
            get_db().execute(
                "INSERT INTO admins (username, password, email) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), email)
            )
            get_db().commit()
            return redirect(url_for("admin_login"))
        
        return render_template_string(
            """
            <!doctype html><html><head><title>Setup Admin</title><style>body{font-family:Arial,sans-serif;padding:24px;max-width:500px;margin:0 auto;}input{width:100%;padding:10px;margin:5px 0;border:1px solid #ccc;border-radius:4px;}button{background:#2f7d32;color:white;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;}</style></head><body>
              <h2>Setup Admin Account</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <input name='email' type='email' placeholder='Email' required>
                <button type='submit'>Create Admin</button>
              </form>
            </body></html>
            """
        )

    @app.route("/auth/google")
    def google_auth():
        # Demo mode for testing without real credentials
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            # Simulate OAuth callback for demo
            session["oauth_demo"] = "google"
            session["oauth_demo_user"] = {
                "id": "demo_google_123",
                "email": "demo@gmail.com",
                "given_name": "Demo",
                "family_name": "User",
            }
            return redirect(url_for("google_callback"))
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(16)
        session["oauth_state"] = state
        
        # Redirect to Google OAuth
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": f"{request.host_url}auth/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        return redirect(f"{auth_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}")

    @app.route("/auth/google/callback")
    def google_callback():
        # Handle demo mode
        if session.get("oauth_demo") == "google":
            user_info = session.pop("oauth_demo_user", {})
            session.pop("oauth_demo", None)
        elif not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            return redirect(url_for("home"))
        else:
            # Verify state
            state = request.args.get("state")
            if state != session.get("oauth_state"):
                return render_template_string("<h2>Invalid OAuth state.</h2><a href='/'>Back</a>")
            
            code = request.args.get("code")
            if not code:
                return render_template_string("<h2>No authorization code received.</h2><a href='/'>Back</a>")
            
            # Exchange code for tokens
            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{request.host_url}auth/google/callback",
                "grant_type": "authorization_code",
            }
            
            try:
                token_response = requests.post(token_url, data=token_data)
                token_response.raise_for_status()
                tokens = token_response.json()
                
                # Get user info
                user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                user_info = requests.get(user_info_url, headers=headers).json()
            except Exception as e:
                print(f"Google OAuth error: {e}")
                return render_template_string("<h2>OAuth authentication failed.</h2><a href='/'>Back</a>")
        
        # Check if user exists
        db = get_db()
        farmer = db.execute("SELECT * FROM farmers WHERE google_id = ?", (user_info["id"],)).fetchone()
        
        if farmer:
            session["farmer_id"] = farmer["id"]
            return redirect(url_for("farmer_dashboard"))
        else:
            # Create new farmer account
            username = user_info["email"].split("@")[0]
            farm_name = f"{user_info.get('given_name', 'Demo')}'s Farm"
            location = "Not specified"
            
            try:
                db.execute(
                    "INSERT INTO farmers (username, password, farm_name, location, email, google_id, is_verified) VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (username, generate_password_hash(secrets.token_urlsafe(32)), farm_name, location, user_info["email"], user_info["id"])
                )
                db.commit()
                farmer = db.execute("SELECT id FROM farmers WHERE google_id = ?", (user_info["id"],)).fetchone()
                session["farmer_id"] = farmer["id"]
                return redirect(url_for("farmer_dashboard"))
            except sqlite3.IntegrityError:
                return render_template_string("<h2>Email already registered with another account.</h2><a href='/farmers/login'>Login</a>")

    @app.route("/auth/facebook")
    def facebook_auth():
        # Demo mode for testing without real credentials
        if not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
            # Simulate OAuth callback for demo
            session["oauth_demo"] = "facebook"
            session["oauth_demo_user"] = {
                "id": "demo_facebook_123",
                "name": "Demo User",
                "email": "demo@facebook.com",
            }
            return redirect(url_for("facebook_callback"))
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(16)
        session["oauth_state"] = state
        
        # Redirect to Facebook OAuth
        auth_url = "https://www.facebook.com/v18.0/dialog/oauth"
        params = {
            "client_id": FACEBOOK_APP_ID,
            "redirect_uri": f"{request.host_url}auth/facebook/callback",
            "response_type": "code",
            "scope": "email public_profile",
            "state": state,
        }
        return redirect(f"{auth_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}")

    @app.route("/auth/facebook/callback")
    def facebook_callback():
        # Handle demo mode
        if session.get("oauth_demo") == "facebook":
            user_info = session.pop("oauth_demo_user", {})
            session.pop("oauth_demo", None)
        elif not FACEBOOK_APP_ID or not FACEBOOK_APP_SECRET:
            return redirect(url_for("home"))
        else:
            # Verify state
            state = request.args.get("state")
            if state != session.get("oauth_state"):
                return render_template_string("<h2>Invalid OAuth state.</h2><a href='/'>Back</a>")
            
            code = request.args.get("code")
            if not code:
                return render_template_string("<h2>No authorization code received.</h2><a href='/'>Back</a>")
            
            # Exchange code for tokens
            token_url = f"https://graph.facebook.com/v18.0/oauth/access_token"
            token_data = {
                "client_id": FACEBOOK_APP_ID,
                "client_secret": FACEBOOK_APP_SECRET,
                "redirect_uri": f"{request.host_url}auth/facebook/callback",
                "code": code,
            }
            
            try:
                token_response = requests.get(token_url, params=token_data)
                token_response.raise_for_status()
                tokens = token_response.json()
                
                # Get user info
                user_info_url = f"https://graph.facebook.com/v18.0/me"
                user_info_params = {
                    "fields": "id,name,email",
                    "access_token": tokens["access_token"],
                }
                user_info = requests.get(user_info_url, params=user_info_params).json()
            except Exception as e:
                print(f"Facebook OAuth error: {e}")
                return render_template_string("<h2>OAuth authentication failed.</h2><a href='/'>Back</a>")
        
        # Check if user exists
        db = get_db()
        farmer = db.execute("SELECT * FROM farmers WHERE facebook_id = ?", (user_info["id"],)).fetchone()
        
        if farmer:
            session["farmer_id"] = farmer["id"]
            return redirect(url_for("farmer_dashboard"))
        else:
            # Create new farmer account
            username = user_info["name"].replace(" ", "").lower()
            farm_name = f"{user_info['name']}'s Farm"
            location = "Not specified"
            email = user_info.get("email", "")
            
            try:
                db.execute(
                    "INSERT INTO farmers (username, password, farm_name, location, email, facebook_id, is_verified) VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (username, generate_password_hash(secrets.token_urlsafe(32)), farm_name, location, email or None, user_info["id"])
                )
                db.commit()
                farmer = db.execute("SELECT id FROM farmers WHERE facebook_id = ?", (user_info["id"],)).fetchone()
                session["farmer_id"] = farmer["id"]
                return redirect(url_for("farmer_dashboard"))
            except sqlite3.IntegrityError:
                return render_template_string("<h2>Email already registered with another account.</h2><a href='/farmers/login'>Login</a>")

    @app.route("/manifest.json")
    def manifest():
        return jsonify({
            "name": "FarmFresh Market",
            "short_name": "FarmFresh",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f6fff4",
            "theme_color": "#2f7d32",
            "icons": [
                {
                    "src": "/static/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png"
                },
                {
                    "src": "/static/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png"
                }
            ]
        })

    with app.app_context():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
