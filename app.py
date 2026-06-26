from flask import Flask, render_template, request, redirect, url_for, session, flash
from sqlalchemy.orm import joinedload
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps
import os
from dotenv import load_dotenv
load_dotenv()
import cloudinary
import cloudinary.uploader
import cloudinary.api
 
app = Flask(__name__)
 
# ==========================================
# CONFIGURATION
# ==========================================
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
 
app.config.update(
    SESSION_PERMANENT=False,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=60),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_REFRESH_EACH_REQUEST=True
)
 
# ==========================================
# CLOUDINARY CONFIGURATION
# ==========================================
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True
)
 
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', '')
 
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)
 
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 10,
    'pool_size': 5,
    'max_overflow': 10
}
 
db = SQLAlchemy(app)
 
# ==========================================
# DATABASE MODELS
# ==========================================
class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(50), nullable=False, default=lambda: datetime.today().strftime('%Y-%m-%d'))
    source = db.Column(db.String(100), default='-')
    customer = db.Column(db.String(100), nullable=False)
    total_price = db.Column(db.Integer, nullable=False, default=0)
    time = db.Column(db.String(50), default='-')
    address = db.Column(db.Text, default='-')
 
    items = db.relationship(
        'OrderItem',
        backref='order',
        cascade="all, delete-orphan",
        lazy='selectin'
    )
 
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    item_name = db.Column(db.String(200), default='Cake')
    size = db.Column(db.String(50), default='-')
    price = db.Column(db.Integer, default=0)
    remarks = db.Column(db.Text, default='-')
    image_url = db.Column(db.Text, default='')
    flower_image_url = db.Column(db.Text, default='')
 
# ==========================================
# AUTHENTICATION DECORATORS
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
 
def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') != 'manager':
            return redirect(url_for('staff_view'))
        return f(*args, **kwargs)
    return decorated_function
 
# ==========================================
# AUTHENTICATION ROUTES
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    portal = request.form.get('portal', 'manager') if request.method == 'POST' else request.args.get('portal', 'manager')
 
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        portal = request.form.get('portal', 'manager')
 
        if portal == 'staff':
            if username == "Staff" and password == os.environ.get("STAFF_PASSWORD", ""):
                session.clear()
                session['logged_in'] = True
                session['role'] = 'staff'
                session.permanent = False
                return redirect(url_for('staff_view'))
            error = "员工凭证错误，请重新输入 (Invalid staff credentials)"
            portal = 'staff'
        elif username == "Memory Cake" and password == os.environ.get("MANAGER_PASSWORD", ""):
            session.clear()
            session['logged_in'] = True
            session['role'] = 'manager'
            session.permanent = False
            return redirect(url_for('index'))
        else:
            error = "管理员凭证错误，请重新输入 (Invalid manager credentials)"
 
    return render_template('login.html', error=error, portal=portal)
 
@app.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('login'))
    response.delete_cookie('session')
    return response
 
# ==========================================
# HELPERS
# ==========================================
@app.before_request
def refresh_session():
    if session.get('logged_in'):
        session.modified = True
 
def _parse_daily_filters():
    filter_mode = request.args.get('filter', 'all')
    if filter_mode not in ('all', 'month', 'day'):
        filter_mode = 'all'
    filter_month = request.args.get('month', datetime.today().strftime('%Y-%m'))
    filter_day = request.args.get('day', datetime.today().strftime('%Y-%m-%d'))
    return filter_mode, filter_month, filter_day
 
def _format_date_display(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        return f"{d.strftime('%B %d, %Y')} ({weekdays[d.weekday()]})"
    except ValueError:
        return date_str
 
def _fetch_orders_grouped_by_day(filter_mode='all', filter_month=None, filter_day=None):
    query = Order.query.options(joinedload(Order.items))
 
    if filter_mode == 'month' and filter_month:
        query = query.filter(Order.date.like(f"{filter_month}%"))
    elif filter_mode == 'day' and filter_day:
        query = query.filter(Order.date == filter_day)
 
    orders = query.order_by(Order.date.desc(), Order.id.desc()).all()
 
    groups = {}
    for order in orders:
        groups.setdefault(order.date, []).append(order)
 
    orders_by_day = []
    for date in sorted(groups.keys(), reverse=True):
        day_orders = groups[date]
        orders_by_day.append({
            'date': date,
            'date_display': _format_date_display(date),
            'orders': day_orders,
            'order_count': len(day_orders),
            'day_total': sum(o.total_price for o in day_orders),
        })
 
    return orders_by_day
 
def _daily_view_context(filter_action):
    filter_mode, filter_month, filter_day = _parse_daily_filters()
    orders_by_day = _fetch_orders_grouped_by_day(filter_mode, filter_month, filter_day)
    total_orders = sum(d['order_count'] for d in orders_by_day)
    total_revenue = sum(d['day_total'] for d in orders_by_day)
 
    available_months = sorted({
        r[0][:7]
        for r in Order.query.with_entities(Order.date).distinct().all()
        if r[0] and len(r[0]) >= 7
    }, reverse=True)
    if not available_months:
        available_months = [datetime.today().strftime('%Y-%m')]
 
    return {
        'orders_by_day': orders_by_day,
        'filter_mode': filter_mode,
        'filter_month': filter_month,
        'filter_day': filter_day,
        'filter_action': filter_action,
        'available_months': available_months,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
    }
 
# ==========================================
# MAIN ROUTES
# ==========================================
@app.route('/')
@manager_required
def index():
    db.session.remove()
    ctx = _daily_view_context(url_for('index'))
    return render_template('daily.html', active_page='daily', readonly=False, **ctx)
 
@app.route('/staff')
@login_required
def staff_view():
    if session.get('role') == 'manager':
        return redirect(url_for('index'))
    db.session.remove()
    ctx = _daily_view_context(url_for('staff_view'))
    return render_template('staff_daily.html', active_page='staff', readonly=True, **ctx)
 
@app.route('/add_order', methods=['POST'])
@manager_required
def add_order():
    order_date = request.form.get('date')
    source = request.form.get('source') or '-'
    customer = request.form.get('customer')
    time = request.form.get('time') or '-'
    address = request.form.get('address') or '-'
 
    item_names = request.form.getlist('item_name[]')
    sizes = request.form.getlist('size[]')
    prices = request.form.getlist('item_price[]')
    remarks_list = request.form.getlist('remarks[]')
 
    uploaded_flowers = request.files.getlist('flowerImage[]')
    uploaded_cakes = request.files.getlist('cakeImage[]')
 
    new_order = Order(
        date=order_date, source=source, customer=customer, total_price=0, time=time, address=address
    )
    db.session.add(new_order)
    db.session.flush()
 
    calculated_total = 0
    timestamp_prefix = int(datetime.now().timestamp())
 
    for i in range(len(item_names)):
        item_price = int(prices[i] if prices[i] else 0)
        calculated_total += item_price
 
        flower_url = ""
        if i < len(uploaded_flowers):
            f_file = uploaded_flowers[i]
            if f_file and f_file.filename != '':
                try:
                    file_bytes = f_file.read()
                    if len(file_bytes) > 0:
                        result = cloudinary.uploader.upload(
                            file_bytes,
                            folder="memory_cake/flowers",
                            public_id=f"{timestamp_prefix}_flr_{i}",
                            overwrite=True,
                            resource_type="image"
                        )
                        flower_url = result['secure_url']
                        print(f"[Cloudinary] flower uploaded OK: {flower_url}")
                except Exception as e:
                    err = f"图片上传失败 flower item {i+1}: {e}"
                    print(f"[Cloudinary ERROR] {err}")
                    flash(err, 'error')
 
        cake_url = ""
        if i < len(uploaded_cakes):
            c_file = uploaded_cakes[i]
            if c_file and c_file.filename != '':
                try:
                    file_bytes = c_file.read()
                    if len(file_bytes) > 0:
                        result = cloudinary.uploader.upload(
                            file_bytes,
                            folder="memory_cake/cakes",
                            public_id=f"{timestamp_prefix}_cke_{i}",
                            overwrite=True,
                            resource_type="image"
                        )
                        cake_url = result['secure_url']
                        print(f"[Cloudinary] cake uploaded OK: {cake_url}")
                except Exception as e:
                    err = f"图片上传失败 cake item {i+1}: {e}"
                    print(f"[Cloudinary ERROR] {err}")
                    flash(err, 'error')
 
        sub_item = OrderItem(
            order_id=new_order.id,
            item_name=item_names[i] or 'Cake',
            size=sizes[i] or '-',
            price=item_price,
            remarks=remarks_list[i] or '-',
            image_url=cake_url,
            flower_image_url=flower_url
        )
        db.session.add(sub_item)
 
    new_order.total_price = calculated_total
    db.session.commit()
    db.session.remove()
    return redirect(url_for('index'))
 
@app.route('/delete_order/<int:id>', methods=['GET', 'POST'])
@manager_required
def delete_order(id):
    order = Order.query.get_or_404(id)
    try:
        db.session.delete(order)
        db.session.commit()
        flash("Order deleted successfully.")
    except Exception as e:
        db.session.rollback()
        print("DELETE ERROR:", e)
        flash("Failed to delete order. Please try again.")
    finally:
        db.session.remove()
    return redirect(url_for('index'))
 
@app.route('/edit_order/<int:order_id>', methods=['POST'])
@manager_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.date = request.form.get('date')
    order.source = request.form.get('source') or '-'
    order.customer = request.form.get('customer')
    order.time = request.form.get('time') or '-'
    order.address = request.form.get('address') or '-'
 
    names = request.form.getlist('edit_item_name[]')
    sizes = request.form.getlist('edit_size[]')
    prices = request.form.getlist('edit_price[]')
    remarks = request.form.getlist('edit_remarks[]')
 
    old_cake_images = request.form.getlist('old_cake_image[]')
    old_flower_images = request.form.getlist('old_flower_image[]')
    new_cake_files = request.files.getlist('editCakeImage[]')
    new_flower_files = request.files.getlist('editFlowerImage[]')
    timestamp_prefix = int(datetime.now().timestamp())
 
    try:
        OrderItem.query.filter_by(order_id=order.id).delete()
        total_price = 0
 
        for i in range(len(names)):
            if not names[i].strip():
                continue
            try:
                price = int(prices[i]) if prices[i] else 0
            except:
                price = 0
            total_price += price
 
            cake_url = old_cake_images[i] if i < len(old_cake_images) else ''
            if i < len(new_cake_files):
                c_file = new_cake_files[i]
                if c_file and c_file.filename != '':
                    try:
                        file_bytes = c_file.read()
                        if len(file_bytes) > 0:
                            result = cloudinary.uploader.upload(
                                file_bytes,
                                folder="memory_cake/cakes",
                                public_id=f"{timestamp_prefix}_editcke_{i}",
                                overwrite=True,
                                resource_type="image"
                            )
                            cake_url = result['secure_url']
                            print(f"[Cloudinary] edit cake uploaded OK: {cake_url}")
                    except Exception as e:
                        err = f"图片上传失败 edit cake item {i+1}: {e}"
                        print(f"[Cloudinary ERROR] {err}")
                        flash(err, 'error')
 
            flower_url = old_flower_images[i] if i < len(old_flower_images) else ''
            if i < len(new_flower_files):
                f_file = new_flower_files[i]
                if f_file and f_file.filename != '':
                    try:
                        file_bytes = f_file.read()
                        if len(file_bytes) > 0:
                            result = cloudinary.uploader.upload(
                                file_bytes,
                                folder="memory_cake/flowers",
                                public_id=f"{timestamp_prefix}_editflr_{i}",
                                overwrite=True,
                                resource_type="image"
                            )
                            flower_url = result['secure_url']
                            print(f"[Cloudinary] edit flower uploaded OK: {flower_url}")
                    except Exception as e:
                        err = f"图片上传失败 edit flower item {i+1}: {e}"
                        print(f"[Cloudinary ERROR] {err}")
                        flash(err, 'error')
 
            new_item = OrderItem(
                order_id=order.id,
                item_name=names[i],
                size=sizes[i] if i < len(sizes) else '-',
                price=price,
                remarks=remarks[i] if i < len(remarks) else '-',
                image_url=cake_url,
                flower_image_url=flower_url
            )
            db.session.add(new_item)
 
        order.total_price = total_price
        db.session.commit()
        flash('Order updated successfully.')
    except Exception as e:
        db.session.rollback()
        print("EDIT ERROR:", e)
        flash("Failed to update order. Please try again.")
    finally:
        db.session.remove()
 
    return redirect(url_for('index'))
 
# ==========================================
# REPORTING
# ==========================================
def _normalize_source(source):
    source = (source or '').strip()
    if source in ['', '-']:
        return 'Other'
    return source
 
@app.route('/monthly')
@manager_required
def monthly():
    db.session.remove()
    db.session.expire_all()
 
    view_mode = request.args.get('view', 'month')
    selected_month = request.args.get('month', datetime.today().strftime('%Y-%m'))
    selected_year = request.args.get('year', datetime.today().strftime('%Y'))
 
    if view_mode == 'year':
        date_filter = f"{selected_year}%"
        period_label = selected_year
    else:
        date_filter = f"{selected_month}%"
        period_label = selected_month
 
    monthly_orders = (
        Order.query
        .options(joinedload(Order.items))
        .filter(Order.date.like(date_filter))
        .all()
    )
 
    total_revenue = sum(order.total_price for order in monthly_orders)
    total_orders = len(monthly_orders)
    avg_ticket = total_revenue / total_orders if total_orders else 0
    unique_customers = len(set(o.customer for o in monthly_orders if o.customer))
 
    source_revenue = {}
    for order in monthly_orders:
        source = _normalize_source(order.source)
        source_revenue[source] = source_revenue.get(source, 0) + order.total_price
 
    channels = []
    for source, revenue in source_revenue.items():
        percentage = round((revenue / total_revenue) * 100) if total_revenue else 0
        channels.append({'name': source, 'revenue': revenue, 'percentage': percentage})
    channels.sort(key=lambda x: x['revenue'], reverse=True)
 
    item_stats = {}
    total_items_count = 0
    for order in monthly_orders:
        for item in order.items:
            total_items_count += 1
            item_name = item.item_name or 'Unknown'
            size = item.size or '-'
            price = item.price or 0
            if item_name not in item_stats:
                item_stats[item_name] = {'count': 0, 'revenue': 0, 'sizes': set()}
            item_stats[item_name]['count'] += 1
            item_stats[item_name]['revenue'] += price
            if size != '-':
                item_stats[item_name]['sizes'].add(size)
 
    top_items = []
    for name, stats in item_stats.items():
        top_items.append({
            'name': name,
            'sizes': ' / '.join(stats['sizes']) if stats['sizes'] else 'Standard',
            'count': stats['count'],
            'revenue': stats['revenue']
        })
    top_items.sort(key=lambda x: x['count'], reverse=True)
    top_items = top_items[:10]
 
    profit_margin = 58
    estimated_profit = int(total_revenue * profit_margin / 100)
    items_per_order = round(total_items_count / total_orders, 1) if total_orders else 0
    canceled_orders = sum(1 for o in monthly_orders if o.total_price == 0)
    refund_rate = round(canceled_orders / total_orders * 100, 1) if total_orders else 0
 
    if view_mode == 'year':
        trend_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        trend_data = [0] * 12
        for order in monthly_orders:
            try:
                m = int(order.date.split('-')[1]) - 1
                if 0 <= m < 12:
                    trend_data[m] += order.total_price
            except (ValueError, IndexError):
                pass
        num_periods = 12
    else:
        year, month = map(int, selected_month.split('-'))
        if month == 12:
            num_days = (datetime(year + 1, 1, 1) - datetime(year, month, 1)).days
        else:
            num_days = (datetime(year, month + 1, 1) - datetime(year, month, 1)).days
 
        daily_map = {f"{selected_month}-{str(day).zfill(2)}": 0 for day in range(1, num_days + 1)}
        for order in monthly_orders:
            if order.date in daily_map:
                daily_map[order.date] += order.total_price
 
        trend_labels = [f"{i}" for i in range(1, num_days + 1)]
        trend_data = [daily_map[f"{selected_month}-{str(i).zfill(2)}"] for i in range(1, num_days + 1)]
        num_periods = num_days
 
    if view_mode == 'year':
        past_filter = Order.date < f"{selected_year}-01-01"
    else:
        past_filter = Order.date < f"{selected_month}-01"
 
    past_customers = set(
        r[0].strip()
        for r in Order.query.filter(past_filter).with_entities(Order.customer).all()
        if r[0]
    )
    current_customers = set(o.customer.strip() for o in monthly_orders if o.customer)
    returning_count = sum(1 for c in current_customers if c in past_customers)
    new_count = len(current_customers) - returning_count
    customer_split_data = [new_count, returning_count]
 
    weekday_sales = {'Mon': 0, 'Tue': 0, 'Wed': 0, 'Thu': 0, 'Fri': 0, 'Sat': 0, 'Sun': 0}
    weekday_names = list(weekday_sales.keys())
    for order in monthly_orders:
        try:
            d = datetime.strptime(order.date, "%Y-%m-%d")
            weekday_sales[weekday_names[d.weekday()]] += order.total_price
        except ValueError:
            pass
 
    weekday_labels = list(weekday_sales.keys())
    weekday_data = list(weekday_sales.values())
 
    customer_stats = {}
    for order in monthly_orders:
        name = order.customer.strip()
        source = _normalize_source(order.source)
        if name not in customer_stats:
            customer_stats[name] = {'orders': 0, 'revenue': 0, 'sources': {}}
        customer_stats[name]['orders'] += 1
        customer_stats[name]['revenue'] += order.total_price
        customer_stats[name]['sources'][source] = customer_stats[name]['sources'].get(source, 0) + 1
 
    top_customers = []
    for name, stats in customer_stats.items():
        primary_source = max(stats['sources'], key=stats['sources'].get) if stats['sources'] else 'Other'
        top_customers.append({'name': name, 'orders': stats['orders'], 'revenue': stats['revenue'], 'source': primary_source})
    top_customers.sort(key=lambda x: x['revenue'], reverse=True)
    top_customers = top_customers[:10]
 
    forecast_revenue = 0
    if trend_data and view_mode == 'month':
        avg_recent = sum(trend_data[-7:]) / min(7, len(trend_data))
        forecast_revenue = int(avg_recent * num_periods)
 
    available_years = sorted({
        r[0][:4]
        for r in Order.query.with_entities(Order.date).distinct().all()
        if r[0] and len(r[0]) >= 4
    }, reverse=True)
    if not available_years:
        available_years = [datetime.today().strftime('%Y')]
 
    return render_template(
        'monthly.html',
        active_page='monthly',
        view_mode=view_mode,
        selected_month=selected_month,
        selected_year=selected_year,
        period_label=period_label,
        available_years=available_years,
        total_revenue=total_revenue,
        total_orders=total_orders,
        avg_ticket=int(avg_ticket),
        unique_customers=unique_customers,
        channels=channels,
        top_items=top_items,
        estimated_profit=estimated_profit,
        profit_margin=profit_margin,
        items_per_order=items_per_order,
        canceled_orders=canceled_orders,
        refund_rate=refund_rate,
        new_customers=new_count,
        returning_customers=returning_count,
        trend_labels=trend_labels,
        trend_data=trend_data,
        customer_split_data=customer_split_data,
        weekday_labels=weekday_labels,
        weekday_data=weekday_data,
        top_customers=top_customers,
        forecast_revenue=forecast_revenue
    )
 
 
@app.route('/check-cloudinary')
@manager_required
def check_cloudinary():
    """Diagnostic: verify Cloudinary credentials are loaded and working."""
    cfg = cloudinary.config()
    cloud = cfg.cloud_name or 'NOT SET'
    key = cfg.api_key or 'NOT SET'
    secret = '✅ set' if cfg.api_secret else '❌ NOT SET'
    try:
        result = cloudinary.api.ping()
        ping = f"✅ {result}"
    except Exception as e:
        ping = f"❌ {e}"
    return (
        f"<b>cloud_name:</b> {cloud}<br>"
        f"<b>api_key:</b> {key}<br>"
        f"<b>api_secret:</b> {secret}<br>"
        f"<b>ping:</b> {ping}<br><br>"
        f"<a href='/'>← Back to app</a>"
    )
 
 
@app.route('/debug-upload')
@manager_required
def debug_upload():
    """Test Cloudinary config and do a real tiny upload to confirm it works end-to-end."""
    import io
    lines = []
    cfg = cloudinary.config()
    lines.append(f"<b>cloud_name:</b> {cfg.cloud_name or '❌ NOT SET'}")
    lines.append(f"<b>api_key:</b> {cfg.api_key or '❌ NOT SET'}")
    lines.append(f"<b>api_secret:</b> {'✅ set' if cfg.api_secret else '❌ NOT SET'}")
 
    # Ping
    try:
        ping = cloudinary.api.ping()
        lines.append(f"<b>ping:</b> ✅ {ping.get('status')}")
    except Exception as e:
        lines.append(f"<b>ping:</b> ❌ {e}")
        return "<br>".join(lines) + "<br><br><a href='/'>← Back</a>"
 
    # Attempt a real upload of a 1×1 white PNG
    try:
        tiny_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
            b'\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18'
            b'\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        result = cloudinary.uploader.upload(
            io.BytesIO(tiny_png),
            folder="memory_cake/test",
            public_id="debug_ping_test",
            overwrite=True,
            resource_type="image"
        )
        lines.append(f"<b>test upload:</b> ✅ <a href='{result["secure_url"]}' target='_blank'>{result['secure_url']}</a>")
    except Exception as e:
        lines.append(f"<b>test upload:</b> ❌ {e}")
 
    return "<br>".join(lines) + "<br><br><a href='/'>← Back</a>"
 
 
@app.route('/run-migration')
@manager_required
def run_migration():
    """One-time route: adds image_url and flower_image_url columns if missing."""
    results = []
    with db.engine.connect() as conn:
        from sqlalchemy import text
        for col, col_type in [('image_url', 'TEXT'), ('flower_image_url', 'TEXT')]:
            try:
                conn.execute(text(f"ALTER TABLE order_items ADD COLUMN {col} {col_type} DEFAULT ''"))
                conn.commit()
                results.append(f"Added column: {col}")
            except Exception as e:
                results.append(f"{col}: {str(e).split('ERROR:')[-1].strip()}")
    return "<br>".join(results) + "<br><br><a href='/'>Back to app</a>"
 
 
if __name__ == '__main__':
    app.run(debug=True, port=5000)
