import os, csv, io, json, re, hashlib, secrets
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, request, redirect, url_for, session, flash, render_template, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db, db_type
from matcher import find_matches

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME-before-deployment-" + secrets.token_hex(12))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)

STATUSES = ["Received", "Under Process", "Pending", "Transferred", "Escalated", "Disposed"]
BUREAUS = ["Regulation Bureau (RB)", "Public Grievance Redressal Cell (PGRC)", "Regional Office", "Other Bureau/Cell"]
CATEGORIES = ["Faculty & Staffing", "Infrastructure", "Approval & Compliance", "Student Grievance", "Fees & Scholarship", "Other"]

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def audit(conn, case_id, action, remarks=""):
    conn.execute(
        "INSERT INTO action_history(case_id, actor, action, remarks, created_at) VALUES(?,?,?,?,?)",
        (case_id, session.get("username", "System"), action, remarks, now())
    )

@app.context_processor
def inject_globals():
    return {"current_year": datetime.now().year, "statuses": STATUSES, "bureaus": BUREAUS, "categories": CATEGORIES}

@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("Secure demo session started.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    totals = {}
    totals["all"] = conn.execute("SELECT COUNT(*) n FROM complaints").fetchone()["n"]
    for status in STATUSES:
        totals[status] = conn.execute("SELECT COUNT(*) n FROM complaints WHERE status=?", (status,)).fetchone()["n"]
    today = date.today().isoformat()
    totals["overdue"] = conn.execute(
        "SELECT COUNT(*) n FROM complaints WHERE status!='Disposed' AND expected_date IS NOT NULL AND expected_date < ?", (today,)
    ).fetchone()["n"]
    bureau_rows = conn.execute("SELECT bureau, COUNT(*) n FROM complaints WHERE status!='Disposed' GROUP BY bureau ORDER BY n DESC").fetchall()
    recent = conn.execute("SELECT * FROM complaints ORDER BY updated_at DESC LIMIT 7").fetchall()
    alerts = conn.execute("SELECT * FROM overlap_alerts WHERE review_status='Needs Review' ORDER BY created_at DESC LIMIT 6").fetchall()
    return render_template("dashboard.html", totals=totals, bureau_rows=bureau_rows, recent=recent, alerts=alerts)

@app.route("/cases")
@login_required
def cases():
    conn = get_db()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    bureau = request.args.get("bureau", "")
    sql = "SELECT * FROM complaints WHERE 1=1"
    params = []
    if q:
        sql += " AND (case_id LIKE ? OR institution_id LIKE ? OR institution_name LIKE ? OR description LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if status in STATUSES:
        sql += " AND status=?"; params.append(status)
    if bureau in BUREAUS:
        sql += " AND bureau=?"; params.append(bureau)
    sql += " ORDER BY updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return render_template("cases.html", cases=rows, q=q, selected_status=status, selected_bureau=bureau)

@app.route("/cases/new", methods=["GET", "POST"])
@login_required
def new_case():
    if request.method == "POST":
        form = request.form
        required = ["case_id", "institution_id", "institution_name", "bureau", "category", "description", "received_date"]
        if any(not form.get(k, "").strip() for k in required):
            flash("Please complete all required fields.", "danger")
            return render_template("case_form.html", item=form, mode="new")
        conn = get_db()
        try:
            conn.execute("""INSERT INTO complaints
                (case_id,institution_id,institution_name,region,bureau,officer,category,description,status,received_date,expected_date,last_action,next_action,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (form["case_id"].strip(), form["institution_id"].strip(), form["institution_name"].strip(),
                 form.get("region","").strip(), form["bureau"], form.get("officer","").strip(),
                 form["category"], form["description"].strip(), form.get("status","Received"),
                 form["received_date"], form.get("expected_date") or None, "Complaint registered",
                 form.get("next_action","Initial scrutiny").strip(), now(), now()))
            audit(conn, form["case_id"].strip(), "Complaint created", "Case registered in the dashboard.")
            conn.commit()
            flash("Complaint registered. AI overlap scan is ready.", "success")
            return redirect(url_for("case_detail", case_id=form["case_id"].strip()))
        except Exception as e:
            conn.rollback()
            flash("Could not save case. Check that the Case ID is unique. Details: " + str(e), "danger")
    return render_template("case_form.html", item={}, mode="new")

@app.route("/cases/<case_id>")
@login_required
def case_detail(case_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM complaints WHERE case_id=?", (case_id,)).fetchone()
    if not item:
        flash("Case not found.", "warning"); return redirect(url_for("cases"))
    history = conn.execute("SELECT * FROM action_history WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall()
    alerts = conn.execute("""SELECT * FROM overlap_alerts WHERE case_a=? OR case_b=? ORDER BY created_at DESC""", (case_id, case_id)).fetchall()
    return render_template("case_detail.html", item=item, history=history, alerts=alerts)

@app.route("/cases/<case_id>/update", methods=["POST"])
@login_required
def update_case(case_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM complaints WHERE case_id=?", (case_id,)).fetchone()
    if not item:
        flash("Case not found.", "warning"); return redirect(url_for("cases"))
    status = request.form.get("status", item["status"])
    bureau = request.form.get("bureau", item["bureau"])
    officer = request.form.get("officer", item["officer"])
    next_action = request.form.get("next_action", item["next_action"])
    remarks = request.form.get("remarks", "").strip()
    if status not in STATUSES or bureau not in BUREAUS:
        flash("Invalid status or Bureau/Cell.", "danger"); return redirect(url_for("case_detail", case_id=case_id))
    try:
        conn.execute("""UPDATE complaints SET status=?,bureau=?,officer=?,next_action=?,last_action=?,updated_at=? WHERE case_id=?""",
                     (status, bureau, officer, next_action, remarks or "Case details updated", now(), case_id))
        audit(conn, case_id, "Case updated", f"Status: {status}; Bureau: {bureau}; Remarks: {remarks}")
        conn.commit()
        flash("Case updated and action history recorded.", "success")
    except Exception as e:
        conn.rollback(); flash("Update failed: " + str(e), "danger")
    return redirect(url_for("case_detail", case_id=case_id))

@app.route("/cases/<case_id>/scan", methods=["POST"])
@login_required
def scan_case(case_id):
    conn = get_db()
    target = conn.execute("SELECT * FROM complaints WHERE case_id=?", (case_id,)).fetchone()
    if not target:
        return jsonify({"error": "Case not found"}), 404
    others = conn.execute("SELECT * FROM complaints WHERE case_id != ? AND status != 'Disposed'", (case_id,)).fetchall()
    matches = find_matches(dict(target), [dict(x) for x in others])
    for m in matches:
        a, b = sorted([case_id, m["case_id"]])
        existing = conn.execute("SELECT id FROM overlap_alerts WHERE case_a=? AND case_b=?", (a,b)).fetchone()
        if not existing:
            conn.execute("""INSERT INTO overlap_alerts(case_a,case_b,score,reason,review_status,created_at)
                            VALUES(?,?,?,?,?,?)""",
                         (a,b,m["score"],m["reason"],"Needs Review",now()))
    audit(conn, case_id, "AI overlap scan", f"{len(matches)} potential match(es) identified.")
    conn.commit()
    return jsonify({"case_id": case_id, "matches": matches, "message": "AI scan complete. Matches are suggestions for authorized review."})

@app.route("/alerts")
@login_required
def alerts():
    conn = get_db()
    rows = conn.execute("""SELECT a.*, c1.institution_name, c1.institution_id, c1.bureau bureau_a, c2.bureau bureau_b
                           FROM overlap_alerts a LEFT JOIN complaints c1 ON c1.case_id=a.case_a
                           LEFT JOIN complaints c2 ON c2.case_id=a.case_b
                           ORDER BY CASE a.review_status WHEN 'Needs Review' THEN 0 ELSE 1 END, a.created_at DESC""").fetchall()
    return render_template("alerts.html", alerts=rows)

@app.route("/alerts/<int:alert_id>/review", methods=["POST"])
@login_required
def review_alert(alert_id):
    decision = request.form.get("decision")
    if decision not in ["Confirmed Related", "Not Related"]:
        flash("Choose a valid review decision.", "danger"); return redirect(url_for("alerts"))
    conn = get_db()
    conn.execute("UPDATE overlap_alerts SET review_status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                 (decision, session.get("username"), now(), alert_id))
    row = conn.execute("SELECT case_a,case_b FROM overlap_alerts WHERE id=?", (alert_id,)).fetchone()
    if row:
        audit(conn, row["case_a"], "Overlap alert reviewed", f"{decision}: related case {row['case_b']}")
    conn.commit()
    flash("Review decision recorded.", "success")
    return redirect(url_for("alerts"))

@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    bureau = conn.execute("SELECT bureau, COUNT(*) total, SUM(CASE WHEN status='Disposed' THEN 1 ELSE 0 END) disposed FROM complaints GROUP BY bureau").fetchall()
    status_rows = conn.execute("SELECT status, COUNT(*) total FROM complaints GROUP BY status").fetchall()
    return render_template("reports.html", bureau=bureau, status_rows=status_rows)

@app.route("/reports/export.csv")
@login_required
def export_csv():
    conn = get_db()
    rows = conn.execute("SELECT case_id,institution_id,institution_name,region,bureau,officer,category,description,status,received_date,expected_date,last_action,next_action,created_at,updated_at FROM complaints ORDER BY created_at").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0].keys() if rows else ["case_id","institution_id","institution_name","region","bureau","officer","category","description","status","received_date","expected_date","last_action","next_action","created_at","updated_at"])
    for row in rows:
        writer.writerow([row[k] for k in row.keys()])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=aicte_cases_backup.csv"})

@app.route("/health")
def health():
    return jsonify({"status":"ok","database":db_type(),"time":now()})

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "0") == "1")
