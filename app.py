import os
import sqlite3
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from functools import wraps


def login_required(f):
    """
    Decorate routes to require login.
    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect('expenses.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database."""
    conn = get_db_connection()
    with open('schema.sql', 'r') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Initialize database
if not os.path.exists('expenses.db'):
    init_db()


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show dashboard with expense summary"""
    conn = get_db_connection()
    
    # Get total expenses
    total = conn.execute(
        "SELECT SUM(amount) as total FROM expenses WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()["total"] or 0
    
    # Get expenses by category
    expenses_by_category = conn.execute("""
        SELECT c.name, c.color, SUM(e.amount) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = ?
        GROUP BY c.id, c.name, c.color
        ORDER BY total DESC
    """, (session["user_id"],)).fetchall()
    
    # Get recent expenses
    recent_expenses = conn.execute("""
        SELECT e.*, c.name as category_name, c.color
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = ?
        ORDER BY e.date DESC, e.created_at DESC
        LIMIT 10
    """, (session["user_id"],)).fetchall()
    
    # Get monthly trend (last 6 months)
    monthly_expenses = conn.execute("""
        SELECT strftime('%Y-%m', date) as month, SUM(amount) as total
        FROM expenses
        WHERE user_id = ?
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
    """, (session["user_id"],)).fetchall()
    
    conn.close()
    
    return render_template("index.html", 
                         total=total,
                         expenses_by_category=expenses_by_category,
                         recent_expenses=recent_expenses,
                         monthly_expenses=list(reversed(monthly_expenses)))


@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    """Add new expense"""
    conn = get_db_connection()
    
    if request.method == "POST":
        # Validate input
        category_id = request.form.get("category")
        amount = request.form.get("amount")
        description = request.form.get("description")
        date = request.form.get("date")
        
        if not category_id:
            flash("Must select category", "danger")
            categories = conn.execute("SELECT * FROM categories").fetchall()
            conn.close()
            return render_template("add.html", categories=categories)
        
        if not amount:
            flash("Must provide amount", "danger")
            categories = conn.execute("SELECT * FROM categories").fetchall()
            conn.close()
            return render_template("add.html", categories=categories)
        
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number", "danger")
            categories = conn.execute("SELECT * FROM categories").fetchall()
            conn.close()
            return render_template("add.html", categories=categories)
        
        if not description:
            flash("Must provide description", "danger")
            categories = conn.execute("SELECT * FROM categories").fetchall()
            conn.close()
            return render_template("add.html", categories=categories)
        
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # Insert expense
        conn.execute("""
            INSERT INTO expenses (user_id, category_id, amount, description, date)
            VALUES (?, ?, ?, ?, ?)
        """, (session["user_id"], category_id, amount, description, date))
        conn.commit()
        conn.close()
        
        flash("Expense added successfully!", "success")
        return redirect("/")
    
    else:
        categories = conn.execute("SELECT * FROM categories").fetchall()
        conn.close()
        today = datetime.now().strftime('%Y-%m-%d')
        return render_template("add.html", categories=categories, today=today)


@app.route("/history")
@login_required
def history():
    """Show expense history"""
    conn = get_db_connection()
    
    # Get all expenses
    expenses = conn.execute("""
        SELECT e.*, c.name as category_name, c.color
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.user_id = ?
        ORDER BY e.date DESC, e.created_at DESC
    """, (session["user_id"],)).fetchall()
    
    conn.close()
    
    return render_template("history.html", expenses=expenses)


@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete(expense_id):
    """Delete an expense"""
    conn = get_db_connection()
    
    # Verify ownership
    expense = conn.execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, session["user_id"])
    ).fetchone()
    
    if not expense:
        flash("Expense not found", "danger")
        conn.close()
        return redirect("/history")
    
    # Delete expense
    conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    conn.close()
    
    flash("Expense deleted successfully!", "success")
    return redirect("/history")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    # Forget any user_id
    session.clear()
    
    if request.method == "POST":
        # Validate input
        if not request.form.get("username"):
            flash("Must provide username", "danger")
            return render_template("login.html")
        
        elif not request.form.get("password"):
            flash("Must provide password", "danger")
            return render_template("login.html")
        
        # Query database for username
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (request.form.get("username"),)
        ).fetchall()
        conn.close()
        
        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            flash("Invalid username and/or password", "danger")
            return render_template("login.html")
        
        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = rows[0]["username"]
        
        flash(f"Welcome back, {rows[0]['username']}!", "success")
        return redirect("/")
    
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""
    # Forget any user_id
    session.clear()
    
    # Redirect user to login form
    flash("Logged out successfully!", "info")
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        
        # Validate input
        if not username:
            flash("Must provide username", "danger")
            return render_template("register.html")
        
        if not password:
            flash("Must provide password", "danger")
            return render_template("register.html")
        
        if not confirmation:
            flash("Must confirm password", "danger")
            return render_template("register.html")
        
        if password != confirmation:
            flash("Passwords do not match", "danger")
            return render_template("register.html")
        
        # Hash password
        hash_pw = generate_password_hash(password)
        
        # Insert user into database
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, hash) VALUES (?, ?)",
                (username, hash_pw)
            )
            conn.commit()
            
            # Get user ID
            user = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            
            # Remember which user has logged in
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            
            conn.close()
            
            flash("Registration successful!", "success")
            return redirect("/")
        
        except sqlite3.IntegrityError:
            conn.close()
            flash("Username already exists", "danger")
            return render_template("register.html")
    
    else:
        return render_template("register.html")


if __name__ == "__main__":
    app.run(debug=True)
