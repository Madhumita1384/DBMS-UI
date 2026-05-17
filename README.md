# FreshMart Grocery Store — Project Setup Guide

## Files in this folder
```
index.html           ← The UI (open in browser)
app.py               ← Python Flask backend (connects UI to MySQL)
sample_inventory.csv ← Sample CSV for import testing
README.md            ← This file
```

---

## How the Architecture Works

```
Browser (index.html)
    ↕  HTTP requests (fetch / AJAX)
Flask Backend (app.py) — runs on localhost:5000
    ↕  SQL queries
MySQL Database (freshmart_db)
```

**The key insight:** The HTML file doesn't talk to MySQL directly.
Flask is the middleman. When you click "Buy" in the UI:
1. Browser sends `POST /api/purchase` to Flask
2. Flask runs the SQL INSERT into Transactions
3. The MySQL TRIGGER fires and decrements Inventory
4. Flask returns a JSON result
5. The browser updates the display

---

## Step 1 — Install Python dependencies

```bash
pip install flask flask-cors mysql-connector-python
```

---

## Step 2 — Set up MySQL

Run your DDL file to create all tables, then update `app.py`:

```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "YOUR_PASSWORD",   ← change this
    "database": "freshmart_db"
}
```

---

## Step 3 — Run the Flask server

```bash
python app.py
```

You should see:
```
FreshMart Flask Backend
http://localhost:5000
```

---

## Step 4 — Open the UI

Open `index.html` in your browser. The demo data is built-in so you
can explore the UI without a database connected.

When you're ready to connect to your real DB:
- Replace the `fetch()` calls in index.html from mock data to real API calls
- Example: change `renderProducts()` to fetch from `http://localhost:5000/api/products`

---

## API Endpoints Summary

| Method | URL | What it does |
|--------|-----|--------------|
| GET | /api/products | All products + stock (INNER JOIN) |
| POST | /api/products | Add product (calls stored procedure) |
| DELETE | /api/products/<id> | Remove product |
| GET | /api/inventory | Full inventory (uses VIEW) |
| PUT | /api/inventory/<id> | Update stock/threshold |
| GET | /api/low-stock | Products below threshold |
| POST | /api/purchase | Record purchase (TRIGGER fires) |
| GET | /api/transactions | Recent transactions |
| GET | /api/reports/top-products | Top 5 by quantity sold |
| GET | /api/reports/revenue-by-category | Revenue (GROUP BY + HAVING) |
| GET | /api/reports/never-sold | Products not sold in 30 days |
| GET | /api/reports/most-expensive-per-category | Subquery example |
| POST | /api/import-csv | Import CSV file |
| GET | /api/export-csv | Download inventory CSV |
| GET | /api/export-transactions-csv | Download transactions CSV |
| GET | /api/customers | All customers |
| POST | /api/customers | Add customer |

---

## Which UI page uses which SQL concept

| UI Page | SQL Concepts Demonstrated |
|---------|--------------------------|
| Product List | LEFT JOIN Products ⟕ Inventory |
| Purchase | INSERT → TRIGGER → Inventory update |
| Low Stock Alerts | WHERE Quantity < Threshold |
| Inventory | Full JOIN, UPDATE |
| Sales Report | GROUP BY, HAVING, Subquery, SUM |
| CSV Import | LOAD DATA equivalent via Python |
| CSV Export | SELECT → CSV download |

---

## For the Presentation

Each team member should be able to explain:
1. Why Flask sits between UI and MySQL (security, abstraction)
2. How the purchase TRIGGER works (trace through the flow)
3. What the ProductStockView VIEW contains and why VIEWs are useful
4. How GROUP BY + HAVING filters categories with avg price > ₹100
5. How the subquery finds the most expensive product per category
