import app_marketplace

create_app = app_marketplace.create_app
get_db = app_marketplace.get_db
close_db = app_marketplace.close_db
init_db = app_marketplace.init_db
login_required = app_marketplace.login_required
get_cart = app_marketplace.get_cart
save_cart = app_marketplace.save_cart

app = app_marketplace.create_app()

if __name__ == "__main__":
    app.run(debug=True)

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
            total TEXT NOT NULL
        );
        """
    )
    db.commit()

    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="dev-secret-key",
        DATABASE=DATABASE,
    )
    if test_config is not None:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    @app.before_request
    def before_request():
        if test_config and test_config.get("TESTING"):
            pass

    @app.route("/")
    def home():
        db = get_db()
        items = db.execute(
            "SELECT i.*, f.farm_name FROM inventory_items i JOIN farmers f ON f.id = i.farmer_id ORDER BY i.id DESC"
        ).fetchall()
        return render_template_string(
            """
            <!doctype html>
            <html>
              <head>
                <meta charset="utf-8">
                <title>FarmFresh Market</title>
                <style>
                  body { font-family: Arial, sans-serif; margin: 0; background: #f6fff4; color: #1f3b22; }
                  .header { background: linear-gradient(135deg, #2f7d32, #1f5a23); color: white; padding: 24px; }
                  .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
                  .card { background: white; padding: 16px; border-radius: 12px; margin-bottom: 16px; box-shadow: 0 8px 16px rgba(0,0,0,0.08); }
                  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
                  .btn { display: inline-block; padding: 10px 14px; background: #2f7d32; color: white; text-decoration: none; border-radius: 8px; margin-right: 8px; }
                  form { display: grid; gap: 10px; }
                  input, select, textarea { padding: 10px; border: 1px solid #cce4ce; border-radius: 8px; }
                  .pill { display: inline-block; padding: 4px 8px; border-radius: 999px; background: #eef7eb; color: #2f7d32; font-size: 12px; }
                </style>
              </head>
              <body>
                <div class="header">
                  <div class="wrap">
                    <h1>FarmFresh Market</h1>
                    <p>Fresh fruits and vegetables from local farms, delivered right to your neighborhood.</p>
                    <a class="btn" href="/farmers/login">Farmer Login</a>
                    <a class="btn" href="/farmers/register">Farmer Register</a>
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
                    (username, password, farm_name, location),
                )
                db.commit()
                session["farmer_id"] = db.execute("SELECT id FROM farmers WHERE username = ?", (username,)).fetchone()[0]
                return redirect(url_for("farmer_dashboard"))
            except sqlite3.IntegrityError:
                return render_template_string("<h2>Username already exists.</h2><a href='/farmers/register'>Try again</a>")

        return render_template_string(
            """
            <!doctype html>
            <html><head><title>Farmer Register</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head>
            <body>
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
            farmer = get_db().execute(
                "SELECT id, username, password FROM farmers WHERE username = ? AND password = ?",
                (username, password),
            ).fetchone()
            if farmer is not None:
                session["farmer_id"] = farmer["id"]
                return redirect(url_for("farmer_dashboard"))
            return render_template_string("<h2>Invalid login.</h2><a href='/farmers/login'>Try again</a>")

        return render_template_string(
            """
            <!doctype html>
            <html><head><title>Farmer Login</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head>
            <body>
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
        items = get_db().execute(
            "SELECT * FROM inventory_items WHERE farmer_id = ? ORDER BY id DESC",
            (farmer_id,),
        ).fetchall()
        return render_template_string(
            """
            <!doctype html>
            <html><head><title>Farmer Dashboard</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head>
            <body>
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

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        if request.method == "POST":
            get_db().execute(
                "INSERT INTO orders (customer_name, customer_email, phone, address, items, total) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request.form["customer_name"].strip(),
                    request.form["customer_email"].strip(),
                    request.form["phone"].strip(),
                    request.form["address"].strip(),
                    request.form["items"].strip(),
                    request.form["total"].strip(),
                ),
            )
            get_db().commit()
            return render_template_string("<h2>Thanks for your order!</h2><p>Your pickup or delivery request was received.</p><a href='/'>Back home</a>")

        return render_template_string(
            """
            <!doctype html>
            <html><head><title>Checkout</title><style>body{font-family:Arial,sans-serif;padding:24px;}</style></head>
            <body>
              <h2>Checkout</h2>
              <form method='post'>
                <input name='customer_name' placeholder='Your name' required>
                <input name='customer_email' placeholder='Email' required>
                <input name='phone' placeholder='Phone' required>
                <textarea name='address' placeholder='Pickup or delivery address' required></textarea>
                <textarea name='items' placeholder='[{\"name\":\"Carrots\",\"price\":2.5,\"quantity\":2}]' required></textarea>
                <input name='total' placeholder='Total' required>
                <button type='submit'>Place order</button>
              </form>
            </body></html>
            """
        )

    with app.app_context():
        init_db()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
