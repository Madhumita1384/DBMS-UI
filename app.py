"""
FreshMart Grocery Store — Flask Backend
Connects the HTML UI to your MySQL database.

Setup:
    pip install flask flask-cors mysql-connector-python

Run:
    python app.py

The UI (index.html) fetches data from these API endpoints.
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import mysql.connector
import csv
import io
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)  # Allow the HTML file to call these endpoints

# ─────────────────────────────────────────────
# DATABASE CONNECTION
# Change these to match your MySQL setup
# ─────────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password_here",   # ← change this
    "database": "freshmart_db"
}

def get_db():
    """Return a fresh DB connection."""
    return mysql.connector.connect(**DB_CONFIG)


# ─────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────

@app.route("/api/products", methods=["GET"])
def get_products():
    """
    GET /api/products
    Returns all products with their current inventory.
    SQL: INNER JOIN Products ⟕ Inventory
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.ProductID, p.Name, p.Price, p.CategoryID,
            c.CategoryName,
            COALESCE(i.Quantity, 0)  AS stock,
            COALESCE(i.Threshold, 10) AS threshold
        FROM Products p
        LEFT JOIN Categories c ON p.CategoryID = c.CategoryID
        LEFT JOIN Inventory i  ON p.ProductID  = i.ProductID
        ORDER BY p.Name
    """)
    products = cur.fetchall()
    cur.close(); db.close()
    return jsonify(products)


@app.route("/api/products", methods=["POST"])
def add_product():
    """
    POST /api/products
    Body: { name, price, category_id, initial_stock, threshold }
    Inserts into Products; the stored procedure auto-creates Inventory record.
    """
    data = request.json
    db = get_db()
    cur = db.cursor()
    # Insert product
    cur.execute("""
        INSERT INTO Products (Name, Price, CategoryID, SupplierID)
        VALUES (%s, %s, %s, %s)
    """, (data["name"], data["price"], data["category_id"], data.get("supplier_id", 1)))
    product_id = cur.lastrowid

    # Call stored procedure to auto-create inventory with zero stock
    cur.callproc("CreateInventoryOnNewProduct", [product_id, data.get("threshold", 10)])

    db.commit()
    cur.close(); db.close()
    return jsonify({"success": True, "product_id": product_id}), 201


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM Inventory WHERE ProductID = %s", (pid,))
    cur.execute("DELETE FROM Products WHERE ProductID = %s", (pid,))
    db.commit()
    cur.close(); db.close()
    return jsonify({"success": True})


# ─────────────────────────────────────────────
# INVENTORY
# ─────────────────────────────────────────────

@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    """
    GET /api/inventory
    Full inventory view (ProductStockView in your DB).
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM ProductStockView ORDER BY ProductName")
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


@app.route("/api/inventory/<int:pid>", methods=["PUT"])
def update_inventory(pid):
    """
    PUT /api/inventory/<pid>
    Body: { quantity, threshold }
    """
    data = request.json
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE Inventory SET Quantity = %s, Threshold = %s
        WHERE ProductID = %s
    """, (data["quantity"], data["threshold"], pid))
    db.commit()
    cur.close(); db.close()
    return jsonify({"success": True})


@app.route("/api/low-stock", methods=["GET"])
def get_low_stock():
    """
    GET /api/low-stock
    Products below reorder threshold.
    SQL: WHERE i.Quantity < i.Threshold
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.ProductID, p.Name, c.CategoryName,
            i.Quantity, i.Threshold,
            ROUND((i.Quantity / i.Threshold) * 100, 1) AS stock_pct
        FROM Inventory i
        JOIN Products   p ON i.ProductID  = p.ProductID
        LEFT JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE i.Quantity < i.Threshold
        ORDER BY stock_pct ASC
    """)
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


# ─────────────────────────────────────────────
# PURCHASES / TRANSACTIONS
# ─────────────────────────────────────────────

@app.route("/api/purchase", methods=["POST"])
def make_purchase():
    """
    POST /api/purchase
    Body: { product_id, quantity, customer_id (optional) }

    - Inserts into Transactions
    - The AFTER INSERT TRIGGER on Transactions auto-decrements Inventory
    - Another TRIGGER raises error if stock goes below threshold
    - Loyalty points updated via UPDATE on Customers
    """
    data = request.json
    pid = data["product_id"]
    qty = data["quantity"]
    customer_id = data.get("customer_id")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Check stock
    cur.execute("SELECT Quantity FROM Inventory WHERE ProductID = %s", (pid,))
    inv = cur.fetchone()
    if not inv or inv["Quantity"] < qty:
        cur.close(); db.close()
        return jsonify({"error": "Insufficient stock"}), 400

    try:
        # Insert transaction — TRIGGER auto-updates inventory
        cur.execute("""
            INSERT INTO Transactions (ProductID, Quantity, TransactionDate, CustomerID)
            VALUES (%s, %s, NOW(), %s)
        """, (pid, qty, customer_id))

        tx_id = cur.lastrowid

        # Update loyalty points (10% of transaction value)
        if customer_id:
            cur.execute("SELECT Price FROM Products WHERE ProductID = %s", (pid,))
            price = cur.fetchone()["Price"]
            lp_earned = int(price * qty / 10)
            cur.execute("""
                UPDATE Customers
                SET LoyaltyPoints = LoyaltyPoints + %s
                WHERE CustomerID = %s
            """, (lp_earned, customer_id))

        db.commit()
        cur.close(); db.close()
        return jsonify({"success": True, "transaction_id": tx_id}), 201

    except mysql.connector.Error as e:
        db.rollback()
        cur.close(); db.close()
        # This catches the TRIGGER error for below-threshold stock
        return jsonify({"error": str(e)}), 400


@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    """GET /api/transactions — recent transactions."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            t.TransactionID, t.TransactionDate,
            p.Name AS ProductName, p.Price,
            t.Quantity, (p.Price * t.Quantity) AS Total,
            c.Name AS CustomerName
        FROM Transactions t
        JOIN Products  p ON t.ProductID  = p.ProductID
        LEFT JOIN Customers c ON t.CustomerID = c.CustomerID
        ORDER BY t.TransactionDate DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────

@app.route("/api/reports/top-products", methods=["GET"])
def top_products():
    """
    Top 5 best-selling products by quantity.
    SQL: GROUP BY + ORDER BY SUM(Quantity) DESC LIMIT 5
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.Name, SUM(t.Quantity) AS total_sold,
            SUM(p.Price * t.Quantity) AS revenue
        FROM Transactions t
        JOIN Products p ON t.ProductID = p.ProductID
        GROUP BY p.ProductID, p.Name
        ORDER BY total_sold DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


@app.route("/api/reports/revenue-by-category", methods=["GET"])
def revenue_by_category():
    """
    Revenue per category.
    SQL: GROUP BY + HAVING avg price > threshold
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            c.CategoryName,
            SUM(p.Price * t.Quantity) AS revenue,
            AVG(p.Price) AS avg_price
        FROM Transactions t
        JOIN Products    p ON t.ProductID  = p.ProductID
        JOIN Categories  c ON p.CategoryID = c.CategoryID
        GROUP BY c.CategoryID, c.CategoryName
        HAVING AVG(p.Price) > 100
        ORDER BY revenue DESC
    """)
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


@app.route("/api/reports/never-sold", methods=["GET"])
def never_sold():
    """
    Products never sold in last 30 days.
    SQL: LEFT JOIN + WHERE t.ProductID IS NULL
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    since = datetime.now() - timedelta(days=30)
    cur.execute("""
        SELECT p.ProductID, p.Name, c.CategoryName, p.Price, i.Quantity
        FROM Products p
        LEFT JOIN Categories c ON p.CategoryID = c.CategoryID
        LEFT JOIN Inventory  i ON p.ProductID  = i.ProductID
        WHERE p.ProductID NOT IN (
            SELECT DISTINCT ProductID FROM Transactions
            WHERE TransactionDate >= %s
        )
        ORDER BY p.Name
    """, (since,))
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


@app.route("/api/reports/most-expensive-per-category", methods=["GET"])
def most_expensive_per_category():
    """
    Subquery: most expensive product in each category.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT p.Name, c.CategoryName, p.Price
        FROM Products p
        JOIN Categories c ON p.CategoryID = c.CategoryID
        WHERE p.Price = (
            SELECT MAX(p2.Price)
            FROM Products p2
            WHERE p2.CategoryID = p.CategoryID
        )
        ORDER BY p.Price DESC
    """)
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


# ─────────────────────────────────────────────
# CSV IMPORT / EXPORT
# ─────────────────────────────────────────────

@app.route("/api/import-csv", methods=["POST"])
def import_csv():
    """
    POST /api/import-csv  (multipart form with file)
    Reads uploaded CSV and bulk-inserts into Products + Inventory.
    Equivalent to MySQL LOAD DATA INFILE.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    content = file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    db = get_db()
    cur = db.cursor()
    count = 0

    for row in reader:
        # Insert product
        cur.execute("""
            INSERT IGNORE INTO Products (Name, Price, CategoryID)
            VALUES (%s, %s, (SELECT CategoryID FROM Categories WHERE CategoryName = %s LIMIT 1))
        """, (row.get("ProductName", row.get("Name")),
              float(row.get("Price", 0)),
              row.get("Category", "Grains")))

        pid = cur.lastrowid
        if pid:
            cur.execute("""
                INSERT INTO Inventory (ProductID, Quantity, Threshold)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE Quantity = VALUES(Quantity), Threshold = VALUES(Threshold)
            """, (pid, int(row.get("Quantity", 0)), int(row.get("Threshold", 10))))
            count += 1

    db.commit()
    cur.close(); db.close()
    return jsonify({"success": True, "imported": count})


@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    """
    GET /api/export-csv
    Exports full inventory as downloadable CSV.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT
            p.ProductID, p.Name AS ProductName,
            c.CategoryName AS Category, p.Price,
            i.Quantity, i.Threshold
        FROM Products p
        LEFT JOIN Categories c ON p.CategoryID = c.CategoryID
        LEFT JOIN Inventory  i ON p.ProductID  = i.ProductID
        ORDER BY p.Name
    """)
    rows = cur.fetchall()
    cur.close(); db.close()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["ProductID","ProductName","Category","Price","Quantity","Threshold"])
    writer.writeheader()
    writer.writerows(rows)

    return app.response_class(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=freshmart_inventory.csv"}
    )


@app.route("/api/export-transactions-csv", methods=["GET"])
def export_transactions_csv():
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT t.TransactionID, t.ProductID, p.Name AS ProductName,
               t.Quantity, p.Price, (t.Quantity * p.Price) AS Total,
               t.TransactionDate
        FROM Transactions t JOIN Products p ON t.ProductID = p.ProductID
        ORDER BY t.TransactionDate DESC
    """)
    rows = cur.fetchall()
    cur.close(); db.close()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["TransactionID","ProductID","ProductName","Quantity","Price","Total","TransactionDate"])
    writer.writeheader()
    writer.writerows(rows)

    return app.response_class(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=freshmart_transactions.csv"}
    )


# ─────────────────────────────────────────────
# CUSTOMERS
# ─────────────────────────────────────────────

@app.route("/api/customers", methods=["GET"])
def get_customers():
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM Customers ORDER BY Name")
    rows = cur.fetchall()
    cur.close(); db.close()
    return jsonify(rows)


@app.route("/api/customers", methods=["POST"])
def add_customer():
    data = request.json
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO Customers (Name, Phone, LoyaltyPoints)
        VALUES (%s, %s, 0)
    """, (data["name"], data["phone"]))
    cid = cur.lastrowid
    db.commit()
    cur.close(); db.close()
    return jsonify({"success": True, "customer_id": cid}), 201


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  FreshMart Flask Backend")
    print("  http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
