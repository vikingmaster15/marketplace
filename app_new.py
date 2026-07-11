import os
import sqlite3
from functools import wraps

from flask import Flask, current_app, g, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE = os.environ.get("DATABASE", os.path.join(os.path.dirname(__file__), "farm_market.db"))


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
            location TEXT NOT NULL
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
            delivery_time TEXT
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


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(SECRET_KEY="dev-secret-key", DATABASE=DATABASE)
    if test_config is not None:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    @app.route("/")
    def home():
        db = get_db()
        items = db.execute(
            "SELECT i.*, f.farm_name FROM inventory_items i JOIN farmers f ON f.id = i.farmer_id ORDER BY i.id DESC"
        ).fetchall()
        cart_count = sum(item["quantity"] for item in get_cart())
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
                    <a class="btn" href="/cart">Cart ({{ cart_count }})</a>
                    <a class="btn" href="/checkout">Checkout</a>
                  </div>
                </div>
                <div class="wrap">
                  <div class="card">
                    <h2>Available produce</h2>
                    <div class="grid">
                      {% for item in items %}
                      <div class="card">
                        <h3>{{ item['name'] }}</h3>
                        <p><strong>Farm:</strong> {{ item['farm_name'] }}</p>
                        <p><strong>Quantity:</strong> {{ item['quantity'] }}</p>
                        <p><strong>Price:</strong> ${{ item['price'] }} / {{ item['unit'] }}</p>
                        <span class="pill">{{ item['status'] }}</span>
                        <form method='post' action='/cart/add'>
                          <input type='hidden' name='item_id' value='{{ item['id'] }}'>
                          <input name='quantity' type='number' min='1' value='1'>
                          <button type='submit'>Add to cart</button>
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
        )

    @app.route("/farmers/register", methods=["GET", "POST"])
    def farmer_register():
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            farm_name = request.form["farm_name"].strip()
            location = request.form["location"].strip()
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO farmers (username, password, farm_name, location) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(password), farm_name, location),
                )
                db.commit()
                farmer = db.execute("SELECT id FROM farmers WHERE username = ?", (username,)).fetchone()
                session["farmer_id"] = farmer[0]
                return redirect(url_for("farmer_dashboard"))
            except sqlite3.IntegrityError:
                return render_template_string("<h2>Username already exists.</h2><a href='/farmers/register'>Try again</a>")

        return render_template_string(
            """
            <!doctype html><html><head><title>Farmer Register</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>Farmer Register</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <input name='farm_name' placeholder='Farm name' required>
                <input name='location' placeholder='Location' required>
                <button type='submit'>Register</button>
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
            <!doctype html><html><head><title>Farmer Login</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>Farmer Login</h2>
              <form method='post'>
                <input name='username' placeholder='Username' required>
                <input name='password' type='password' placeholder='Password' required>
                <button type='submit'>Login</button>
              </form>
            </body></html>
            """
        )

    @app.route("/dashboard")
    @login_required
    def farmer_dashboard():
        farmer_id = session["farmer_id"]
        farmer = get_db().execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        items = get_db().execute("SELECT * FROM inventory_items WHERE farmer_id = ? ORDER BY id DESC", (farmer_id,)).fetchall()
        return render_template_string(
            """
            <!doctype html><html><head><title>Farmer Dashboard</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
              <h2>Farmer Dashboard</h2>
              <p>Welcome, {{ farmer['farm_name'] }}!</p>
              <h3>Add produce</h3>
              <form method='post' action='/inventory/add'>
                <input name='name' placeholder='Produce name' required>
                <input name='category' placeholder='Category' required>
                <input name='quantity' placeholder='Quantity' required>
                <input name='price' placeholder='Price' required>
                <input name='unit' placeholder='Unit (lb, box, bunch)' required>
                <select name='status'>
                  <option>Available</option>
                  <option>Almost gone</option>
                  <option>Out of stock</option>
                </select>
                <button type='submit'>Add inventory</button>
              </form>
              <h3>Your inventory</h3>
              {% for item in items %}
                <div><strong>{{ item['name'] }}</strong> - {{ item['quantity'] }} - ${{ item['price'] }} / {{ item['unit'] }} - {{ item['status'] }}</div>
              {% else %}
                <p>No items yet.</p>
              {% endfor %}
              <p><a href='/'>Back to market</a></p>
            </body></html>
            """,
            farmer=farmer,
            items=items,
        )

    @app.route("/inventory/add", methods=["POST"])
    @login_required
    def add_inventory():
        farmer_id = session["farmer_id"]
        get_db().execute(
            "INSERT INTO inventory_items (farmer_id, name, category, quantity, price, unit, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                farmer_id,
                request.form["name"].strip(),
                request.form["category"].strip(),
                request.form["quantity"].strip(),
                request.form["price"].strip(),
                request.form["unit"].strip(),
                request.form["status"].strip(),
            ),
        )
        get_db().commit()
        return redirect(url_for("farmer_dashboard"))

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
        if request.method == "POST":
            if not cart_items:
                return render_template_string("<h2>Your cart is empty.</h2><a href='/'>Back home</a>")
            get_db().execute(
                "INSERT INTO orders (customer_name, customer_email, phone, address, items, total, order_type, delivery_date, delivery_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
            get_db().commit()
            save_cart([])
            return render_template_string("<h2>Thanks for your order!</h2><p>Your pickup or delivery request was received.</p><a href='/'>Back home</a>")

        return render_template_string(
            """
            <!doctype html><html><head><title>Checkout</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head><body>
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
                <button type='submit'>Place order</button>
              </form>
              <p><a href='/cart'>Back to cart</a></p>
            </body></html>
            """,
            subtotal=subtotal,
        )

    with app.app_context():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
