import os
import csv
import io
import urllib.request
import urllib.parse
import json
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import database as db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


@app.context_processor
def inject_unread_support():
    if not session.get("logged_in"):
        return {}
    try:
        total_unread = sum(t.get("unread") or 0 for t in db.get_support_threads())
    except Exception:
        total_unread = 0
    return {"unread_support": total_unread}


def send_telegram_message(chat_id, text):
    if not BOT_TOKEN:
        return False, "BOT_TOKEN орнатылмаған"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return body.get("ok", False), body.get("description", "")
    except Exception as e:
        return False, str(e)


def send_telegram_photo(chat_id, file_id, caption=""):
    if not BOT_TOKEN:
        return False, "BOT_TOKEN орнатылмаған"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = urllib.parse.urlencode({"chat_id": chat_id, "photo": file_id, "caption": caption}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return body.get("ok", False), body.get("description", "")
    except Exception as e:
        return False, str(e)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Қате құпия сөз")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    stats = db.get_stats()
    stats["commission_percent"] = db.get_commission_percent()
    stats["total_commission"] = db.get_total_commission()
    daily = db.get_daily_revenue()
    monthly = db.get_monthly_revenue()
    rides = db.get_all_rides(limit=20)
    revenue_by_day = db.get_revenue_by_day(7)
    return render_template("dashboard.html", stats=stats, rides=rides, daily=daily, monthly=monthly,
                            revenue_by_day=revenue_by_day)


@app.route("/rides")
@login_required
def rides():
    status_filter = request.args.get("status", "")
    all_rides = db.get_all_rides()
    if status_filter:
        all_rides = [r for r in all_rides if r["status"] == status_filter]
    return render_template("rides.html", rides=all_rides, status_filter=status_filter)


@app.route("/rides/<int:ride_id>/complete", methods=["POST"])
@login_required
def complete_ride(ride_id):
    db.complete_ride(ride_id)
    return redirect(url_for("rides"))


@app.route("/rides/<int:ride_id>/cancel", methods=["POST"])
@login_required
def cancel_ride(ride_id):
    db.cancel_ride(ride_id)
    return redirect(url_for("rides"))


@app.route("/users")
@login_required
def users():
    q = (request.args.get("q") or "").strip().lower()
    all_users = db.get_all_users()
    if q:
        all_users = [
            u for u in all_users
            if q in (u.get("full_name") or "").lower()
            or q in (u.get("username") or "").lower()
            or q in (u.get("phone") or "").lower()
        ]
    for u in all_users:
        if u["role"] == "driver":
            r = db.get_driver_rating(u["id"])
            u["rating_display"] = f"⭐{r['avg']} ({r['count']})" if r["count"] else "—"
    return render_template("users.html", users=all_users, q=q)


@app.route("/users/export.csv")
@login_required
def export_users():
    q = (request.args.get("q") or "").strip().lower()
    all_users = db.get_all_users()
    if q:
        all_users = [
            u for u in all_users
            if q in (u.get("full_name") or "").lower()
            or q in (u.get("username") or "").lower()
            or q in (u.get("phone") or "").lower()
        ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "full_name", "username", "phone", "role", "is_online", "is_blocked",
                      "intercity_access", "verification_status", "created_at"])
    for u in all_users:
        writer.writerow([u.get(k) for k in
                          ["id", "full_name", "username", "phone", "role", "is_online", "is_blocked",
                           "intercity_access", "verification_status", "created_at"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=users.csv"})


@app.route("/users/<int:user_id>/block", methods=["POST"])
@login_required
def block_user(user_id):
    db.set_blocked(user_id, True)
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/unblock", methods=["POST"])
@login_required
def unblock_user(user_id):
    db.set_blocked(user_id, False)
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/grant_intercity", methods=["POST"])
@login_required
def grant_intercity(user_id):
    db.set_intercity_access(user_id, True)
    user = db.get_user_by_id(user_id)
    if user:
        send_telegram_message(
            user["telegram_id"],
            "✅ Сізге 'Жанақала — Орал' бағыты бойынша тапсырыс беруге рұқсат берілді! Тапсырысты қайта бастап көріңіз.",
        )
    return redirect(url_for("users"))


@app.route("/users/<int:user_id>/revoke_intercity", methods=["POST"])
@login_required
def revoke_intercity(user_id):
    db.set_intercity_access(user_id, False)
    return redirect(url_for("users"))


@app.route("/drivers")
@login_required
def drivers():
    status_filter = request.args.get("status", "")
    all_drivers = db.get_all_drivers()
    for d in all_drivers:
        r = db.get_driver_rating(d["id"])
        d["rating_display"] = f"⭐{r['avg']} ({r['count']})" if r["count"] else "—"
        earn = db.get_driver_earnings(d["id"])
        d["earnings_display"] = f"{earn['total']} тг ({earn['count']} сапар)"
    if status_filter:
        all_drivers = [d for d in all_drivers if (d.get("verification_status") or "none") == status_filter]
    return render_template("drivers.html", drivers=all_drivers, status_filter=status_filter)


@app.route("/drivers/<int:user_id>/approve", methods=["POST"])
@login_required
def approve_driver(user_id):
    db.set_verification_status(user_id, "approved")
    user = db.get_user_by_id(user_id)
    if user:
        send_telegram_message(user["telegram_id"], "✅ Құжаттарың расталды! Енді 🟢 Online режиміне кіре аласың.")
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:user_id>/reject", methods=["POST"])
@login_required
def reject_driver(user_id):
    reason = request.form.get("reason", "").strip() or "Талапқа сай емес"
    db.set_verification_status(user_id, "rejected", reason)
    user = db.get_user_by_id(user_id)
    if user:
        send_telegram_message(
            user["telegram_id"],
            f"❌ Құжаттарың қабылданбады. Себебі: {reason}\n🔄 Деректерді түзетіп қайта тіркеле аласың.",
        )
    return redirect(url_for("drivers"))


@app.route("/drivers/<int:user_id>/toggle_online", methods=["POST"])
@login_required
def toggle_driver_online(user_id):
    user = db.get_user_by_id(user_id)
    if user:
        db.set_online(user["telegram_id"], not bool(user["is_online"]))
    return redirect(url_for("drivers"))


@app.route("/cities", methods=["GET", "POST"])
@login_required
def cities():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            if db.add_city(name):
                flash(f"'{name}' қосылды")
            else:
                flash("Бұл қала/аудан бұрын қосылған")
        else:
            flash("Атауын жаз")
    all_cities = db.get_cities()
    tariffs = db.get_all_tariffs()
    return render_template("cities.html", cities=all_cities, tariffs=tariffs)


@app.route("/cities/<int:city_id>/toggle", methods=["POST"])
@login_required
def toggle_city(city_id):
    all_cities = {c["id"]: c for c in db.get_cities()}
    c = all_cities.get(city_id)
    if c:
        db.set_city_active(city_id, not bool(c["is_active"]))
    return redirect(url_for("cities"))


@app.route("/cities/<int:city_id>/delete", methods=["POST"])
@login_required
def delete_city(city_id):
    db.delete_city(city_id)
    return redirect(url_for("cities"))


@app.route("/tariffs", methods=["POST"])
@login_required
def update_tariffs():
    for route in ("local", "intercity"):
        base = request.form.get(f"{route}_base", "").strip()
        per_km = request.form.get(f"{route}_per_km", "").strip()
        if base or per_km:
            db.set_tariff(route, base, per_km)
    flash("Тарифтер сақталды")
    return redirect(url_for("cities"))


@app.route("/broadcast", methods=["GET", "POST"])
@login_required
def broadcast():
    result = None
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        role_filter = request.form.get("role") or None
        if not text:
            flash("Хабарлама мәтінін жаз")
        else:
            recipients = db.get_broadcast_recipients(role_filter)
            sent, failed = 0, 0
            for tg_id in recipients:
                ok, _ = send_telegram_message(tg_id, text)
                if ok:
                    sent += 1
                else:
                    failed += 1
            result = {"sent": sent, "failed": failed, "total": len(recipients)}
    return render_template("broadcast.html", result=result, bot_token_set=bool(BOT_TOKEN))


@app.route("/rides/export.csv")
@login_required
def export_rides():
    status_filter = request.args.get("status", "")
    all_rides = db.get_all_rides()
    if status_filter:
        all_rides = [r for r in all_rides if r["status"] == status_filter]
    buf = io.StringIO()
    writer = csv.writer(buf)
    cols = ["id", "client_name", "driver_name", "service_type", "route", "from_location",
            "to_location", "ride_time", "price", "status", "rating", "client_rating", "created_at"]
    writer.writerow(cols)
    for r in all_rides:
        writer.writerow([r.get(c) for c in cols])
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=rides.csv"})


@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    user_id = request.args.get("user_id", type=int)

    if request.method == "POST" and user_id:
        text = request.form.get("text", "").strip()
        user = db.get_user_by_id(user_id)
        if text and user:
            db.add_support_message(user_id, "out", text)
            ok, err = send_telegram_message(user["telegram_id"], f"💬 Әкімші: {text}")
            if not ok:
                flash(f"Хабарлама Telegram-ға жіберілмеді: {err}")
        return redirect(url_for("support", user_id=user_id))

    if user_id:
        selected = db.get_user_by_id(user_id)
        if not selected:
            return redirect(url_for("support"))
        db.mark_support_read(user_id)
        messages = db.get_support_messages(user_id)
        return render_template("support.html", selected=selected, messages=messages, threads=None)

    threads = db.get_support_threads()
    return render_template("support.html", threads=threads, selected=None)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        percent = request.form.get("commission_percent", "10")
        try:
            float(percent)
            db.set_setting("commission_percent", percent)
            flash("Комиссия сақталды")
        except ValueError:
            flash("Дұрыс сан жаз")
    current = db.get_commission_percent()
    total = db.get_total_commission()
    return render_template("settings.html", commission_percent=current, total_commission=total)


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", "5000"))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
