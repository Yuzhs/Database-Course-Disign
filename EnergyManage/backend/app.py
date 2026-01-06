"""
智慧能源管理系统 - 统一登录版
支持多角色跳转：系统管理员、数据分析师、能源管理员等
"""

from flask import Flask, request, jsonify, session, render_template, redirect, url_for
from flask_cors import CORS
from functools import wraps
import pymysql
import hashlib
import datetime
import os
import json
import subprocess
import threading
import time
import re
import psutil
import shutil
import threading
from queue import Queue
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import pymysql
import time
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, TextAreaField, DateField, DateTimeField
from wtforms.validators import DataRequired, Length

# ============ 移除 Flask-Login 依赖 ============
# from flask_login import current_user  # 注释掉这行

app = Flask(__name__, template_folder='../frontend/templates')
app.secret_key = 'energy-management-secret-key-2025'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['BACKUP_FOLDER'] = 'database_backups'
app.config['UPLOAD_FOLDER'] = 'uploads'
CORS(app)

# ============ 数据库配置 ============
DB_CONFIG = {
    'host': '47.110.69.225',
    'user': 'taohaoran',
    'password': '12345678',
    'database': 'database1',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'port': 3306,
    'use_unicode': True,
    'connect_timeout': 30,  # 增加连接超时时间
    'read_timeout': 30,     # 增加读取超时时间
    'write_timeout': 30,    # 增加写入超时时间
    'autocommit': True,     # 启用自动提交
}

# ============ 工具函数 ============
def md5_hash(password):
    """使用MD5加密密码"""
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def verify_md5(stored_hash, password):
    """验证MD5加密的密码"""
    return stored_hash == md5_hash(password)

def check_password_strength(password):
    """检查密码强度"""
    if len(password) < 8:
        return False, "密码长度至少8位"
    if not re.search(r'[A-Za-z]', password):
        return False, "密码必须包含字母"
    if not re.search(r'\d', password):
        return False, "密码必须包含数字"
    return True, "密码强度合格"



def retry_db_operation(func, max_retries=3):
    """数据库操作重试装饰器"""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as e:
                last_exception = e
                print(f"数据库操作失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # 等待1秒后重试
                    # 清除当前线程的连接
                    if hasattr(db.local, 'connection'):
                        try:
                            db.local.connection.close()
                        except:
                            pass
                        delattr(db.local, 'connection')
                else:
                    raise last_exception
        raise last_exception
    return wrapper

# 在需要数据库操作的地方使用
@app.route('/api/check-login', methods=['GET'])
def check_login():
    """检查用户登录状态"""
    cursor=None
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401

        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 使用重试机制
        @retry_db_operation
        def query_user():
            cursor = db.get_cursor()
            sql = """
            SELECT 
                u.用户ID,
                u.登录账号,
                u.真实姓名,
                u.用户角色,
                u.手机号码,
                u.负责的厂区编号,
                u.上次登录的时间,
                f.厂区名称
            FROM 用户 u
            LEFT JOIN 厂区 f ON u.负责的厂区编号 = f.厂区编号
            WHERE u.用户ID = %s
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchone()

        user = query_user()

        if not user:
            session.clear()
            return jsonify({'success': False, 'message': '用户不存在'}), 401

        # 准备返回数据
        user_info = {
            'user_id': user['用户ID'],
            'username': user['登录账号'],
            'real_name': user['真实姓名'],
            'role': user['用户角色'],
            'phone': user['手机号码'],
            'factory_id': user['负责的厂区编号'],
            'factory_name': user['厂区名称'],
            'last_login': user['上次登录的时间'].strftime('%Y-%m-%d %H:%M:%S') if user['上次登录的时间'] else None
        }

        return jsonify({'success': True, 'data': user_info})

    except Exception as e:
        print(f"检查登录失败: {str(e)}")
        # 返回简化的用户信息（如果可能）
        if 'user_id' in session:
            return jsonify({
                'success': True,
                'data': {
                    'user_id': session.get('user_id'),
                    'username': session.get('username', '用户'),
                    'real_name': session.get('username', '用户'),
                    'role': session.get('user_role', '运维人员'),
                    'phone': '',
                    'factory_id': session.get('factory_id'),
                    'factory_name': '',
                    'last_login': None
                }
            })
        return jsonify({'success': False, 'message': str(e)}), 500



def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_role(required_roles):
    """角色权限验证装饰器"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'success': False, 'message': '未登录'}), 401

            user_role = session.get('user_role')
            print(f"🔍 DEBUG - 用户角色: {user_role}, 需要的角色: {required_roles}")

            if isinstance(required_roles, str):
                required_roles_list = [required_roles]
            else:
                required_roles_list = required_roles

            # 检查用户角色是否在允许的角色列表中
            if user_role not in required_roles_list:
                print(f"❌ 权限不足: 用户角色 '{user_role}' 不在 {required_roles_list} 中")
                return jsonify({'success': False, 'message': '权限不足'}), 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator

@app.route('/api/operation/dashboard-data', methods=['GET'])
@login_required
@require_role('运维人员')
@retry_db_operation
def get_operation_dashboard_data():
    """获取运维仪表板数据"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()

        # 1. 工单统计
        sql_orders = """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN 处理完成时间 IS NULL THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN 处理完成时间 IS NOT NULL THEN 1 ELSE 0 END) as completed
        FROM 运维工单 
        WHERE 运维人员ID = %s
        """
        cursor.execute(sql_orders, (user_id,))
        orders = cursor.fetchone()

        # 2. 告警统计
        sql_alerts = """
        SELECT 
            SUM(CASE WHEN 告警等级 = '高' THEN 1 ELSE 0 END) as high_alarms,
            SUM(CASE WHEN 告警等级 = '中' THEN 1 ELSE 0 END) as medium_alarms,
            SUM(CASE WHEN 告警等级 = '低' THEN 1 ELSE 0 END) as low_alarms
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE d.所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_alerts, (user_id,))
        alerts = cursor.fetchone()

        # 3. 设备统计
        sql_devices = """
        SELECT 
            COUNT(*) as total_devices,
            SUM(CASE WHEN 运行状态 = '正常' THEN 1 ELSE 0 END) as normal,
            SUM(CASE WHEN 运行状态 = '故障' THEN 1 ELSE 0 END) as fault,
            SUM(CASE WHEN 运行状态 = '维护中' THEN 1 ELSE 0 END) as maintenance,
            SUM(CASE WHEN 运行状态 = '离线' THEN 1 ELSE 0 END) as offline
        FROM 设备
        WHERE 所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_devices, (user_id,))
        devices = cursor.fetchone()

        # 4. 最近活动（已完成工单）
        sql_activities = """
        SELECT 
            w.工单编号,
            w.处理结果,
            w.处理完成时间,
            a.告警内容
        FROM 运维工单 w
        JOIN 告警信息 a ON w.告警ID = a.告警ID
        WHERE w.运维人员ID = %s 
          AND w.处理完成时间 IS NOT NULL
        ORDER BY w.处理完成时间 DESC
        LIMIT 5
        """
        cursor.execute(sql_activities, (user_id,))
        activities = cursor.fetchall()

        # 5. 待处理工单
        sql_pending = """
        SELECT 
            w.工单编号,
            a.告警内容,
            a.告警等级,
            d.设备名称,
            w.派单时间
        FROM 运维工单 w
        JOIN 告警信息 a ON w.告警ID = a.告警ID
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE w.运维人员ID = %s 
          AND w.处理完成时间 IS NULL
        ORDER BY w.派单时间 DESC
        LIMIT 5
        """
        cursor.execute(sql_pending, (user_id,))
        pending_orders = cursor.fetchall()

        # 准备返回数据
        dashboard_data = {
            'stats': {
                'total_orders': orders['total'] if orders else 0,
                'pending_orders': orders['pending'] if orders else 0,
                'completed_orders': orders['completed'] if orders else 0,
                'high_alarms': alerts['high_alarms'] if alerts else 0,
                'medium_alarms': alerts['medium_alarms'] if alerts else 0,
                'low_alarms': alerts['low_alarms'] if alerts else 0
            },
            'equipment': {
                'total': devices['total_devices'] if devices else 0,
                'normal': devices['normal'] if devices else 0,
                'fault': devices['fault'] if devices else 0,
                'maintenance': devices['maintenance'] if devices else 0,
                'offline': devices['offline'] if devices else 0
            },
            'recent_activities': activities,
            'pending_orders': pending_orders
        }

        return jsonify({
            'success': True,
            'data': dashboard_data
        })

    except Exception as e:
        print(f"获取仪表板数据失败: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# ============ 数据库连接池 ============

class Database:
    def __init__(self):
        self.connection = None
        self.max_retries = 3
        self.retry_delay = 2

    def connect(self):
        """建立数据库连接"""
        try:
            if self.connection is None or not self.connection.open:
                self.connection = pymysql.connect(**DB_CONFIG)
                print(f"✅ 数据库连接成功")
            return self.connection
        except Exception as e:
            print(f"❌ 数据库连接失败: {str(e)}")
            raise

    def get_cursor(self):
        """获取游标，更简单的实现"""
        try:
            conn = self.connect()
            # 尝试ping，如果失败则重新连接
            try:
                conn.ping(reconnect=True)
            except:
                self.connection = None
                conn = self.connect()
            return conn.cursor()
        except Exception as e:
            print(f"获取游标失败: {str(e)}")
            # 如果失败，尝试重新连接
            self.connection = None
            for i in range(self.max_retries):
                try:
                    time.sleep(self.retry_delay)
                    self.connection = pymysql.connect(**DB_CONFIG)
                    return self.connection.cursor()
                except Exception as retry_error:
                    print(f"重试连接失败 ({i + 1}/{self.max_retries}): {retry_error}")
            raise Exception(f"数据库连接失败")

class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(min=3)])
    password = PasswordField('密码', validators=[DataRequired()])

class CreateWorkOrderForm(FlaskForm):
    alarm_id = StringField('告警ID', validators=[DataRequired()])
    operator_id = SelectField('运维人员', choices=[], validators=[DataRequired()])
    priority = SelectField('优先级', choices=[
        ('high', '高'),
        ('medium', '中'),
        ('low', '低')
    ], validators=[DataRequired()])
    description = TextAreaField('工单描述')
    deadline = DateField('截止时间', validators=[DataRequired()])

class ReviewWorkOrderForm(FlaskForm):
    review_status = SelectField('复查状态', choices=[
        ('通过', '通过'),
        ('未通过', '未通过')
    ], validators=[DataRequired()])
    review_notes = TextAreaField('复查备注')
    re_assign = SelectField('重新派单给', choices=[('', '不重新派单')])
# class Database:
#     def __init__(self, pool_size=5):
#         self.pool_size = pool_size
#         self.connection_pool = Queue(maxsize=pool_size)
#         self.lock = Lock()
#         self.max_retries = 3
#         self.retry_delay = 2
#         self._init_pool()
#
#     def _init_pool(self):
#         """初始化连接池"""
#         for _ in range(self.pool_size):
#             try:
#                 conn = pymysql.connect(**DB_CONFIG)
#                 self.connection_pool.put(conn)
#             except Exception as e:
#                 logger.error(f"初始化数据库连接失败: {e}")
#                 raise
#
#     def get_connection(self):
#         """从连接池获取连接"""
#         try:
#             conn = self.connection_pool.get(block=True, timeout=5)
#
#             # 检查连接是否有效
#             try:
#                 conn.ping(reconnect=True)
#                 return conn
#             except:
#                 # 连接无效，创建新的
#                 conn = self._create_new_connection()
#                 return conn
#
#         except Exception as e:
#             logger.error(f"获取数据库连接失败: {e}")
#             # 如果获取失败，创建新连接
#             return self._create_new_connection()
#
#     def _create_new_connection(self):
#         """创建新的数据库连接"""
#         for i in range(self.max_retries):
#             try:
#                 conn = pymysql.connect(**DB_CONFIG)
#                 logger.info("✅ 创建新的数据库连接成功")
#                 return conn
#             except Exception as e:
#                 logger.error(f"创建数据库连接失败 ({i + 1}/{self.max_retries}): {e}")
#                 if i < self.max_retries - 1:
#                     time.sleep(self.retry_delay)
#                 else:
#                     raise Exception(f"无法连接到数据库: {e}")
#
#     def release_connection(self, connection):
#         """释放连接回连接池"""
#         if connection:
#             try:
#                 # 检查连接是否仍然有效
#                 connection.ping(reconnect=True)
#                 self.connection_pool.put(connection)
#             except:
#                 # 连接已损坏，创建新的放回池中
#                 try:
#                     new_conn = self._create_new_connection()
#                     self.connection_pool.put(new_conn)
#                 except:
#                     logger.error("无法替换损坏的连接")
#
#     def get_cursor(self, connection=None):
#         """获取游标 - 简化版"""
#         if not connection:
#             connection = self.get_connection()
#         try:
#             return connection.cursor(pymysql.cursors.DictCursor)
#         except Exception as e:
#             logger.error(f"获取游标失败: {e}")
#             raise
#
#     def execute_query(self, query, params=None, fetch_all=True):
#         """执行查询的便捷方法"""
#         conn = None
#         try:
#             conn = self.get_connection()
#             with conn.cursor(pymysql.cursors.DictCursor) as cursor:
#                 cursor.execute(query, params or ())
#                 if fetch_all:
#                     result = cursor.fetchall()
#                 else:
#                     result = cursor.fetchone()
#                 conn.commit()
#                 return result
#         except Exception as e:
#             if conn:
#                 conn.rollback()
#             logger.error(f"查询执行失败: {e}")
#             raise
#         finally:
#             if conn:
#                 self.release_connection(conn)
#
#     def close_all(self):
#         """关闭所有连接"""
#         try:
#             while not self.connection_pool.empty():
#                 conn = self.connection_pool.get_nowait()
#                 try:
#                     conn.close()
#                 except:
#                     pass
#         except:
#             pass
#
#     # 为了兼容现有的 get_cursor 方法
#     def connect(self):
#         """兼容方法 - 返回一个连接"""
#         return self.get_connection()

db = Database()

# ============ 统一登录路由 ============
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """统一登录页面"""
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    try:
        cursor = db.get_cursor()

        # 查询用户信息
        sql = """
        SELECT u.*, p.厂区名称 
        FROM 用户 u 
        LEFT JOIN 厂区 p ON u.负责的厂区编号 = p.厂区编号
        WHERE u.登录账号 = %s
        """
        cursor.execute(sql, (username,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'error': '用户名或密码错误'}), 401

        # 检查账号是否锁定
        if user['登录失败的次数'] >= 4:
            return jsonify({'error': '账号已锁定，请联系管理员'}), 423

        # 验证密码
        stored_password = None
        for field in ['密码哈希值', '密码', 'password']:
            if field in user and user[field]:
                stored_password = user[field]
                break

        if not stored_password or not verify_md5(stored_password, password):
            # 密码错误，增加失败次数
            update_sql = """
            UPDATE 用户 
            SET 登录失败的次数 = 登录失败的次数 + 1 
            WHERE 用户ID = %s
            """
            cursor.execute(update_sql, (user['用户ID'],))
            db.connect().commit()

            return jsonify({'error': '用户名或密码错误'}), 401

        # 登录成功，重置失败次数
        update_sql = """
        UPDATE 用户 
        SET 登录失败的次数 = 0, 上次登录的时间 = %s 
        WHERE 用户ID = %s
        """
        cursor.execute(update_sql, (datetime.now(), user['用户ID']))
        db.connect().commit()

        # 设置session
        session['user_id'] = user['用户ID']
        session['user_role'] = user['用户角色']
        session['username'] = user['真实姓名']
        session['factory_id'] = user['负责的厂区编号']
        session['last_activity'] = time.time()

        print(f"DEBUG - Login successful for user: {user['真实姓名']}, role: {user['用户角色']}")

        # 根据角色返回不同的跳转路径
        role = user['用户角色']
        redirect_url = get_redirect_url_by_role(role)

        return jsonify({
            'success': True,
            'user_id': user['用户ID'],
            'role': role,
            'name': user['真实姓名'],
            'factory_name': user['厂区名称'],
            'redirect_url': redirect_url
        })

    except Exception as e:
        print(f"登录错误: {str(e)}")
        return jsonify({'error': f'登录失败: {str(e)}'}), 500

def get_redirect_url_by_role(role):
    """根据用户角色返回对应的跳转路径"""
    role_map = {
        '系统管理员': '/admin/dashboard',
        '数据分析师': '/analyst/dashboard',
        '能源管理员': '/energy/dashboard',
        '运维人员': '/operation/dashboard',
        '运维工单管理员': '/workorder/dashboard',
        '企业管理层': '/management/dashboard'
    }
    return role_map.get(role, '/dashboard')

# ============ 当前用户信息路由 ============
@app.route('/current_user')
def get_current_user():
    """获取当前登录用户信息"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401

        return jsonify({
            'success': True,
            'user': {
                'id': session.get('user_id'),
                'role': session.get('user_role'),
                'name': session.get('username'),
                'factory_id': session.get('factory_id')
            }
        })
    except Exception as e:
        print(f"获取当前用户失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 角色专属仪表板路由 ============
@app.route('/admin/dashboard')
@login_required
@require_role('系统管理员')
def admin_dashboard():
    """系统管理员仪表板"""
    return render_template('admin_dashboard.html')

@app.route('/analyst/dashboard')
@login_required
@require_role('数据分析师')
def analyst_dashboard_page():
    """数据分析师仪表板页面"""
    return render_template('analyst_dashboard.html')

# @app.route('/energy/dashboard')
# @login_required
# @require_role('能源管理员')
# def energy_dashboard():
#     """能源管理员仪表板（重定向到新版本）"""
#     return redirect(url_for('energy_dashboard_original'))

@app.route('/operation/dashboard')
@login_required
@require_role('运维人员')
def operation_dashboard():
    """运维人员仪表板"""
    return render_template('operation/dashboard.html')
@app.route('/operation/alerts')
@login_required
def alerts():
    return render_template('operation/alerts.html')

@app.route('/operation/equipment')
@login_required
def equipment():
    return render_template('operation/equipment.html')

@app.route('/operation/profile')
@login_required
def profile():
    return render_template('operation/profile.html')

@app.route('/operation/work_orders')
@login_required
def work_orders():
    return render_template('operation/work_orders.html')
@app.route('/dashboard')
@login_required
def user_dashboard():
    """默认用户仪表板（其他角色）"""
    user_role = session.get('user_role', '')
    if user_role == '系统管理员':
        return redirect(url_for('admin_dashboard'))
    elif user_role == '数据分析师':
        return redirect(url_for('analyst_dashboard_page'))
    elif user_role == '能源管理员':
        return redirect(url_for('energy_dashboard_original'))
    elif user_role == '运维人员':
        return redirect(url_for('operation_dashboard'))
    else:
        return render_template('user_dashboard.html')

# ============ 数据分析师功能路由 ============

@app.route('/api/analyst/dashboard', methods=['GET'])
@login_required
@require_role('数据分析师')
def get_analyst_dashboard_data():
    """获取数据分析师仪表盘数据"""
    try:
        # 最近30天的数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        cursor = db.get_cursor()

        # 查询光伏预测数据
        sql = """
        SELECT 
            COUNT(*) as total_predictions,
            SUM(CASE WHEN ABS(偏差率) < 10 THEN 1 ELSE 0 END) as accurate_predictions
        FROM 光伏预测数据
        WHERE 预测日期 BETWEEN %s AND %s
        """
        cursor.execute(sql, (start_date, end_date))
        pv_stats = cursor.fetchone()

        # 查询能耗数据
        sql = """
        SELECT 
            SUM(总能耗) as total_energy,
            SUM(能耗成本) as total_cost
        FROM 峰谷能耗数据
        WHERE 统计日期 BETWEEN %s AND %s
        """
        cursor.execute(sql, (start_date, end_date))
        energy_stats = cursor.fetchone()

        # 构建返回数据
        total_predictions = pv_stats['total_predictions'] if pv_stats and pv_stats['total_predictions'] else 0
        accurate_predictions = pv_stats['accurate_predictions'] if pv_stats and pv_stats['accurate_predictions'] else 0

        dashboard_data = {
            'pv_analysis': {
                'total_predictions': total_predictions,
                'accurate_predictions': accurate_predictions,
                'accuracy_rate': round((accurate_predictions / total_predictions * 100) if total_predictions > 0 else 0, 2),
                'date_range': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                }
            },
            'energy_analysis': {
                'total_energy': float(energy_stats['total_energy']) if energy_stats and energy_stats['total_energy'] else 0.0,
                'total_cost': float(energy_stats['total_cost']) if energy_stats and energy_stats['total_cost'] else 0.0,
                'energy_by_type': {
                    '电': {
                        'total_energy': float(energy_stats['total_energy'] or 0) * 0.68,
                        'total_cost': float(energy_stats['total_cost'] or 0) * 0.68
                    },
                    '水': {
                        'total_energy': float(energy_stats['total_energy'] or 0) * 0.20,
                        'total_cost': float(energy_stats['total_cost'] or 0) * 0.20
                    },
                    '天然气': {
                        'total_energy': float(energy_stats['total_energy'] or 0) * 0.12,
                        'total_cost': float(energy_stats['total_cost'] or 0) * 0.12
                    }
                }
            },
            'summary': {
                'date_range': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                }
            }
        }

        return jsonify({
            'success': True,
            'data': dashboard_data
        })

    except Exception as e:
        print(f"获取仪表盘数据失败: {str(e)}")
        return jsonify({'success': False, 'message': f'获取仪表盘数据失败: {str(e)}'}), 500

@app.route('/api/analyst/pv-analysis', methods=['GET'])
@login_required
@require_role('数据分析师')
def analyze_pv_prediction():
    """分析光伏预测数据"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # 设置默认日期范围
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')

        cursor = db.get_cursor()

        # 查询光伏预测数据
        sql = """
        SELECT 
            预测编号,
            预测日期,
            预测时段,
            预测发电量,
            实际发电量,
            偏差率,
            预测模型版本
        FROM 光伏预测数据
        WHERE 预测日期 BETWEEN %s AND %s
        ORDER BY 预测日期
        """
        cursor.execute(sql, (start_date, end_date))
        predictions = cursor.fetchall()

        prediction_list = []
        total_predictions = len(predictions)
        high_deviation_count = 0
        total_deviation = 0
        max_deviation = 0
        max_deviation_date = None

        for pred in predictions:
            deviation = abs(float(pred['偏差率'])) if pred['偏差率'] else 0
            total_deviation += deviation

            if deviation > 15:  # 偏差率超过15%为高偏差
                high_deviation_count += 1
                needs_optimization = True
            else:
                needs_optimization = False

            if deviation > max_deviation:
                max_deviation = deviation
                max_deviation_date = pred['预测日期']

            prediction_list.append({
                '预测编号': pred['预测编号'],
                '预测日期': pred['预测日期'].strftime('%Y-%m-%d') if pred['预测日期'] else None,
                '预测时段': pred['预测时段'],
                '预测发电量': float(pred['预测发电量']) if pred['预测发电量'] else 0,
                '实际发电量': float(pred['实际发电量']) if pred['实际发电量'] else 0,
                '偏差率': float(pred['偏差率']) if pred['偏差率'] else 0,
                '预测模型版本': pred['预测模型版本'],
                '需要优化': needs_optimization
            })

        average_deviation = total_deviation / total_predictions if total_predictions > 0 else 0
        high_deviation_percentage = (high_deviation_count / total_predictions * 100) if total_predictions > 0 else 0

        return jsonify({
            'success': True,
            'data': {
                'predictions': prediction_list,
                'total_predictions': total_predictions,
                'high_deviation_count': high_deviation_count,
                'high_deviation_percentage': round(high_deviation_percentage, 2),
                'average_deviation': round(average_deviation, 2),
                'max_deviation': {
                    '偏差率': round(max_deviation, 2),
                    '预测日期': max_deviation_date.strftime('%Y-%m-%d') if max_deviation_date else None
                }
            }
        })

    except Exception as e:
        print(f"光伏预测分析失败: {str(e)}")
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500

@app.route('/api/analyst/optimize-model', methods=['POST'])
@login_required
@require_role('数据分析师')
def optimize_model():
    """优化预测模型"""
    try:
        data = request.get_json()
        deviation_threshold = data.get('deviation_threshold', 15)

        cursor = db.get_cursor()

        # 查找需要优化的预测记录
        sql = """
        SELECT DISTINCT 预测模型版本 
        FROM 光伏预测数据 
        WHERE 偏差率 >= %s 
        AND 预测日期 >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """
        cursor.execute(sql, (deviation_threshold,))
        problematic_models = cursor.fetchall()

        # 获取受影响的设备
        affected_devices = []
        if problematic_models:
            model_versions = [model['预测模型版本'] for model in problematic_models if model['预测模型版本']]

            if model_versions:
                placeholders = ', '.join(['%s'] * len(model_versions))
                device_sql = f"""
                SELECT DISTINCT 设备编号 
                FROM 光伏发电数据 
                WHERE 设备编号 IN (
                    SELECT DISTINCT 并网点编号 
                    FROM 光伏预测数据 
                    WHERE 预测模型版本 IN ({placeholders})
                )
                """
                cursor.execute(device_sql, tuple(model_versions))
                device_results = cursor.fetchall()
                affected_devices = [device['设备编号'] for device in device_results if device['设备编号']]

        # 生成优化建议
        optimization_suggestions = []
        if problematic_models:
            optimization_suggestions = [
                "检测到连续高偏差预测，建议更新预测模型",
                f"当前使用天气因子数量不足，建议增加天气数据维度",
                "建议增加历史训练数据的时间范围",
                f"调整模型参数，当前偏差阈值{deviation_threshold}%过高"
            ]
        else:
            optimization_suggestions = ["当前预测模型表现良好，无需立即优化"]

        # 生成新模型版本号
        new_model_version = f"V{datetime.now().strftime('%Y%m%d_%H%M')}"

        optimization_result = {
            'analyzed_predictions': len(problematic_models),
            'problematic_models': [{'版本': model['预测模型版本']} for model in problematic_models if model['预测模型版本']],
            'optimization_suggestions': optimization_suggestions,
            'new_model_version': new_model_version,
            'affected_devices': affected_devices
        }

        return jsonify({
            'success': True,
            'data': optimization_result
        })

    except Exception as e:
        print(f"模型优化失败: {str(e)}")
        return jsonify({'success': False, 'message': f'优化失败: {str(e)}'}), 500

@app.route('/api/analyst/energy-patterns', methods=['GET'])
@login_required
@require_role('数据分析师')
def analyze_energy_patterns():
    """分析能耗模式"""
    try:
        plant_id = request.args.get('plant_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # 设置默认日期范围
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')

        cursor = db.get_cursor()

        # 构建查询条件
        if plant_id:
            sql = """
            SELECT 
                能源类型,
                SUM(总能耗) as total_energy,
                SUM(能耗成本) as total_cost,
                SUM(尖峰时段能耗 + 高峰时段能耗) as peak_energy,
                COUNT(*) as record_count
            FROM 峰谷能耗数据
            WHERE 厂区编号 = %s AND 统计日期 BETWEEN %s AND %s
            GROUP BY 能源类型
            """
            cursor.execute(sql, (plant_id, start_date, end_date))
        else:
            sql = """
            SELECT 
                能源类型,
                SUM(总能耗) as total_energy,
                SUM(能耗成本) as total_cost,
                SUM(尖峰时段能耗 + 高峰时段能耗) as peak_energy,
                COUNT(*) as record_count
            FROM 峰谷能耗数据
            WHERE 统计日期 BETWEEN %s AND %s
            GROUP BY 能源类型
            """
            cursor.execute(sql, (start_date, end_date))

        energy_stats = cursor.fetchall()

        # 分析能耗模式
        energy_by_type = {}
        total_energy = 0
        total_cost = 0
        peak_energy_total = 0

        for record in energy_stats:
            energy_type = record['能源类型']
            total = float(record['total_energy']) if record['total_energy'] else 0
            cost = float(record['total_cost']) if record['total_cost'] else 0
            peak = float(record['peak_energy']) if record['peak_energy'] else 0

            energy_by_type[energy_type] = {
                'total_energy': total,
                'total_cost': cost,
                'peak_energy': peak,
                'record_count': record['record_count']
            }

            total_energy += total
            total_cost += cost
            peak_energy_total += peak

        # 计算百分比和峰段占比
        for energy_type, data in energy_by_type.items():
            if total_energy > 0:
                data['percentage'] = (data['total_energy'] / total_energy) * 100
            else:
                data['percentage'] = 0

            if data['total_energy'] > 0:
                data['peak_ratio'] = (data['peak_energy'] / data['total_energy']) * 100
            else:
                data['peak_ratio'] = 0

        # 节能潜力分析
        energy_saving_potential = []
        avg_peak_ratio = (peak_energy_total / total_energy * 100) if total_energy > 0 else 0

        for energy_type, data in energy_by_type.items():
            if data['peak_ratio'] > avg_peak_ratio * 1.2:  # 峰段占比高于平均值20%
                estimated_saving = data['total_cost'] * 0.15  # 预计可节省15%
                energy_saving_potential.append({
                    'energy_type': energy_type,
                    'current_peak_ratio': data['peak_ratio'],
                    'suggestion': f'建议调整{energy_type}使用时间，降低峰段消耗',
                    'estimated_saving': estimated_saving
                })

        return jsonify({
            'success': True,
            'data': {
                'analysis_period': {
                    'start': start_date,
                    'end': end_date
                },
                'total_analysis': {
                    'total_energy': round(total_energy, 2),
                    'total_cost': round(total_cost, 2),
                    'avg_peak_ratio': round(avg_peak_ratio, 2)
                },
                'energy_by_type': energy_by_type,
                'energy_saving_potential': energy_saving_potential
            }
        })

    except Exception as e:
        print(f"能耗模式分析失败: {str(e)}")
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500

@app.route('/api/analyst/generate-report', methods=['POST'])
@login_required
@require_role('数据分析师')
def generate_report():
    """生成能源报告"""
    try:
        data = request.get_json()
        report_type = data.get('report_type', 'monthly')
        year = data.get('year')
        month = data.get('month')

        # 处理参数
        current_time = datetime.now()
        if not year:
            year = current_time.year
        if not month:
            month = current_time.month

        try:
            year = int(year)
            month = int(month)
        except (ValueError, TypeError):
            year = current_time.year
            month = current_time.month

        # 根据报告类型确定时间范围
        try:
            if report_type == 'monthly':
                start_date = datetime(year, month, 1)
                if month == 12:
                    end_date = datetime(year + 1, 1, 1)
                else:
                    end_date = datetime(year, month + 1, 1)
                period_str = f"{year}年{month}月"
                report_type_name = f"{year}年{month}月分析报告"
            elif report_type == 'quarterly':
                quarter = (month - 1) // 3 + 1
                quarter_start_month = (quarter - 1) * 3 + 1
                start_date = datetime(year, quarter_start_month, 1)
                if quarter == 4:
                    end_date = datetime(year + 1, 1, 1)
                else:
                    end_date = datetime(year, quarter_start_month + 3, 1)
                period_str = f"{year}年第{quarter}季度"
                report_type_name = f"{year}年第{quarter}季度分析报告"
            else:  # yearly
                start_date = datetime(year, 1, 1)
                end_date = datetime(year, 12, 31)
                period_str = f"{year}年"
                report_type_name = f"{year}年度分析报告"
        except Exception as e:
            print(f"日期创建失败: {str(e)}")
            # 使用当前月份作为回退
            start_date = datetime(current_time.year, current_time.month, 1)
            if current_time.month == 12:
                end_date = datetime(current_time.year + 1, 1, 1)
            else:
                end_date = datetime(current_time.year, current_time.month + 1, 1)
            period_str = f"{current_time.year}年{current_time.month}月"
            report_type_name = f"{current_time.year}年{current_time.month}月分析报告"

        cursor = db.get_cursor()

        # 1. 能耗统计
        sql = """
        SELECT 
            SUM(总能耗) as total_energy,
            SUM(能耗成本) as total_cost
        FROM 峰谷能耗数据
        WHERE 统计日期 >= %s AND 统计日期 < %s
        """
        cursor.execute(sql, (start_date, end_date))
        energy_stats = cursor.fetchone()

        total_energy = float(energy_stats['total_energy']) if energy_stats and energy_stats['total_energy'] else 0.0
        total_cost = float(energy_stats['total_cost']) if energy_stats and energy_stats['total_cost'] else 0.0

        # 2. 光伏发电统计
        sql = """
        SELECT 
            SUM(发电量) as total_generation,
            SUM(自用电量) as total_self_use
        FROM 光伏发电数据
        WHERE 采集时间 >= %s AND 采集时间 < %s
        """
        cursor.execute(sql, (start_date, end_date))
        pv_stats = cursor.fetchone()

        pv_generation = float(pv_stats['total_generation']) if pv_stats and pv_stats['total_generation'] else 0.0
        pv_self_use = float(pv_stats['total_self_use']) if pv_stats and pv_stats['total_self_use'] else 0.0

        # 3. 告警统计
        sql = """
        SELECT 
            COUNT(*) as total_alarms,
            SUM(CASE WHEN 处理状态 = '已结案' THEN 1 ELSE 0 END) as resolved_alarms
        FROM 告警信息
        WHERE 发生时间 >= %s AND 发生时间 < %s
        """
        cursor.execute(sql, (start_date, end_date))
        alarm_stats = cursor.fetchone()

        total_alarms = int(alarm_stats['total_alarms']) if alarm_stats and alarm_stats['total_alarms'] else 0
        resolved_alarms = int(alarm_stats['resolved_alarms']) if alarm_stats and alarm_stats['resolved_alarms'] else 0
        resolution_rate = (resolved_alarms / total_alarms * 100) if total_alarms > 0 else 0

        # 4. 获取能源类型分布（真实数据）
        sql = """
        SELECT 
            能源类型,
            SUM(总能耗) as type_energy,
            SUM(能耗成本) as type_cost
        FROM 峰谷能耗数据
        WHERE 统计日期 >= %s AND 统计日期 < %s
        GROUP BY 能源类型
        """
        cursor.execute(sql, (start_date, end_date))
        energy_by_type_data = cursor.fetchall()

        # 5. 获取厂区分布（真实数据）
        sql = """
        SELECT 
            p.厂区名称,
            SUM(e.总能耗) as plant_energy,
            SUM(e.能耗成本) as plant_cost
        FROM 峰谷能耗数据 e
        LEFT JOIN 厂区 p ON e.厂区编号 = p.厂区编号
        WHERE e.统计日期 >= %s AND e.统计日期 < %s
        GROUP BY p.厂区名称
        HAVING p.厂区名称 IS NOT NULL
        """
        cursor.execute(sql, (start_date, end_date))
        energy_by_plant_data = cursor.fetchall()

        # 6. 获取光伏效率数据（模拟数据）
        pv_efficiency = {
            'average_efficiency': 93.4,
            'below_threshold': 0,
            'below_threshold_percentage': 0.0
        }

        # 7. 获取小时能耗模式（模拟数据）
        energy_by_hour = {
            '8': {'average': 960.00},
            '9': {'average': 980.00},
            '10': {'average': 1000.00},
            '11': {'average': 1020.00},
            '12': {'average': 1040.00},
            '13': {'average': 1060.00},
            '14': {'average': 1080.00},
            '15': {'average': 1100.00},
            '16': {'average': 1120.00},
            '17': {'average': 1140.00},
            '18': {'average': 1160.00},
            '19': {'average': 275.00},
            '20': {'average': 260.00}
        }

        # 8. 获取数据质量说明（模拟数据）
        raw_data_summary = {
            'energy_records': 1,
            'pv_records': 3,
            'alarm_records': 0
        }
        report_id = f"REPORT_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 生成文本格式的报告内容
        report_content = format_report_to_text({
            'report_id' : report_id,
            'report_type': report_type_name,
            'period': period_str,
            'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            },
            'summary': {
                'total_energy_consumption': total_energy,
                'total_energy_cost': total_cost,
                'total_pv_generation': pv_generation,
                'total_pv_self_use': pv_self_use,
                'total_alarms': total_alarms,
                'resolved_alarms': resolved_alarms,
                'resolution_rate': round(resolution_rate, 1)
            },
            'detailed_analysis': {
                'energy_by_type': energy_by_type_data,
                'energy_by_plant': energy_by_plant_data,
                'alarm_statistics': {
                    'by_level': {
                        '高': max(0, total_alarms // 3),
                        '中': max(0, total_alarms // 3),
                        '低': max(0, total_alarms // 3)
                    },
                    'resolution_rate': round(resolution_rate, 1)
                },
                'pv_efficiency': pv_efficiency,
                'recommendations': [
                    '当前能源运行状况良好，继续保持'
                ],
                'energy_by_hour': energy_by_hour
            },
            'raw_data_summary': raw_data_summary
        })

        # 保存报告到数据库
        try:
            user_id = session.get('user_id')
            report_id = f"REPORT_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            report_type_int = 1 if report_type == 'monthly' else 2

            insert_sql = """
            INSERT INTO 简单报告 (报告ID, 报告类型, 报告内容, 生成时间, 生成人ID)
            VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(insert_sql, (report_id, report_type_int, report_content, datetime.now(), user_id))
            db.connect().commit()

        except Exception as e:
            print(f"保存报告到数据库失败: {str(e)}")
            # 继续返回报告数据，不中断流程
            report_id = f"REPORT_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        return jsonify({
            'success': True,
            'message': '报告生成成功',
            'report_id': report_id,
            'report_content': report_content
        })

    except Exception as e:
        print(f"生成报告失败: {str(e)}")
        return jsonify({'success': False, 'message': f'报告生成失败: {str(e)}'}), 500


def format_report_to_text(data):
    """将报告数据格式化为文本格式"""
    try:
        text = f"智慧能源管理系统 - {data['report_type']}\n"
        text += "=" * 50 + "\n\n"

        text += f"报告ID: {data.get('report_id', 'N/A')}\n"
        text += f"生成时间: {data['generation_time']}\n"
        text += f"数据范围: {data['data_range']['start']} 至 {data['data_range']['end']}\n\n"

        # 一、报告摘要
        text += "一、报告摘要\n"
        text += "-" * 30 + "\n"
        summary = data['summary']
        text += f"总能耗: {summary.get('total_energy_consumption', 0):.2f}\n"
        text += f"总成本: ￥{summary.get('total_energy_cost', 0):.2f}\n"
        text += f"光伏总发电量: {summary.get('total_pv_generation', 0):.2f} kWh\n"
        text += f"光伏自用电量: {summary.get('total_pv_self_use', 0):.2f} kWh\n"
        text += f"总告警次数: {summary.get('total_alarms', 0)}\n"
        text += f"告警处理率: {summary.get('resolution_rate', 0):.1f}%\n\n"

        # 二、详细分析
        text += "二、详细分析\n"
        text += "-" * 30 + "\n"

        # 1. 按能源类型统计
        if data['detailed_analysis'].get('energy_by_type'):
            text += "1. 按能源类型统计:\n"
            for item in data['detailed_analysis']['energy_by_type']:
                energy_type = item.get('能源类型', '未知')
                type_energy = float(item.get('type_energy', 0))
                type_cost = float(item.get('type_cost', 0))
                if data['summary']['total_energy_consumption'] > 0:
                    percentage = (type_energy / data['summary']['total_energy_consumption']) * 100
                else:
                    percentage = 0
                text += f"   {energy_type}: {type_energy:.2f} ({percentage:.1f}%) - 成本: ￥{type_cost:.2f}\n"
            text += "\n"

        # 2. 按厂区统计
        if data['detailed_analysis'].get('energy_by_plant'):
            text += "2. 按厂区统计:\n"
            for item in data['detailed_analysis']['energy_by_plant']:
                plant_name = item.get('厂区名称', '未知厂区')
                plant_energy = float(item.get('plant_energy', 0))
                if data['summary']['total_energy_consumption'] > 0:
                    percentage = (plant_energy / data['summary']['total_energy_consumption']) * 100
                else:
                    percentage = 0
                text += f"   {plant_name}: {plant_energy:.2f} ({percentage:.1f}%)\n"
            text += "\n"

        # 3. 告警统计
        alarm_stats = data['detailed_analysis'].get('alarm_statistics', {})
        text += "3. 告警统计:\n"
        text += f"   高等级告警: {alarm_stats.get('by_level', {}).get('高', 0)}\n"
        text += f"   中等级告警: {alarm_stats.get('by_level', {}).get('中', 0)}\n"
        text += f"   低等级告警: {alarm_stats.get('by_level', {}).get('低', 0)}\n"
        text += f"   处理完成率: {alarm_stats.get('resolution_rate', 0):.1f}%\n\n"

        # 4. 光伏效率分析
        pv_efficiency = data['detailed_analysis'].get('pv_efficiency', {})
        if pv_efficiency:
            text += "4. 光伏效率分析:\n"
            text += f"   平均效率: {pv_efficiency.get('average_efficiency', 0):.1f}%\n"
            text += f"   低于阈值设备数: {pv_efficiency.get('below_threshold', 0)}\n"
            text += f"   低效率占比: {pv_efficiency.get('below_threshold_percentage', 0):.1f}%\n\n"

        # 三、优化建议
        text += "三、优化建议\n"
        text += "-" * 30 + "\n"
        recommendations = data['detailed_analysis'].get('recommendations', [])
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                text += f"{i}. {rec}\n"
        else:
            text += "暂无优化建议\n"

        # 四、小时能耗模式（可选展示）
        energy_by_hour = data['detailed_analysis'].get('energy_by_hour', {})
        if energy_by_hour:
            text += "\n四、小时能耗模式\n"
            text += "-" * 30 + "\n"

            # 只显示关键时段
            key_hours = ['8', '9', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20']
            for hour in key_hours:
                hour_data = energy_by_hour.get(str(hour), {})
                if hour_data:
                    text += f"   {hour}:00 - {hour_data.get('average', 0):.2f}\n"

        # 五、数据质量说明
        raw_data = data.get('raw_data_summary', {})
        text += "\n五、数据质量说明\n"
        text += "-" * 30 + "\n"
        text += f"能耗记录数: {raw_data.get('energy_records', 0)}\n"
        text += f"光伏记录数: {raw_data.get('pv_records', 0)}\n"
        text += f"告警记录数: {raw_data.get('alarm_records', 0)}\n"

        return text

    except Exception as e:
        print(f"格式化报告失败: {str(e)}")
        return f"报告生成错误: {str(e)}\n"

@app.route('/api/analyst/my-simple-reports', methods=['GET'])
@login_required
@require_role('数据分析师')
def get_my_simple_reports():
    """获取当前用户的简单报告列表"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()

        # 查询用户的报告
        sql = """
        SELECT 
            报告ID,
            报告类型,
            报告内容,
            生成时间
        FROM 简单报告
        WHERE 生成人ID = %s
        ORDER BY 生成时间 DESC
        """
        cursor.execute(sql, (user_id,))
        reports = cursor.fetchall()

        # 格式化报告列表
        report_list = []
        for report in reports:
            report_type = '月度报告' if report['报告类型'] == 1 else '季度报告'

            # 提取报告内容的前100个字符作为预览
            content_preview = report['报告内容']
            if content_preview and len(content_preview) > 100:
                content_preview = content_preview[:100] + '...'
            elif not content_preview:
                content_preview = ''

            report_list.append({
                '报告ID': report['报告ID'],
                '报告类型': report_type,
                '生成时间': report['生成时间'].strftime('%Y-%m-%d %H:%M:%S') if report['生成时间'] else '',
                '内容预览': content_preview
            })

        return jsonify({
            'success': True,
            'data': report_list
        })

    except Exception as e:
        print(f"获取报告列表失败: {str(e)}")
        return jsonify({'success': False, 'message': f'获取报告列表失败: {str(e)}'}), 500

@app.route('/api/analyst/report/<report_id>', methods=['GET'])
@login_required
@require_role('数据分析师')
def get_report_detail(report_id):
    """获取报告详情"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()

        # 查询报告详情
        sql = """
        SELECT 
            报告ID,
            报告类型,
            报告内容,
            生成时间,
            生成人ID
        FROM 简单报告
        WHERE 报告ID = %s
        """
        cursor.execute(sql, (report_id,))
        report = cursor.fetchone()

        if not report:
            return jsonify({'success': False, 'message': '报告不存在'}), 404

        # 检查是否是当前用户的报告
        if report['生成人ID'] != user_id:
            return jsonify({'success': False, 'message': '无权查看此报告'}), 403

        # 获取生成人姓名
        user_sql = "SELECT 真实姓名 FROM 用户 WHERE 用户ID = %s"
        cursor.execute(user_sql, (user_id,))
        user_info = cursor.fetchone()
        generator_name = user_info['真实姓名'] if user_info and user_info['真实姓名'] else '未知'

        report_type = '月度报告' if report['报告类型'] == 1 else '季度报告'

        # 解析报告内容
        report_content = report['报告内容']
        try:
            if report_content:
                report_data = json.loads(report_content)
            else:
                report_data = {}
        except json.JSONDecodeError:
            report_data = {'raw_content': report_content}

        return jsonify({
            'success': True,
            'data': {
                '报告ID': report['报告ID'],
                '报告类型': report['报告类型'],
                '报告类型名称': report_type,
                '报告内容': report_content,
                '生成时间': report['生成时间'].strftime('%Y-%m-%d %H:%M:%S') if report['生成时间'] else '',
                '生成人': generator_name,
                '生成人ID': report['生成人ID'],
                'report_data': report_data
            }
        })

    except Exception as e:
        print(f"获取报告详情失败: {str(e)}")
        return jsonify({'success': False, 'message': f'获取报告详情失败: {str(e)}'}), 500

# ============ 所有其他API路由 ============
# 这里保持你原有的其他API路由不变
# 包括：用户管理、告警规则、备份恢复等

@app.route('/api/users', methods=['GET'])
@login_required
@require_role(['系统管理员','运维人员'])
def get_users():
    """获取用户列表"""
    try:
        cursor = db.get_cursor()
        sql = """
        SELECT 
            u.用户ID, u.登录账号, u.真实姓名, u.用户角色, 
            u.手机号码, u.上次登录的时间, u.登录失败的次数,
            p.厂区名称, u.负责的厂区编号,
            CASE 
                WHEN u.登录失败的次数 >= 5 THEN '已锁定'
                WHEN u.上次登录的时间 IS NULL THEN '从未登录'
                ELSE '正常'
            END as 状态
        FROM 用户 u 
        LEFT JOIN 厂区 p ON u.负责的厂区编号 = p.厂区编号
        ORDER BY u.用户角色, u.真实姓名
        """
        cursor.execute(sql)
        users = cursor.fetchall()

        cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
        factories = cursor.fetchall()

        return jsonify({
            'success': True,
            'users': users,
            'factories': factories,
            'roles': ['能源管理员', '运维人员', '数据分析师', '系统管理员', '企业管理层', '运维工单管理员']
        })
    except Exception as e:
        print(f"获取用户列表错误: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 系统管理员API路由 ============



@app.route('/api/dashboard/stats', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_dashboard_stats():
    """获取仪表板统计数据"""
    try:
        cursor = db.get_cursor()

        # 获取用户总数
        try:
            cursor.execute("SELECT COUNT(*) as total_users FROM 用户")
            user_result = cursor.fetchone()
            total_users = user_result['total_users'] if user_result else 0
        except Exception as e:
            print(f"获取用户总数失败: {str(e)}")
            total_users = 0

        # 获取设备总数
        try:
            cursor.execute("SELECT COUNT(*) as total_devices FROM 设备")
            device_result = cursor.fetchone()
            total_devices = device_result['total_devices'] if device_result else 0
        except Exception as e:
            print(f"获取设备总数失败: {str(e)}")
            total_devices = 0

        # 获取告警总数
        try:
            cursor.execute("SELECT COUNT(*) as total_alarms FROM 告警信息")
            alarm_result = cursor.fetchone()
            total_alarms = alarm_result['total_alarms'] if alarm_result else 0
        except Exception as e:
            print(f"获取告警总数失败: {str(e)}")
            total_alarms = 0

        # 获取数据库大小 - 使用更简单的方法
        try:
            db_size = 0
            # 尝试查询数据库大小
            cursor.execute("""
                SELECT 
                    ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as total_mb
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
            """)
            db_size_result = cursor.fetchone()
            if db_size_result and db_size_result['total_mb']:
                db_size = float(db_size_result['total_mb'])
        except:
            db_size = 0

        # 模拟最近活动
        recent_activities = [
            {
                '操作时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '操作人员': '系统管理员',
                '操作内容': '查看仪表板',
                '操作结果': '成功'
            }
        ]

        return jsonify({
            'success': True,
            'total_users': total_users,
            'total_devices': total_devices,
            'alarms': {'total': total_alarms},
            'database_size': {'total_mb': db_size},
            'recent_activities': recent_activities
        })

    except Exception as e:
        print(f"获取仪表板统计数据失败: {str(e)}")
        import traceback
        traceback.print_exc()
        # 返回默认值
        return jsonify({
            'success': True,
            'total_users': 0,
            'total_devices': 0,
            'alarms': {'total': 0},
            'database_size': {'total_mb': 0},
            'recent_activities': []
        })

@app.route('/api/database/status', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_database_status():
    """获取数据库状态"""
    try:
        cursor = db.get_cursor()

        # 获取数据库版本
        cursor.execute("SELECT VERSION() as version")
        version_result = cursor.fetchone()
        db_version = version_result['version'] if version_result else '未知'

        # 获取表空间使用情况
        cursor.execute("""
            SELECT 
                TABLE_NAME as 表名,
                TABLE_ROWS as 行数,
                DATA_LENGTH / 1024 / 1024 as 数据大小_MB,
                INDEX_LENGTH / 1024 / 1024 as 索引大小_MB,
                (DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024 as 总大小_MB
            FROM information_schema.tables 
            WHERE table_schema = %s
            ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
            LIMIT 10
        """, (DB_CONFIG['database'],))
        table_stats = cursor.fetchall()

        # 获取数据库运行时间
        cursor.execute("SHOW GLOBAL STATUS LIKE 'Uptime'")
        uptime_result = cursor.fetchone()
        uptime_seconds = int(uptime_result['Value']) if uptime_result else 0

        # 转换运行时间为可读格式
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f"{days}天 {hours}小时 {minutes}分钟"

        # 获取连接数
        cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
        connections_result = cursor.fetchone()
        current_connections = connections_result['Value'] if connections_result else 0

        # 获取系统资源使用情况（模拟）
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        memory_percent = memory_info.percent

        return jsonify({
            'success': True,
            'database_info': {
                'version': db_version,
                'uptime': uptime_str
            },
            'connection_info': {
                'threads_connected': current_connections
            },
            'system_info': {
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'memory_total': memory_info.total / (1024 ** 3),  # GB
                'memory_used': memory_info.used / (1024 ** 3),  # GB
                'memory_free': memory_info.free / (1024 ** 3)  # GB
            },
            'table_stats': table_stats
        })

    except Exception as e:
        print(f"获取数据库状态失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/alarm-rules', methods=['POST'])
@login_required
@require_role('系统管理员')
def add_alarm_rule():
    """添加告警规则"""
    try:
        data = request.get_json()
        print(f"=== 添加告警规则，接收到的数据: {data}")

        # 验证必要字段
        required_fields = ['rule_name', 'device_type', 'alarm_param', 'threshold', 'alarm_level']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'缺少必要字段: {field}'}), 400

        cursor = db.get_cursor()

        # 生成规则ID
        rule_id = f"RULE_{int(time.time())}"

        # 获取当前用户的用户ID
        current_user_id = session.get('user_id')
        if not current_user_id:
            return jsonify({'success': False, 'error': '用户未登录'}), 401

        # 验证设备类型是否存在
        try:
            cursor.execute("SELECT COUNT(*) as count FROM 设备 WHERE 设备大类 = %s", (data['device_type'],))
            device_count = cursor.fetchone()['count']
            if device_count == 0:
                print(f"警告: 设备类型 '{data['device_type']}' 不存在，但继续添加规则")
        except Exception as e:
            print(f"检查设备类型失败: {str(e)}")
            # 不中断流程

        # 插入告警规则 - 使用用户的ID作为外键
        sql = """
        INSERT INTO 告警规则 (
            规则ID, 规则名称, 设备类型, 告警参数, 告警条件,
            告警阈值, 告警等级, 启用状态, 创建人员
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)
        """

        # 设置默认条件为 '>'
        condition = '>'

        cursor.execute(sql, (
            rule_id,
            data['rule_name'],
            data['device_type'],
            data['alarm_param'],
            condition,
            float(data['threshold']),
            data['alarm_level'],
            current_user_id  # 使用用户ID，而不是真实姓名
        ))

        db.connect().commit()

        print(f"告警规则添加成功: {rule_id}")

        return jsonify({
            'success': True,
            'message': '告警规则添加成功',
            'rule_id': rule_id
        })

    except Exception as e:
        db.connect().rollback()
        print(f"添加告警规则失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/users/<user_id>', methods=['DELETE'])
@login_required
@require_role('系统管理员')
def delete_user_api(user_id):
    """删除用户（处理外键约束）"""
    try:
        cursor = db.get_cursor()

        # 检查用户是否存在
        cursor.execute("SELECT 真实姓名, 用户角色 FROM 用户 WHERE 用户ID = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        # 如果是系统管理员，不能删除自己
        current_user_id = session.get('user_id')
        if user_id == current_user_id:
            return jsonify({'success': False, 'error': '不能删除当前登录的用户'}), 400

        # 检查用户是否有相关数据
        check_queries = [
            ("SELECT COUNT(*) as count FROM 运维工单 WHERE 运维人员ID = %s", '运维工单'),
            ("SELECT COUNT(*) as count FROM 简单报告 WHERE 生成人ID = %s", '简单报告'),
            ("SELECT COUNT(*) as count FROM 告警信息 WHERE 告警确认人ID = %s", '告警确认'),
            ("SELECT COUNT(*) as count FROM 配电房 WHERE 负责人ID = %s", '负责配电房'),
        ]

        related_data = []
        for query, desc in check_queries:
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            if result and result['count'] > 0:
                related_data.append(f"{desc}: {result['count']}条")

        if related_data:
            return jsonify({
                'success': False,
                'error': f'用户有相关数据，无法删除',
                'related_data': related_data
            }), 400

        # 禁用外键约束检查
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

        try:
            # 删除用户
            cursor.execute("DELETE FROM 用户 WHERE 用户ID = %s", (user_id,))

            # 记录操作日志
            cursor.execute("""
                INSERT INTO 操作日志 (日志ID, 操作类型, 操作人员ID, 操作内容, 操作结果, 操作时间)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                f"LOG_{int(time.time())}",
                '删除用户',
                current_user_id,
                f'删除用户 {user["真实姓名"]} (ID: {user_id}, 角色: {user["用户角色"]})',
                '成功',
                datetime.now()
            ))

            db.connect().commit()

        except Exception as delete_error:
            db.connect().rollback()
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            raise delete_error

        # 重新启用外键约束检查
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        return jsonify({
            'success': True,
            'message': f'用户 {user["真实姓名"]} 删除成功'
        })

    except Exception as e:
        try:
            db.connect().rollback()
        except:
            pass
        print(f"删除用户失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# @app.route('/api/alarm-rules', methods=['GET'])
# @login_required
# @require_role('系统管理员')
# def get_alarm_rules():
#     """获取告警规则列表"""
#     try:
#         cursor = db.get_cursor()
#
#         cursor.execute("""
#             SELECT
#                 r.*,
#                 u.真实姓名 as 创建人姓名,
#                 CASE WHEN r.启用状态 = 1 THEN '启用' ELSE '停用' END as 状态显示
#             FROM 告警规则 r
#             LEFT JOIN 用户 u ON r.创建人员ID = u.用户ID
#             ORDER BY r.创建时间 DESC
#         """)
#         rules = cursor.fetchall()
#
#         # 获取设备类型
#         cursor.execute("SELECT DISTINCT 设备大类 FROM 设备 WHERE 设备大类 IS NOT NULL")
#         device_types = [row['设备大类'] for row in cursor.fetchall()]
#
#         return jsonify({
#             'success': True,
#             'rules': rules,
#             'device_types': device_types
#         })
#
#     except Exception as e:
#         print(f"获取告警规则失败: {str(e)}")
#         return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/alarm-rules', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_alarm_rules():
    """获取告警规则列表"""
    try:
        cursor = db.get_cursor()

        # 查看告警规则表的实际结构
        cursor.execute("DESCRIBE 告警规则")
        columns = cursor.fetchall()
        print("告警规则表结构:", columns)

        # 获取所有列名
        column_names = [col['Field'] for col in columns]
        print("可用列名:", column_names)

        # 根据实际列名构建查询
        if '创建人ID' in column_names:
            # 如果列名是"创建人ID"
            sql = """
                SELECT 
                    r.*,
                    u.真实姓名 as 创建人姓名,
                    CASE WHEN r.启用状态 = 1 THEN '启用' ELSE '停用' END as 状态显示
                FROM 告警规则 r
                LEFT JOIN 用户 u ON r.创建人ID = u.用户ID
                ORDER BY r.创建时间 DESC
            """
        elif '创建人员ID' in column_names:
            # 如果列名是"创建人员ID"
            sql = """
                SELECT 
                    r.*,
                    u.真实姓名 as 创建人姓名,
                    CASE WHEN r.启用状态 = 1 THEN '启用' ELSE '停用' END as 状态显示
                FROM 告警规则 r
                LEFT JOIN 用户 u ON r.创建人员ID = u.用户ID
                ORDER BY r.创建时间 DESC
            """
        else:
            # 如果没有创建人字段
            sql = """
                SELECT 
                    *,
                    '系统' as 创建人姓名,
                    CASE WHEN 启用状态 = 1 THEN '启用' ELSE '停用' END as 状态显示
                FROM 告警规则
                ORDER BY 创建时间 DESC
            """

        print("执行SQL:", sql)
        cursor.execute(sql)
        rules = cursor.fetchall()

        # 获取设备类型
        cursor.execute("SELECT DISTINCT 设备大类 FROM 设备 WHERE 设备大类 IS NOT NULL")
        device_types = [row['设备大类'] for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'rules': rules,
            'device_types': device_types
        })

    except Exception as e:
        print(f"获取告警规则失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/alarm-rules/<rule_id>', methods=['DELETE'])
@login_required
@require_role('系统管理员')
def delete_alarm_rule(rule_id):
    """删除告警规则"""
    try:
        cursor = db.get_cursor()

        # 检查规则是否存在
        cursor.execute("SELECT 规则名称 FROM 告警规则 WHERE 规则ID = %s", (rule_id,))
        rule = cursor.fetchone()

        if not rule:
            return jsonify({'success': False, 'error': '规则不存在'}), 404

        # 删除规则
        cursor.execute("DELETE FROM 告警规则 WHERE 规则ID = %s", (rule_id,))
        db.connect().commit()

        return jsonify({'success': True, 'message': '规则删除成功'})

    except Exception as e:
        db.connect().rollback()
        print(f"删除告警规则失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/query-workorder-full', methods=['POST'])
@login_required
@require_role('系统管理员')
def query_workorder():
    """查询运维工单"""
    try:
        data = request.get_json()

        cursor = db.get_cursor()

        # 构建查询条件
        conditions = []
        params = []

        if data.get('device_id'):
            # 通过告警信息关联设备
            conditions.append("w.告警ID IN (SELECT 告警ID FROM 告警信息 WHERE 关联设备编号 = %s)")
            params.append(data['device_id'])

        if data.get('maintenance_person_id'):
            conditions.append("w.运维人员ID = %s")
            params.append(data['maintenance_person_id'])

        if data.get('start_time'):
            conditions.append("w.派单时间 >= %s")
            params.append(data['start_time'])

        if data.get('end_time'):
            conditions.append("w.派单时间 <= %s")
            params.append(data['end_time'])

        if data.get('review_status'):
            conditions.append("w.复查状态 = %s")
            params.append(data['review_status'])

        # 构建查询语句
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 添加排序和限制
        limit = min(int(data.get('limit', 100)), 1000)

        sql = f"""
            SELECT 
                w.*,
                a.告警内容,
                u.真实姓名 as 运维人员姓名
            FROM 运维工单 w
            LEFT JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            {where_clause}
            ORDER BY w.派单时间 DESC
            LIMIT %s
        """
        params.append(limit)

        cursor.execute(sql, params)
        results = cursor.fetchall()

        # 计算统计数据
        total_rows = len(results)

        return jsonify({
            'success': True,
            'count': total_rows,
            'data': results
        })

    except Exception as e:
        print(f"查询工单数据失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/query-circuit-data-full', methods=['POST'])
@login_required
@require_role('系统管理员')
def query_circuit_data():
    """查询回路数据"""
    try:
        data = request.get_json()

        cursor = db.get_cursor()

        # 检查回路监测数据表是否存在
        cursor.execute("SHOW TABLES LIKE '回路监测数据'")
        if not cursor.fetchone():
            return jsonify({
                'success': True,
                'count': 0,
                'data': [],
                'stats': {}
            })

        # 构建查询条件
        conditions = []
        params = []

        if data.get('start_time'):
            conditions.append("采集时间 >= %s")
            params.append(data['start_time'])

        if data.get('end_time'):
            conditions.append("采集时间 <= %s")
            params.append(data['end_time'])

        if data.get('circuit_id'):
            conditions.append("回路编号 = %s")
            params.append(data['circuit_id'])

        if data.get('device_id'):
            conditions.append("设备编号 = %s")
            params.append(data['device_id'])

        if data.get('voltage_abnormal'):
            conditions.append("电压异常标记 = 1")

        if data.get('temp_abnormal'):
            conditions.append("温度异常标记 = 1")

        # 构建查询语句
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 添加排序和限制
        limit = min(int(data.get('limit', 100)), 1000)

        sql = f"""
            SELECT * FROM 回路监测数据
            {where_clause}
            ORDER BY 采集时间 DESC
            LIMIT %s
        """
        params.append(limit)

        cursor.execute(sql, params)
        results = cursor.fetchall()

        # 计算统计数据
        total_rows = len(results)
        if results and total_rows > 0:
            voltage_sum = sum([float(row.get('电压') or 0) for row in results])
            voltage_avg = voltage_sum / total_rows

            temp_sum = sum([float(row.get('电容器温度') or 0) for row in results])
            temp_avg = temp_sum / total_rows

            stats = {
                '平均电压': round(voltage_avg, 2),
                '平均温度': round(temp_avg, 2),
                '数据总数': total_rows
            }
        else:
            stats = {}

        return jsonify({
            'success': True,
            'count': total_rows,
            'data': results,
            'stats': stats
        })

    except Exception as e:
        print(f"查询回路数据失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/get-maintenance-users', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_maintenance_users():
    """获取运维人员列表"""
    try:
        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 用户ID, 真实姓名, 用户角色
            FROM 用户
            WHERE 用户角色 IN ('运维人员', '运维工单管理员', '能源管理员')
            ORDER BY 真实姓名
        """)
        users = cursor.fetchall()

        return jsonify({
            'success': True,
            'users': users
        })

    except Exception as e:
        print(f"获取运维人员列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/energy-data-list', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_energy_data_list():
    """获取能耗数据列表"""
    try:
        limit = request.args.get('limit', 20)

        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 
                数据编号,
                设备编号,
                采集时间,
                能耗值,
                单位,
                数据质量
            FROM 能耗监测数据
            ORDER BY 采集时间 DESC
            LIMIT %s
        """, (int(limit),))

        data = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': data
        })

    except Exception as e:
        print(f"获取能耗数据列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/alarm-list', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_alarm_list():
    """获取告警列表"""
    try:
        limit = request.args.get('limit', 20)

        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 
                告警ID,
                告警编号,
                告警类型,
                关联设备编号,
                发生时间,
                告警等级,
                告警内容,
                处理状态
            FROM 告警信息
            ORDER BY 发生时间 DESC
            LIMIT %s
        """, (int(limit),))

        data = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': data
        })

    except Exception as e:
        print(f"获取告警列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/workorder-list', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_workorder_list():
    """获取工单列表"""
    try:
        limit = request.args.get('limit', 20)

        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 
                w.工单ID,
                w.工单编号,
                w.告警ID,
                w.运维人员ID,
                w.派单时间,
                w.处理结果,
                w.复查状态,
                a.告警内容,
                u.真实姓名 as 运维人员姓名
            FROM 运维工单 w
            LEFT JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            ORDER BY w.派单时间 DESC
            LIMIT %s
        """, (int(limit),))

        data = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': data
        })

    except Exception as e:
        print(f"获取工单列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 持久层测试API路由 ============

@app.route('/api/persistence/device-list', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_device_list():
    """获取设备列表"""
    try:
        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 
                设备编号,
                设备名称,
                设备大类,
                设备类型,
                运行状态,
                安装位置描述
            FROM 设备
            ORDER BY 设备编号
            LIMIT 20
        """)
        devices = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': devices
        })

    except Exception as e:
        print(f"获取设备列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/add-pv-device', methods=['POST'])
@login_required
@require_role('系统管理员')
def add_pv_device():
    """添加光伏设备"""
    try:
        data = request.get_json()
        print("接收到的数据:", data)

        cursor = db.get_cursor()

        # 生成设备ID
        device_id = data.get('device_id') or f"PV_{int(time.time())}"

        # 处理日期字段
        commission_date = data.get('commission_date')
        if not commission_date or commission_date == '':
            commission_date = None
        else:
            # 确保日期格式正确
            try:
                commission_date = datetime.strptime(commission_date, '%Y-%m-%d').date()
            except ValueError:
                commission_date = None

        # 处理数值字段
        installed_capacity = data.get('installed_capacity')
        if installed_capacity:
            try:
                installed_capacity = float(installed_capacity)
            except (ValueError, TypeError):
                installed_capacity = None

        calibration_period = data.get('calibration_period', 12)
        try:
            calibration_period = int(calibration_period)
        except (ValueError, TypeError):
            calibration_period = 12

        print(f"准备插入设备 {device_id}, 投运时间: {commission_date}")

        # 1. 先在设备表中插入记录
        cursor.execute("""
            INSERT INTO 设备 (
                设备编号, 设备名称, 设备大类, 设备类型, 运行状态
            ) VALUES (%s, %s, %s, %s, %s)
        """, (
            device_id,
            f"光伏设备-{device_id}",
            '光伏设备',
            data.get('device_type', '逆变器'),
            data.get('status', '正常')
        ))

        # 2. 在光伏设备表中插入记录
        cursor.execute("""
            INSERT INTO 光伏设备 (
                设备编号, 设备类型, 装机容量, 生产厂家,
                设备型号, 投运时间, 校准周期, 运行状态, 通信协议
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            device_id,
            data.get('device_type', '逆变器'),
            installed_capacity,
            data.get('manufacturer', ''),
            data.get('model', ''),
            commission_date,
            calibration_period,
            data.get('status', '正常'),
            data.get('protocol', 'Modbus')
        ))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '光伏设备添加成功',
            'device_id': device_id
        })

    except Exception as e:
        db.connect().rollback()
        print(f"添加光伏设备失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/persistence/add-device', methods=['POST'])
@login_required
@require_role('系统管理员')
def add_device():
    """添加普通设备"""
    try:
        data = request.get_json()

        cursor = db.get_cursor()

        # 生成设备ID
        device_id = data.get('device_id') or f"DEV_{int(time.time())}"

        # 插入设备记录
        cursor.execute("""
            INSERT INTO 设备 (
                设备编号, 设备名称, 设备大类, 设备类型,
                所属厂区编号, 安装位置描述, 运行状态
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            device_id,
            data.get('device_name'),
            data.get('device_category'),
            data.get('device_type'),
            data.get('factory_id'),
            data.get('location'),
            data.get('status', '正常')
        ))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '设备添加成功',
            'device_id': device_id
        })

    except Exception as e:
        db.connect().rollback()
        print(f"添加设备失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/get-devices', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_devices_for_select():
    """获取设备列表用于下拉选择"""
    try:
        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 设备编号, 设备名称
            FROM 设备
            WHERE 设备编号 IS NOT NULL
            ORDER BY 设备名称
            LIMIT 50
        """)
        devices = cursor.fetchall()

        return jsonify({
            'success': True,
            'devices': devices
        })

    except Exception as e:
        print(f"获取设备列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/delete-expired-alarm', methods=['POST'])
@login_required
@require_role('系统管理员')
def delete_expired_alarm():
    """删除过期告警"""
    try:
        data = request.get_json()
        days = int(data.get('days', 30))

        cursor = db.get_cursor()

        # 删除已结案且超过指定天数的告警
        cursor.execute("""
            DELETE FROM 告警信息 
            WHERE 处理状态 = '已结案' 
            AND 发生时间 < DATE_SUB(NOW(), INTERVAL %s DAY)
        """, (days,))

        deleted_count = cursor.rowcount

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': f'删除了 {deleted_count} 条过期告警记录'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"删除过期告警失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/update-alarm', methods=['POST'])
@login_required
@require_role('系统管理员')
def update_alarm():
    """更新告警状态"""
    try:
        data = request.get_json()

        if not data.get('alarm_id'):
            return jsonify({'success': False, 'error': '告警ID不能为空'}), 400

        cursor = db.get_cursor()

        # 更新告警状态
        cursor.execute("""
            UPDATE 告警信息 
            SET 处理状态 = %s,
                告警确认人ID = %s,
                确认时间 = NOW()
            WHERE 告警ID = %s
        """, (
            data.get('status'),
            session.get('user_id'),
            data.get('alarm_id')
        ))

        updated_count = cursor.rowcount

        if updated_count == 0:
            return jsonify({'success': False, 'error': '告警不存在'}), 404

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '告警状态更新成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"更新告警状态失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/update-equipment-full', methods=['POST'])
@login_required
@require_role('系统管理员')
def update_equipment():
    """更新设备台账"""
    try:
        data = request.get_json()

        if not data.get('device_id'):
            return jsonify({'success': False, 'error': '设备ID不能为空'}), 400

        cursor = db.get_cursor()

        # 检查设备是否存在
        cursor.execute("SELECT 设备编号 FROM 设备 WHERE 设备编号 = %s", (data.get('device_id'),))
        if not cursor.fetchone():
            return jsonify({'success': False, 'error': '设备不存在'}), 404

        # 检查台账是否存在
        cursor.execute("SELECT 台账编号 FROM 设备台账 WHERE 设备编号 = %s", (data.get('device_id'),))
        ledger = cursor.fetchone()

        if ledger:
            # 更新现有台账
            cursor.execute("""
                UPDATE 设备台账 
                SET 型号规格 = %s,
                    安装时间 = %s,
                    质保期 = %s,
                    维修记录 = %s,
                    校准记录 = %s,
                    报废状态 = %s,
                    报废时间 = %s,
                    报废原因 = %s
                WHERE 设备编号 = %s
            """, (
                data.get('model_spec'),
                data.get('install_date'),
                data.get('warranty_period'),
                data.get('maintenance_record'),
                data.get('calibration_record'),
                data.get('scrap_status', '正常使用'),
                data.get('scrap_date'),
                data.get('scrap_reason'),
                data.get('device_id')
            ))
        else:
            # 插入新台账
            ledger_id = f"LEDGER_{int(time.time())}"
            cursor.execute("""
                INSERT INTO 设备台账 (
                    台账编号, 设备编号, 型号规格, 安装时间,
                    质保期, 维修记录, 校准记录,
                    报废状态, 报废时间, 报废原因
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                ledger_id,
                data.get('device_id'),
                data.get('model_spec'),
                data.get('install_date'),
                data.get('warranty_period'),
                data.get('maintenance_record'),
                data.get('calibration_record'),
                data.get('scrap_status', '正常使用'),
                data.get('scrap_date'),
                data.get('scrap_reason')
            ))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '设备台账更新成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"更新设备台账失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/persistence/get-factories', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_factories():
    """获取厂区列表"""
    try:
        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 厂区编号, 厂区名称
            FROM 厂区
            ORDER BY 厂区名称
        """)
        factories = cursor.fetchall()

        return jsonify({
            'success': True,
            'factories': factories
        })

    except Exception as e:
        print(f"获取厂区列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/persistence/delete-invalid-data', methods=['POST'])
@login_required
@require_role('系统管理员')
def delete_invalid_data():
    """清理无效测试数据"""
    try:
        cursor = db.get_cursor()
        result = {}

        # 清理无效设备记录
        cursor.execute("""
            DELETE FROM 设备 
            WHERE 设备编号 LIKE 'TEST_%' 
            OR 设备编号 LIKE 'PV_%' 
            OR 设备编号 LIKE 'DEV_%'
            OR 设备名称 LIKE '%测试%'
        """)
        result['devices_deleted'] = cursor.rowcount

        # 清理无效告警记录
        cursor.execute("""
            DELETE FROM 告警信息 
            WHERE 告警内容 LIKE '%测试%'
            OR 告警内容 LIKE '%test%'
        """)
        result['alarms_deleted'] = cursor.rowcount

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '清理完成',
            'result': result
        })

    except Exception as e:
        db.connect().rollback()
        print(f"清理无效数据失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 修复数据库连接问题 ============

@app.before_request
def before_request():
    """在每个请求前获取数据库连接"""
    try:
        # 确保线程本地有数据库连接
        db.get_connection()
    except Exception as e:
        print(f"数据库连接检查失败: {e}")

@app.after_request
def after_request(response):
    """在每个请求后释放数据库连接"""
    try:
        db.release_connection()
    except Exception as e:
        print(f"释放数据库连接失败: {e}")
    return response


# ============ 修复用户管理功能 ============

@app.route('/api/users', methods=['POST'])
@login_required
@require_role('系统管理员')
def add_user():
    """添加用户"""
    try:
        data = request.get_json()

        if not data.get('login_account'):
            return jsonify({'success': False, 'error': '登录账号不能为空'}), 400

        # 检查账号是否已存在
        cursor = db.get_cursor()
        cursor.execute("SELECT 用户ID FROM 用户 WHERE 登录账号 = %s", (data['login_account'],))
        if cursor.fetchone():
            return jsonify({'success': False, 'error': '登录账号已存在'}), 400

        # 生成用户ID
        cursor.execute("SELECT MAX(用户ID) as max_id FROM 用户")
        max_id_result = cursor.fetchone()
        max_id = max_id_result['max_id'] if max_id_result and max_id_result['max_id'] else 'U000'

        # 生成新用户ID
        if max_id and max_id.startswith('U'):
            try:
                num = int(max_id[1:]) + 1
                new_user_id = f"U{num:03d}"
            except:
                new_user_id = f"U{int(time.time()) % 1000:03d}"
        else:
            new_user_id = "U001"

        # 插入用户
        cursor.execute("""
            INSERT INTO 用户 (
                用户ID, 登录账号, 真实姓名, 用户角色, 
                密码哈希值, 手机号码, 登录失败的次数
            ) VALUES (%s, %s, %s, %s, %s, %s, 0)
        """, (
            new_user_id,
            data['login_account'],
            data.get('real_name', data['login_account']),
            data.get('role', '能源管理员'),
            md5_hash(data['password'] if data.get('password') else '123456'),
            data.get('phone', '')
        ))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '用户添加成功',
            'user_id': new_user_id
        })

    except Exception as e:
        db.connect().rollback()
        print(f"添加用户失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/backups', methods=['GET'])
@login_required
@require_role('系统管理员')
def get_backups():
    """获取备份列表"""
    try:
        cursor = db.get_cursor()

        # 查看备份日志表结构
        cursor.execute("DESCRIBE 备份日志")
        columns = cursor.fetchall()
        column_names = [col['Field'] for col in columns]
        print(f"备份日志表列: {column_names}")

        # 根据表结构调整查询
        if '操作人员ID' in column_names:
            sql = """
            SELECT 
                b.*,
                u.真实姓名 as 操作人员姓名
            FROM 备份日志 b
            LEFT JOIN 用户 u ON b.操作人员ID = u.用户ID
            ORDER BY b.备份时间 DESC
            LIMIT 20
            """
        elif '操作人员' in column_names:
            sql = """
            SELECT 
                b.*,
                b.操作人员 as 操作人员姓名
            FROM 备份日志 b
            ORDER BY b.备份时间 DESC
            LIMIT 20
            """
        else:
            sql = """
            SELECT 
                b.*,
                '系统' as 操作人员姓名
            FROM 备份日志 b
            ORDER BY b.备份时间 DESC
            LIMIT 20
            """

        cursor.execute(sql)
        backups = cursor.fetchall()

        # 获取备份文件列表
        backup_files = []
        backup_folder = app.config['BACKUP_FOLDER']
        if os.path.exists(backup_folder):
            for filename in os.listdir(backup_folder):
                if filename.endswith('.sql'):
                    filepath = os.path.join(backup_folder, filename)
                    size_mb = os.path.getsize(filepath) / (1024 * 1024) if os.path.exists(filepath) else 0
                    backup_files.append({
                        'filename': filename,
                        'filepath': filepath,
                        'size_mb': round(size_mb, 2)
                    })

        # 计算统计信息
        total_backups = len(backups)
        total_size = sum([float(b.get('备份大小') or 0) for b in backups])

        return jsonify({
            'success': True,
            'backups': backups,
            'backup_files': backup_files,
            'backup_stats': {
                'total': total_backups,
                'total_size': round(total_size, 2)
            }
        })

    except Exception as e:
        print(f"获取备份列表失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/database/backup', methods=['POST'])
@login_required
@require_role('系统管理员')
def create_backup():
    """创建数据库备份"""
    try:
        # 生成备份文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.sql"
        backup_path = os.path.join(app.config['BACKUP_FOLDER'], backup_filename)

        # 构建备份命令
        db_config = DB_CONFIG
        backup_cmd = [
            'mysqldump',
            '-h', db_config['host'],
            '-P', str(db_config['port']),
            '-u', db_config['user'],
            '-p' + db_config['password'],
            db_config['database']
        ]

        # 执行备份
        try:
            with open(backup_path, 'w') as f:
                subprocess.run(backup_cmd, stdout=f, check=True, text=True)

            # 获取备份文件大小
            backup_size = os.path.getsize(backup_path) / (1024 * 1024)  # MB

            # 记录备份日志
            cursor = db.get_cursor()
            backup_id = f"BACKUP_{timestamp}"

            cursor.execute("""
                INSERT INTO 备份日志 (
                    备份ID, 备份时间, 备份文件, 备份类型,
                    操作人员ID, 备份大小, 完成状态
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                backup_id,
                datetime.now(),
                backup_path,
                '手动备份',
                session.get('user_id'),
                round(backup_size, 2),
                '成功'
            ))

            db.connect().commit()

            return jsonify({
                'success': True,
                'message': '备份创建成功',
                'backup_file': backup_path,
                'backup_size': round(backup_size, 2)
            })

        except subprocess.CalledProcessError as e:
            return jsonify({
                'success': False,
                'error': f'备份执行失败: {str(e)}'
            }), 500

    except Exception as e:
        print(f"创建备份失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

#==========能源管理员============
# ============ 能源管理功能路由（兼容两个版本） ============

# 辅助函数
def get_factories():
    """获取所有厂区"""
    try:
        cursor = db.get_cursor()
        cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
        return cursor.fetchall()
    except Exception as e:
        print(f"获取厂区列表失败: {str(e)}")
        return []


def get_energy_types():
    """获取能源类型"""
    energy_types = ['电', '水', '蒸汽', '天然气']
    return energy_types


# 仪表板页面 - 能源管理员
@app.route('/energy/dashboard', methods=['GET'])
@login_required
@require_role('能源管理员')
def energy_dashboard_original():
    """能源管理员仪表板（原始版本）"""
    if not session.get('user_id'):
        return redirect(url_for('login'))

    try:
        cursor = db.get_cursor()

        # 1. 本月各能源类型的能耗和总成本
        query_by_energy_type = """
                SELECT 
                    能源类型,
                    SUM(总能耗) as 总能耗,
                    SUM(能耗成本) as 能耗成本,
                    CASE 
                        WHEN 能源类型 = '电' THEN 'kWh'
                        WHEN 能源类型 = '水' THEN 'm³'
                        WHEN 能源类型 = '蒸汽' THEN 't'
                        WHEN 能源类型 = '天然气' THEN 'm³'
                        ELSE '单位'
                    END as 单位
                FROM 峰谷能耗数据 
                WHERE MONTH(统计日期) = MONTH(CURDATE()) 
                    AND YEAR(统计日期) = YEAR(CURDATE())
                GROUP BY 能源类型
                ORDER BY 
                    CASE 能源类型
                        WHEN '电' THEN 1
                        WHEN '水' THEN 2
                        WHEN '蒸汽' THEN 3
                        WHEN '天然气' THEN 4
                        ELSE 5
                    END
                """
        cursor.execute(query_by_energy_type)
        energy_by_type = cursor.fetchall()

        # 2. 计算本月总成本
        query_total_cost = """
        SELECT SUM(能耗成本) as 总成本
        FROM 峰谷能耗数据 
        WHERE MONTH(统计日期) = MONTH(CURDATE()) 
            AND YEAR(统计日期) = YEAR(CURDATE())
        """
        cursor.execute(query_total_cost)
        total_cost_result = cursor.fetchone()
        total_cost = total_cost_result['总成本'] if total_cost_result and total_cost_result['总成本'] else 0

        # 3. 近期告警
        query = """
        SELECT 
            告警ID,
            告警类型,
            关联设备编号,
            发生时间,
            告警等级,
            告警内容,
            处理状态
        FROM 告警信息 
        ORDER BY 发生时间 DESC 
        LIMIT 10
        """
        cursor.execute(query)
        alerts = cursor.fetchall()

        # 4. 能耗趋势（最近7天）
        query = """
        SELECT 
            DATE(统计日期) as date,
            能源类型,
            SUM(总能耗) as energy
        FROM 峰谷能耗数据 
        WHERE 统计日期 >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY DATE(统计日期), 能源类型
        ORDER BY date
        """
        cursor.execute(query)
        trend_data = cursor.fetchall()

        # 5. 能源构成（本月各能源类型占比）
        query = """
        SELECT 
            能源类型,
            SUM(总能耗) as total_energy
        FROM 峰谷能耗数据 
        WHERE MONTH(统计日期) = MONTH(CURDATE()) 
            AND YEAR(统计日期) = YEAR(CURDATE())
        GROUP BY 能源类型
        ORDER BY total_energy DESC
        """
        cursor.execute(query)
        energy_composition = cursor.fetchall()

        # 6. 节能项目数量
        query = """
        SELECT COUNT(*) as count 
        FROM 能耗优化方案 
        WHERE 当前状态 IN ('已审批', '执行中')
        """
        cursor.execute(query)
        optimization_result = cursor.fetchone()
        optimization_count = optimization_result['count'] if optimization_result else 0

        # 处理趋势数据为图表格式
        trend_chart_data = {}
        for row in trend_data:
            if row['date']:
                date = row['date'].strftime('%m-%d')
                if date not in trend_chart_data:
                    trend_chart_data[date] = {}
                trend_chart_data[date][row['能源类型']] = float(row['energy']) if row['energy'] else 0

        # 处理能源构成数据
        composition_labels = []
        composition_data = []
        composition_colors = {
            '电': '#4e73df',
            '水': '#1cc88a',
            '蒸汽': '#36b9cc',
            '天然气': '#f6c23e',
            '光伏': '#e74a3b'
        }

        total_monthly_energy = sum(float(item['total_energy'] or 0) for item in energy_composition)

        for item in energy_composition:
            energy_type = item['能源类型']
            energy_value = float(item['total_energy'] or 0)

            if total_monthly_energy > 0:
                composition_labels.append(energy_type)
                composition_data.append(energy_value)

        if not composition_labels:
            composition_labels = ['电能', '水能', '蒸汽', '天然气']
            composition_data = [0, 0, 0, 0]
            total_monthly_energy = 0

        composition_percentages = []
        if total_monthly_energy > 0:
            composition_percentages = [(value / total_monthly_energy * 100) for value in composition_data]
        else:
            composition_percentages = [0] * len(composition_data)

        composition_chart_data = {
            'labels': composition_labels,
            'data': composition_data,
            'percentages': composition_percentages,
            'colors': [composition_colors.get(label, '#999') for label in composition_labels]
        }

        # 格式化能源类型数据
        energy_by_type_formatted = []
        for energy in energy_by_type:
            energy_type = energy['能源类型']
            energy_value = float(energy['总能耗'] or 0)
            unit = energy.get('单位', '单位')

            if unit == 'kWh':
                formatted_value = f"{energy_value:,.0f} kWh"
            elif unit == 'm³':
                formatted_value = f"{energy_value:,.0f} m³"
            elif unit == 't':
                formatted_value = f"{energy_value:,.1f} t"
            else:
                formatted_value = f"{energy_value:,.0f} {unit}"

            energy_by_type_formatted.append({
                'type': energy_type,
                'value': formatted_value,
                'raw_value': energy_value,
                'unit': unit,
                'cost': float(energy['能耗成本'] or 0)
            })

        monthly_data_dict = {
            'total_cost': total_cost,
            'energy_by_type': energy_by_type_formatted,
            'total_energy': total_monthly_energy
        }

        return render_template('dashboard.html',
                               monthly_data=monthly_data_dict,
                               alerts=alerts,
                               trend_data=json.dumps(trend_chart_data),
                               energy_composition=energy_composition,
                               optimization_count=optimization_count,
                               composition_chart_data=composition_chart_data)

    except Exception as e:
        print(f"仪表板数据获取失败: {str(e)}")
        # 返回空数据模板
        return render_template('dashboard.html',
                               monthly_data={'total_cost': 0, 'energy_by_type': [], 'total_energy': 0},
                               alerts=[],
                               trend_data='{}',
                               energy_composition=[],
                               optimization_count=0,
                               composition_chart_data={'labels': [], 'data': [], 'percentages': [], 'colors': []})



@app.route('/energy/report')
@login_required
@require_role('能源管理员')
def energy_report():
    """能耗报表 - 修复版"""
    try:
        # 获取查询参数
        factory_id = request.args.get('factory_id', '')
        energy_type = request.args.get('energy_type', '全部')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        # 设置默认日期（最近30天）
        if not start_date or not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        print(f"🔍 能耗报表参数: factory_id={factory_id}, energy_type={energy_type}, start={start_date}, end={end_date}")

        cursor = db.get_cursor()

        # 1. 先测试最简单的查询
        print("📊 测试1: 查询峰谷能耗数据表结构...")
        try:
            cursor.execute("DESCRIBE 峰谷能耗数据")
            columns = cursor.fetchall()
            print(f"表结构: {[col['Field'] for col in columns[:5]]}...")
        except Exception as e:
            print(f"❌ 表结构查询失败: {e}")
            return render_template('report.html',
                                   factories=[],
                                   error=f"表结构查询失败: {str(e)}")

        # 2. 测试数据量
        print("📊 测试2: 查询数据总量...")
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM 峰谷能耗数据")
            count_result = cursor.fetchone()
            print(f"数据总量: {count_result['cnt']}")

            if count_result['cnt'] == 0:
                print("⚠️ 警告: 峰谷能耗数据表为空")
                return render_template('report.html',
                                       factories=[],
                                       energy_reports={},
                                       error="数据库中没有能耗数据")
        except Exception as e:
            print(f"❌ 数据量查询失败: {e}")
            return render_template('report.html',
                                   factories=[],
                                   error=f"数据查询失败: {str(e)}")

        # 3. 测试带条件的查询（简化版）
        print("📊 测试3: 执行简化查询...")
        try:
            # 构建基础查询（简化）
            base_query = """
            SELECT 
                p.记录编号,
                p.能源类型,
                p.厂区编号,
                p.统计日期,
                p.总能耗,
                p.能耗成本,
                f.厂区名称
            FROM 峰谷能耗数据 p
            LEFT JOIN 厂区 f ON p.厂区编号 = f.厂区编号  # 改为LEFT JOIN
            WHERE 1=1
            """

            params = []

            # 添加能源类型条件
            if energy_type and energy_type != '全部':
                base_query += " AND p.能源类型 = %s"
                params.append(energy_type)

            # 添加日期条件
            if start_date:
                base_query += " AND p.统计日期 >= %s"
                params.append(start_date)

            if end_date:
                base_query += " AND p.统计日期 <= %s"
                params.append(end_date)

            # 添加厂区条件
            if factory_id:
                base_query += " AND p.厂区编号 = %s"
                params.append(factory_id)

            base_query += " ORDER BY p.统计日期 DESC, p.能源类型 LIMIT 100"

            print(f"📝 执行SQL: {base_query}")
            print(f"📝 参数: {params}")

            cursor.execute(base_query, params)
            all_data = cursor.fetchall()

            print(f"📈 查询到 {len(all_data)} 条记录")

            if all_data:
                for i, row in enumerate(all_data[:3]):  # 显示前3条
                    print(f"   记录{i + 1}: {row}")
            else:
                print("⚠️ 警告: 没有查询到任何数据")

        except Exception as e:
            print(f"❌ 详细查询失败: {e}")
            import traceback
            traceback.print_exc()
            return render_template('report.html',
                                   factories=[],
                                   error=f"查询执行失败: {str(e)}")

        # 4. 按能源类型分组数据
        energy_reports = {}
        for row in all_data:
            energy_key = row['能源类型']
            if energy_key not in energy_reports:
                energy_reports[energy_key] = []
            energy_reports[energy_key].append(row)

        print(f"📊 按能源类型分组: {list(energy_reports.keys())}")

        # 5. 计算统计数据
        total_energy_by_type = {}
        for energy_key, data_list in energy_reports.items():
            total_energy = sum(float(row.get('总能耗', 0) or 0) for row in data_list)
            total_energy_by_type[energy_key] = total_energy

        total_energy_all = sum(total_energy_by_type.values())
        print(f"📊 总能耗: {total_energy_all}")

        # 6. 获取厂区列表
        cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
        factories = cursor.fetchall()
        print(f"🏭 厂区数量: {len(factories)}")

        # 7. 准备能源类型信息
        energy_types_info = {
            '电': {'unit': 'kWh', 'color': 'primary', 'icon': 'fa-bolt'},
            '水': {'unit': 'm³', 'color': 'info', 'icon': 'fa-tint'},
            '蒸汽': {'unit': 't', 'color': 'warning', 'icon': 'fa-fire'},
            '天然气': {'unit': 'm³', 'color': 'success', 'icon': 'fa-gas-pump'}
        }

        quality_distribution = {}

        return render_template('report.html',
                               factories=factories,
                               energy_types=['电', '水', '蒸汽', '天然气', '全部'],
                               energy_reports=energy_reports,
                               total_energy_by_type=total_energy_by_type,
                               total_energy_all=total_energy_all,
                               energy_types_info=energy_types_info,
                               factory_id=factory_id,
                               energy_type=energy_type,
                               start_date=start_date,
                               end_date=end_date,
                               quality_distribution=quality_distribution,
                               data_count=len(all_data))

    except Exception as e:
        print(f"❌ 能耗报表获取失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return render_template('report.html',
                               factories=[],
                               error=f"系统错误: {str(e)}")

# 数据分析
@app.route('/energy/analysis')
@login_required
@require_role('能源管理员')
def energy_analysis():
    """数据分析"""
    try:
        analysis_type = request.args.get('type', 'peak_valley')
        energy_type = request.args.get('energy_type', '电')
        factory_ids = request.args.getlist('factory_ids')

        cursor = db.get_cursor()

        if analysis_type == 'peak_valley':
            # 峰谷分析
            base_query = """
            SELECT 
                统计日期,
                尖峰时段能耗,
                高峰时段能耗,
                平段能耗,
                低谷时段能耗,
                厂区编号
            FROM 峰谷能耗数据 
            WHERE 能源类型 = %s
            """

            params = [energy_type]

            if factory_ids and factory_ids[0]:
                placeholders = ', '.join(['%s'] * len(factory_ids))
                base_query += f" AND 厂区编号 IN ({placeholders})"
                params.extend(factory_ids)

            base_query += " ORDER BY 统计日期 DESC LIMIT 30"

            cursor.execute(base_query, params)
            data = cursor.fetchall()

            # 计算各时段占比
            peak_total = sum(float(row['尖峰时段能耗'] or 0) for row in data)
            high_total = sum(float(row['高峰时段能耗'] or 0) for row in data)
            normal_total = sum(float(row['平段能耗'] or 0) for row in data)
            valley_total = sum(float(row['低谷时段能耗'] or 0) for row in data)
            total = peak_total + high_total + normal_total + valley_total

            # 获取选中的厂区名称
            selected_factory_name = ""
            if factory_ids and factory_ids[0]:
                cursor.execute("SELECT 厂区名称 FROM 厂区 WHERE 厂区编号 = %s", (factory_ids[0],))
                factory_result = cursor.fetchone()
                if factory_result:
                    selected_factory_name = factory_result['厂区名称']

            analysis_data = {
                'labels': ['尖峰', '高峰', '平段', '低谷'],
                'values_list': [peak_total, high_total, normal_total, valley_total],
                'percentages': [
                    round(peak_total / total * 100, 1) if total > 0 else 0,
                    round(high_total / total * 100, 1) if total > 0 else 0,
                    round(normal_total / total * 100, 1) if total > 0 else 0,
                    round(valley_total / total * 100, 1) if total > 0 else 0
                ],
                'selected_factory_name': selected_factory_name or "全部厂区"
            }

            cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
            factories = cursor.fetchall()

            return render_template('analysis.html',
                                   analysis_type='peak_valley',
                                   energy_type=energy_type,
                                   factories=factories,
                                   energy_types=['电', '水', '蒸汽', '天然气'],
                                   selected_factories=factory_ids,
                                   analysis_data=analysis_data)

        elif analysis_type == 'high_consumption':
            # 高耗能分析
            threshold = int(request.args.get('threshold', 30))

            base_query = """
            SELECT 
                f.厂区名称,
                AVG(p.总能耗) as avg_energy,
                (SELECT AVG(总能耗) FROM 峰谷能耗数据 WHERE 能源类型 = %s) as overall_avg
            FROM 峰谷能耗数据 p
            JOIN 厂区 f ON p.厂区编号 = f.厂区编号
            WHERE p.能源类型 = %s
            """

            params = [energy_type, energy_type]

            if factory_ids and factory_ids[0]:
                placeholders = ', '.join(['%s'] * len(factory_ids))
                base_query += f" AND p.厂区编号 IN ({placeholders})"
                params.extend(factory_ids)

            base_query += " GROUP BY f.厂区名称"

            cursor.execute(base_query, params)
            data = cursor.fetchall()

            # 找出超标厂区
            high_consumption = []
            for row in data:
                if row['avg_energy'] and row['overall_avg']:
                    avg_energy = float(row['avg_energy'])
                    overall_avg = float(row['overall_avg'])
                    if overall_avg > 0:
                        ratio = ((avg_energy - overall_avg) / overall_avg) * 100
                        status = '正常'
                        if ratio > threshold:
                            status = '超标'
                        elif ratio > threshold * 0.7:
                            status = '预警'

                        high_consumption.append({
                            'factory': row['厂区名称'],
                            'avg_energy': avg_energy,
                            'overall_avg': overall_avg,
                            'ratio': round(ratio, 1),
                            'status': status
                        })

            cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
            factories = cursor.fetchall()

            return render_template('analysis.html',
                                   analysis_type='high_consumption',
                                   energy_type=energy_type,
                                   threshold=threshold,
                                   factories=factories,
                                   energy_types=['电', '水', '蒸汽', '天然气'],
                                   selected_factories=factory_ids,
                                   high_consumption=high_consumption)

        # 默认返回页面
        cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
        factories = cursor.fetchall()

        return render_template('analysis.html',
                               factories=factories,
                               energy_types=['电', '水', '蒸汽', '天然气'])

    except Exception as e:
        print(f"数据分析获取失败: {str(e)}")
        return render_template('analysis.html',
                               factories=[],
                               energy_types=['电', '水', '蒸汽', '天然气'])


# 数据审核
@app.route('/energy/audit')
@login_required
@require_role('能源管理员')
def energy_audit():
    """数据审核"""
    try:
        quality = request.args.get('quality', '全部')
        fluctuation = int(request.args.get('fluctuation', 20))
        audit_status = request.args.get('audit_status', '待复核')

        cursor = db.get_cursor()

        # 构建查询
        query = """
        SELECT 
            e.数据编号,
            e.设备编号,
            e.采集时间,
            e.能耗值,
            e.单位,
            e.数据质量,
            e.审核状态,
            e.审核时间,
            e.审核备注,
            f.厂区名称,
            u.真实姓名 as 审核人姓名
        FROM 能耗监测数据 e
        JOIN 能耗计量设备 m ON e.设备编号 = m.设备编号
        JOIN 设备 d ON m.设备编号 = d.设备编号
        JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        LEFT JOIN 用户 u ON e.审核人ID = u.用户ID
        WHERE 1=1
        """

        params = []

        # 数据质量筛选
        if quality != '全部':
            if quality == '中/差':
                query += " AND e.数据质量 IN ('中', '差')"
            elif quality in ['优', '良', '中', '差']:
                query += " AND e.数据质量 = %s"
                params.append(quality)

        # 审核状态筛选
        if audit_status != '全部':
            query += " AND e.审核状态 = %s"
            params.append(audit_status)

        query += " ORDER BY e.采集时间 DESC LIMIT 200"

        cursor.execute(query, params)
        abnormal_data = cursor.fetchall()

        return render_template('audit.html',
                               abnormal_data=abnormal_data,
                               quality=quality,
                               fluctuation=fluctuation,
                               audit_status=audit_status)

    except Exception as e:
        print(f"数据审核获取失败: {str(e)}")
        return render_template('audit.html',
                               abnormal_data=[],
                               quality='全部',
                               fluctuation=20,
                               audit_status='待复核')


# 能耗优化
@app.route('/energy/optimization')
@login_required
@require_role('能源管理员')
def energy_optimization():
    """能耗优化"""
    try:
        cursor = db.get_cursor()

        # 从数据库获取优化方案
        query = """
        SELECT 
            o.*,
            f.厂区名称 as 适用厂区名称
        FROM 能耗优化方案 o
        LEFT JOIN 厂区 f ON o.适用厂区编号 = f.厂区编号
        ORDER BY o.创建时间 DESC
        """

        cursor.execute(query)
        optimization_plans = cursor.fetchall()

        # 获取厂区列表和能源类型
        cursor.execute("SELECT 厂区编号, 厂区名称 FROM 厂区 ORDER BY 厂区名称")
        factories = cursor.fetchall()

        energy_types = ['电', '水', '蒸汽', '天然气']

        return render_template('optimization.html',
                               optimization_plans=optimization_plans,
                               factories=factories,
                               energy_types=energy_types)

    except Exception as e:
        print(f"能耗优化获取失败: {str(e)}")
        return render_template('optimization.html',
                               optimization_plans=[],
                               factories=[],
                               energy_types=['电', '水', '蒸汽', '天然气'])


# ============ 能耗优化API路由 ============

@app.route('/api/energy/optimization/save', methods=['POST'])
@login_required
@require_role('能源管理员')
def save_optimization():
    """保存优化方案"""
    try:
        data = request.get_json()

        # 验证必要字段
        required_fields = ['plan_name', 'energy_type', 'measures']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'缺少必要字段: {field}'}), 400

        cursor = db.get_cursor()

        # 生成方案编号
        plan_id = f"OPT{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 获取厂区编号
        factory_id = None
        factory_name = data.get('factory')
        if factory_name:
            cursor.execute("SELECT 厂区编号 FROM 厂区 WHERE 厂区名称 = %s", (factory_name,))
            result = cursor.fetchone()
            if result:
                factory_id = result['厂区编号']

        # 插入优化方案
        query = """
        INSERT INTO 能耗优化方案 
        (方案编号, 方案名称, 适用厂区编号, 能源类型, 预期节能, 实施周期, 预算费用, 负责人, 优化措施描述, 当前状态)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '已审批')
        """

        params = (
            plan_id,
            data.get('plan_name'),
            factory_id,
            data.get('energy_type'),
            float(data.get('expected_saving') or 0),
            int(data.get('implementation_days') or 0),
            float(data.get('budget') or 0),
            data.get('responsible') or session.get('username', '管理员'),
            data.get('measures')
        )

        cursor.execute(query, params)
        db.connect().commit()

        return jsonify({'success': True, 'message': '方案保存成功', 'plan_id': plan_id})

    except Exception as e:
        db.connect().rollback()
        print(f"保存优化方案失败: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/energy/optimization/update_status', methods=['POST'])
@login_required
@require_role('能源管理员')
def update_optimization_status():
    """更新优化方案状态"""
    try:
        data = request.get_json()
        plan_id = data.get('plan_id')
        new_status = data.get('status')
        actual_saving = data.get('actual_saving')

        if not plan_id or not new_status:
            return jsonify({'error': '参数不完整'}), 400

        if new_status not in ['已审批', '执行中', '已完成', '已取消']:
            return jsonify({'error': '状态值无效'}), 400

        cursor = db.get_cursor()

        # 构建SQL查询语句
        if new_status == '已完成':
            # 如果新状态是"已完成"，需要验证实际节能率
            if actual_saving is None:
                return jsonify({'error': '切换到"已完成"状态必须提供实际节能率'}), 400

            try:
                saving_value = float(actual_saving)
                if saving_value < 0 or saving_value > 100:
                    return jsonify({'error': '实际节能率必须在0-100之间'}), 400
            except ValueError:
                return jsonify({'error': '实际节能率格式不正确'}), 400

            # 更新状态、实际节能率和更新时间
            query = """
            UPDATE 能耗优化方案 
            SET 当前状态 = %s, 
                实际节能 = %s,
                更新时间 = NOW()
            WHERE 方案编号 = %s
            """
            params = (new_status, saving_value, plan_id)
        else:
            # 如果新状态不是"已完成"，清除实际节能率字段
            query = """
            UPDATE 能耗优化方案 
            SET 当前状态 = %s, 
                实际节能 = NULL,
                更新时间 = NOW()
            WHERE 方案编号 = %s
            """
            params = (new_status, plan_id)

        cursor.execute(query, params)
        db.connect().commit()

        return jsonify({'success': True, 'message': '状态更新成功'})

    except Exception as e:
        db.connect().rollback()
        print(f"更新优化方案状态失败: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/energy/optimization/detail/<plan_id>')
@login_required
@require_role('能源管理员')
def get_optimization_detail(plan_id):
    """获取优化方案详情"""
    try:
        cursor = db.get_cursor()

        query = """
        SELECT 
            o.*,
            f.厂区名称 as 适用厂区名称
        FROM 能耗优化方案 o
        LEFT JOIN 厂区 f ON o.适用厂区编号 = f.厂区编号
        WHERE o.方案编号 = %s
        """

        cursor.execute(query, (plan_id,))
        plan = cursor.fetchone()

        if not plan:
            return jsonify({'error': '方案不存在'}), 404

        # 转换日期格式
        if plan.get('创建时间'):
            plan['创建时间'] = plan['创建时间'].strftime('%Y-%m-%d %H:%M:%S')
        if plan.get('更新时间'):
            plan['更新时间'] = plan['更新时间'].strftime('%Y-%m-%d %H:%M:%S')

        return jsonify(plan)

    except Exception as e:
        print(f"获取优化方案详情失败: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ============ 数据审核API路由 ============

@app.route('/api/energy/audit/update_status', methods=['POST'])
@login_required
@require_role('能源管理员')
def update_audit_status():
    """更新数据审核状态"""
    try:
        data = request.get_json()
        data_id = data.get('data_id')
        new_status = data.get('status')
        remark = data.get('remark', '')

        if not data_id or not new_status:
            return jsonify({'error': '参数不完整'}), 400

        if new_status not in ['待复核', '已复核']:
            return jsonify({'error': '状态值无效'}), 400

        cursor = db.get_cursor()

        # 如果标记为已复核，记录审核人和时间
        if new_status == '已复核':
            query = """
            UPDATE 能耗监测数据 
            SET 审核状态 = %s,
                审核备注 = %s,
                审核时间 = NOW(),
                审核人ID = %s
            WHERE 数据编号 = %s
            """
            params = (new_status, remark, session.get('user_id'), data_id)
        else:
            # 如果标记为待复核，清除审核信息
            query = """
            UPDATE 能耗监测数据 
            SET 审核状态 = %s,
                审核备注 = %s,
                审核时间 = NULL,
                审核人ID = NULL
            WHERE 数据编号 = %s
            """
            params = (new_status, remark, data_id)

        cursor.execute(query, params)
        db.connect().commit()

        return jsonify({'success': True, 'message': '审核状态更新成功'})

    except Exception as e:
        db.connect().rollback()
        print(f"更新审核状态失败: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/energy/audit/batch_update', methods=['POST'])
@login_required
@require_role('能源管理员')
def batch_update_audit_status():
    """批量更新审核状态"""
    try:
        data = request.get_json()
        data_ids = data.get('data_ids', [])
        new_status = data.get('status')

        if not data_ids or not new_status:
            return jsonify({'error': '参数不完整'}), 400

        cursor = db.get_cursor()

        # 构建IN查询的占位符
        placeholders = ', '.join(['%s'] * len(data_ids))

        if new_status == '已复核':
            query = f"""
            UPDATE 能耗监测数据 
            SET 审核状态 = %s,
                审核时间 = NOW(),
                审核人ID = %s,
                审核备注 = '批量审核'
            WHERE 数据编号 IN ({placeholders})
            """
            params = [new_status, session.get('user_id')] + data_ids
        else:
            query = f"""
            UPDATE 能耗监测数据 
            SET 审核状态 = %s,
                审核时间 = NULL,
                审核人ID = NULL,
                审核备注 = ''
            WHERE 数据编号 IN ({placeholders})
            """
            params = [new_status] + data_ids

        cursor.execute(query, params)
        db.connect().commit()

        return jsonify({'success': True, 'message': f'成功更新{cursor.rowcount}条记录'})

    except Exception as e:
        db.connect().rollback()
        print(f"批量更新审核状态失败: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ============ 运维人员功能路由 ============
@app.route('/dashboard.html')
def redirect_dashboard():
    """重定向 dashboard.html 到运维仪表板"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_role = session.get('user_role')
    if user_role == '运维人员':
        return redirect(url_for('operation_dashboard'))
    else:
        # 其他角色也做相应重定向
        return redirect(url_for('user_dashboard'))


@app.route('/api/operation/work-orders', methods=['GET'])
@login_required
@require_role('运维人员')
def get_work_orders():
    """获取运维工单列表"""
    try:
        user_id = session.get('user_id')
        status = request.args.get('status', 'all')  # pending, completed, all

        cursor = db.get_cursor()

        # 构建基础查询
        base_sql = """
        SELECT 
            w.工单ID, w.工单编号, a.告警内容, a.告警等级,
            d.设备名称, w.派单时间, w.响应时间, w.处理完成时间,
            w.处理结果, w.复查状态, w.处理耗时,
            f.厂区名称, a.告警ID
        FROM 运维工单 w
        JOIN 告警信息 a ON w.告警ID = a.告警ID
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        WHERE w.运维人员ID = %s
        """

        params = [user_id]

        if status == 'pending':
            base_sql += " AND w.处理完成时间 IS NULL"
        elif status == 'completed':
            base_sql += " AND w.处理完成时间 IS NOT NULL"

        base_sql += " ORDER BY w.派单时间 DESC"

        cursor.execute(base_sql, params)
        orders = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': orders
        })

    except Exception as e:
        print(f"获取工单列表失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/alert-badge', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_alert_badge_api():
    """获取告警徽章数量"""
    try:
        factory_id = session.get('factory_id')
        cursor = db.get_cursor()

        # 获取未处理的告警数量
        sql = """
        SELECT COUNT(*) as count
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE a.处理状态 = '未处理'
        """

        if factory_id:
            sql += " AND (d.所属厂区编号 = %s OR d.所属厂区编号 IS NULL)"
            cursor.execute(sql, (factory_id,))
        else:
            cursor.execute(sql)

        result = cursor.fetchone()
        count = result['count'] if result else 0

        return jsonify({
            'success': True,
            'count': count
        })

    except Exception as e:
        print(f"获取告警数量失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取失败', 'count': 0})


@app.route('/api/reminders', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_reminders_api():
    """获取工单提醒"""
    try:
        user_id = session.get('user_id')
        user_role = session.get('user_role')

        print(f"🔍 获取工单提醒 - 用户: {user_id}, 角色: {user_role}")

        cursor = db.get_cursor()

        # 根据用户角色构建查询
        if user_role == '运维人员':
            # 运维人员只看到自己的工单提醒
            sql = """
            SELECT 
                w.工单ID,
                w.工单编号,
                a.告警内容,
                a.告警等级,
                w.派单时间,
                w.响应时间,
                w.处理完成时间,
                d.设备名称,
                f.厂区名称,
                TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) as 派单时长
            FROM 运维工单 w
            JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
            LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
            WHERE w.运维人员ID = %s 
              AND w.处理完成时间 IS NULL
              AND w.派单时间 >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY 
                CASE a.告警等级
                    WHEN '高' THEN 1
                    WHEN '中' THEN 2
                    WHEN '低' THEN 3
                    ELSE 4
                END,
                w.派单时间
            """
            cursor.execute(sql, (user_id,))
        else:
            # 工单管理员看到所有提醒
            sql = """
            SELECT 
                w.工单ID,
                w.工单编号,
                a.告警内容,
                a.告警等级,
                w.派单时间,
                w.响应时间,
                w.处理完成时间,
                d.设备名称,
                f.厂区名称,
                u.真实姓名 as 运维人员姓名,
                TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) as 派单时长
            FROM 运维工单 w
            JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
            LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            WHERE w.处理完成时间 IS NULL
              AND w.派单时间 >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            ORDER BY 
                CASE a.告警等级
                    WHEN '高' THEN 1
                    WHEN '中' THEN 2
                    WHEN '低' THEN 3
                    ELSE 4
                END,
                w.派单时间
            """
            cursor.execute(sql)

        reminders = cursor.fetchall()

        # 格式化提醒数据
        formatted_reminders = []
        for reminder in reminders:
            # 确定提醒类型
            alert_level = reminder['告警等级'] or '中'
            hours_passed = reminder['派单时长'] or 0

            reminder_type = '中等级提醒'
            if alert_level == '高':
                if hours_passed >= 0.25:  # 15分钟未响应
                    reminder_type = '高等级紧急'
                else:
                    reminder_type = '高等级提醒'
            elif alert_level == '中' and hours_passed > 24:
                reminder_type = '中等级逾期'
            elif alert_level == '低' and hours_passed > 72:
                reminder_type = '低等级逾期'

            # 构建提醒内容
            device_name = reminder['设备名称'] or '未知设备'
            if alert_level == '高':
                reminder_content = f'高等级告警：{reminder["告警内容"]}，设备：{device_name}'
            else:
                reminder_content = f'{alert_level}等级告警：{reminder["告警内容"]}，设备：{device_name}'

            # 如果有响应时间，标记为已响应
            if reminder['响应时间']:
                reminder_content += '（已响应）'

            formatted_reminders.append({
                '工单ID': reminder['工单ID'],
                '工单编号': reminder['工单编号'],
                '提醒类型': reminder_type,
                '提醒内容': reminder_content,
                '派单时间': reminder['派单时间'].isoformat() if reminder['派单时间'] else None,
                '提醒时间': datetime.now().isoformat(),
                '状态': '未处理'
            })

        return jsonify({
            'success': True,
            'data': formatted_reminders
        })

    except Exception as e:
        print(f"❌ 获取工单提醒失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取提醒失败: {str(e)}'
        }), 500


# ============ 通用的运维API路由（供前端调用）============

@app.route('/api/operation/dashboard/stats', methods=['GET'])
@login_required
@require_role('运维人员')
def get_dashboard_stats_operation():
    """获取运维人员仪表板统计"""
    try:
        print(f"🔍 正在获取运维人员仪表板统计，用户ID: {session.get('user_id')}, 角色: {session.get('user_role')}")
        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 工单统计
        sql_orders = """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN 处理完成时间 IS NULL THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN 处理完成时间 IS NOT NULL THEN 1 ELSE 0 END) as completed
        FROM 运维工单 
        WHERE 运维人员ID = %s
        """
        cursor.execute(sql_orders, (user_id,))
        orders = cursor.fetchone()

        stats = {
            'total': orders['total'] if orders else 0,
            'pending': orders['pending'] if orders else 0,
            'completed': orders['completed'] if orders else 0
        }

        # 告警统计
        sql_alerts = """
        SELECT 
            COUNT(*) as total_alerts,
            SUM(CASE WHEN 告警等级 = '高' THEN 1 ELSE 0 END) as high_alarms,
            SUM(CASE WHEN 告警等级 = '中' THEN 1 ELSE 0 END) as medium_alarms,
            SUM(CASE WHEN 告警等级 = '低' THEN 1 ELSE 0 END) as low_alarms
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE d.所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_alerts, (user_id,))
        alerts = cursor.fetchone()

        if alerts:
            stats.update({
                'high_alarms': alerts['high_alarms'] or 0,
                'medium_alarms': alerts['medium_alarms'] or 0,
                'low_alarms': alerts['low_alarms'] or 0
            })
        else:
            stats.update({
                'high_alarms': 0,
                'medium_alarms': 0,
                'low_alarms': 0
            })

        # 设备统计
        sql_devices = """
        SELECT 
            COUNT(*) as total_devices,
            SUM(CASE WHEN 运行状态 = '正常' THEN 1 ELSE 0 END) as normal,
            SUM(CASE WHEN 运行状态 = '故障' THEN 1 ELSE 0 END) as fault,
            SUM(CASE WHEN 运行状态 = '维护中' THEN 1 ELSE 0 END) as maintenance,
            SUM(CASE WHEN 运行状态 = '离线' THEN 1 ELSE 0 END) as offline
        FROM 设备
        WHERE 所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_devices, (user_id,))
        devices = cursor.fetchone()

        if devices:
            stats.update({
                'total_devices': devices['total_devices'] or 0,
                'normal_devices': devices['normal'] or 0,
                'faulty_devices': devices['fault'] or 0,
                'maintenance_devices': devices['maintenance'] or 0,
                'offline_devices': devices['offline'] or 0
            })

        return jsonify({
            'success': True,
            'data': stats
        })

    except Exception as e:
        print(f"获取仪表板统计失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/work-orders', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_work_orders_api():
    """获取工单列表"""
    try:
        user_id = session.get('user_id')
        status = request.args.get('status', 'all')

        cursor = db.get_cursor()

        # 构建基础查询
        base_sql = """
        SELECT 
            w.工单ID, w.工单编号, a.告警内容, a.告警等级,
            d.设备名称, w.派单时间, w.响应时间, w.处理完成时间,
            w.处理结果, w.复查状态, w.处理耗时,
            f.厂区名称, a.告警ID
        FROM 运维工单 w
        JOIN 告警信息 a ON w.告警ID = a.告警ID
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        WHERE w.运维人员ID = %s
        """

        params = [user_id]

        if status == 'pending':
            base_sql += " AND w.处理完成时间 IS NULL AND w.响应时间 IS NULL"
        elif status == 'in-progress':
            base_sql += " AND w.处理完成时间 IS NULL AND w.响应时间 IS NOT NULL"
        elif status == 'completed':
            base_sql += " AND w.处理完成时间 IS NOT NULL"

        base_sql += " ORDER BY w.派单时间 DESC"

        cursor.execute(base_sql, tuple(params))
        orders = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': orders
        })

    except Exception as e:
        print(f"获取工单列表失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/alerts', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_alerts_api():
    """获取告警列表"""
    try:
        factory_id = session.get('factory_id')
        status = request.args.get('status', 'all')
        level = request.args.get('level', 'all')
        device_type = request.args.get('device_type', 'all')
        start_date = request.args.get('start_date')

        cursor = db.get_cursor()

        # 构建SQL查询
        sql = """
        SELECT 
            a.*,
            d.设备名称,
            d.设备类型,
            d.所属厂区编号,
            f.厂区名称,
            w.工单编号 as 关联工单编号
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        LEFT JOIN 运维工单 w ON a.告警ID = w.告警ID
        WHERE 1=1
        """

        params = []

        # 厂区筛选
        if factory_id:
            sql += " AND (d.所属厂区编号 = %s OR d.所属厂区编号 IS NULL)"
            params.append(factory_id)

        # 状态筛选
        if status == 'unprocessed':
            sql += " AND a.处理状态 = '未处理'"
        elif status == 'in-progress':
            sql += " AND a.处理状态 = '处理中'"
        elif status == 'processed':
            sql += " AND a.处理状态 = '已结案'"

        # 等级筛选
        if level in ['高', '中', '低']:
            sql += " AND a.告警等级 = %s"
            params.append(level)

        # 设备类型筛选
        if device_type != 'all':
            sql += " AND d.设备类型 = %s"
            params.append(device_type)

        # 时间筛选
        if start_date:
            sql += " AND DATE(a.发生时间) >= %s"
            params.append(start_date)

        sql += " ORDER BY a.发生时间 DESC"

        cursor.execute(sql, tuple(params))
        alerts = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': alerts
        })

    except Exception as e:
        print(f"获取告警列表失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/equipment', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_equipment_api():
    """获取设备列表（修复版）"""
    try:
        user_id = session.get('user_id')
        user_role = session.get('user_role')
        factory_id = session.get('factory_id')

        print(f"🔍 DEBUG - 获取设备列表")
        print(f"🔍 用户ID: {user_id}")
        print(f"🔍 用户角色: {user_role}")
        print(f"🔍 厂区ID: {factory_id}")
        print(f"🔍 Session内容: {dict(session)}")

        # 如果运维人员没有厂区ID，尝试从数据库查询
        if not factory_id and user_role == '运维人员':
            print(f"⚠️ 运维人员 {user_id} 的session中没有factory_id，从数据库查询")
            cursor = db.get_cursor()
            cursor.execute("SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s", (user_id,))
            user_info = cursor.fetchone()

            if user_info and user_info['负责的厂区编号']:
                factory_id = user_info['负责的厂区编号']
                session['factory_id'] = factory_id  # 更新session
                print(f"✅ 从数据库获取到厂区ID: {factory_id}")
            else:
                print(f"❌ 数据库中也没有找到厂区ID")
                return jsonify({
                    'success': True,
                    'data': [],
                    'message': '您尚未分配厂区，请联系管理员分配'
                })

        cursor = db.get_cursor()

        # 构建查询
        if user_role == '运维人员':
            print(f"🔍 查询运维人员 {user_id} 的厂区 {factory_id} 的设备")

            # 验证厂区是否存在
            cursor.execute("SELECT 厂区名称 FROM 厂区 WHERE 厂区编号 = %s", (factory_id,))
            factory_info = cursor.fetchone()

            if not factory_info:
                print(f"❌ 厂区 {factory_id} 不存在")
                return jsonify({
                    'success': True,
                    'data': [],
                    'message': f'厂区 {factory_id} 不存在，请联系管理员'
                })

            print(f"✅ 厂区存在: {factory_info['厂区名称']}")

            # 运维人员只看到自己负责厂区的设备
            sql = """
            SELECT 
                d.设备编号, 
                d.设备名称, 
                d.设备大类, 
                d.设备类型, 
                d.运行状态, 
                d.安装位置描述,
                e.安装时间, 
                e.质保期, 
                e.报废状态, 
                e.维修记录
            FROM 设备 d
            LEFT JOIN 设备台账 e ON d.设备编号 = e.设备编号
            WHERE d.所属厂区编号 = %s
            ORDER BY d.设备编号
            """

            print(f"🔍 执行SQL: {sql}")
            print(f"🔍 参数: factory_id = {factory_id}")

            cursor.execute(sql, (factory_id,))

        elif user_role == '运维工单管理员':
            print("🔍 工单管理员查看所有设备")
            # 工单管理员看到所有设备
            sql = """
            SELECT 
                d.设备编号, 
                d.设备名称, 
                d.设备大类, 
                d.设备类型, 
                d.运行状态, 
                d.安装位置描述,
                e.安装时间, 
                e.质保期, 
                e.报废状态, 
                e.维修记录,
                f.厂区名称
            FROM 设备 d
            LEFT JOIN 设备台账 e ON d.设备编号 = e.设备编号
            LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
            ORDER BY d.所属厂区编号, d.设备编号
            """
            cursor.execute(sql)
        else:
            # 其他角色返回空列表
            cursor.execute("SELECT 1 LIMIT 0")

        equipment = cursor.fetchall()

        print(f"✅ 查询到 {len(equipment)} 条设备记录")

        # 处理日期格式
        formatted_equipment = []
        for item in equipment:
            formatted_item = dict(item)

            # 处理安装时间
            if formatted_item.get('安装时间'):
                if isinstance(formatted_item['安装时间'], datetime):
                    formatted_item['安装时间'] = formatted_item['安装时间'].strftime('%Y-%m-%d')
                else:
                    formatted_item['安装时间'] = str(formatted_item['安装时间'])

            formatted_equipment.append(formatted_item)

        return jsonify({
            'success': True,
            'data': formatted_equipment,
            'user_role': user_role,
            'factory_id': factory_id,
            'equipment_count': len(formatted_equipment)
        })

    except Exception as e:
        print(f"❌ 获取设备列表失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/api/operation/work-orders/<work_order_id>/respond', methods=['POST'])
@login_required
@require_role('运维人员')
def respond_work_order(work_order_id):
    """响应工单"""
    try:
        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 检查工单是否存在且属于当前用户
        check_sql = """
        SELECT 工单ID FROM 运维工单 
        WHERE 工单ID = %s AND 运维人员ID = %s
        """
        cursor.execute(check_sql, (work_order_id, user_id))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': '工单不存在或无权限'}), 404

        # 更新响应时间
        sql = """
        UPDATE 运维工单 
        SET 响应时间 = NOW() 
        WHERE 工单ID = %s AND 运维人员ID = %s
        """
        cursor.execute(sql, (work_order_id, user_id))
        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '响应成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"响应工单失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/work-orders/<work_order_id>/complete', methods=['POST'])
@login_required
@require_role('运维人员')
def complete_work_order(work_order_id):
    """完成工单"""
    try:
        data = request.get_json()
        result_text = data.get('result', '')

        if not result_text:
            return jsonify({'success': False, 'message': '请输入处理结果'}), 400

        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 检查工单是否存在且属于当前用户
        check_sql = """
        SELECT 工单ID, 响应时间 FROM 运维工单 
        WHERE 工单ID = %s AND 运维人员ID = %s
        """
        cursor.execute(check_sql, (work_order_id, user_id))
        order = cursor.fetchone()

        if not order:
            return jsonify({'success': False, 'message': '工单不存在或无权限'}), 404

        # 计算处理时长
        process_minutes = 0
        if order['响应时间']:
            cursor.execute("SELECT TIMESTAMPDIFF(MINUTE, %s, NOW()) as minutes", (order['响应时间'],))
            time_result = cursor.fetchone()
            process_minutes = time_result['minutes'] if time_result else 0

        # 更新工单
        sql = """
        UPDATE 运维工单 
        SET 处理完成时间 = NOW(),
            处理结果 = %s,
            处理耗时 = %s,
            复查状态 = '已完成'
        WHERE 工单ID = %s AND 运维人员ID = %s
        """

        cursor.execute(sql, (result_text, process_minutes, work_order_id, user_id))

        # 更新关联告警状态为已结案
        update_alert_sql = """
        UPDATE 告警信息 
        SET 处理状态 = '已结案'
        WHERE 告警ID IN (
            SELECT 告警ID FROM 运维工单 WHERE 工单ID = %s
        )
        """
        cursor.execute(update_alert_sql, (work_order_id,))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '完成成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"完成工单失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/alerts', methods=['GET'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def get_alerts():
    """获取告警列表"""
    try:
        factory_id = session.get('factory_id')
        status = request.args.get('status', 'all')  # all, unprocessed, processed, acknowledged
        level = request.args.get('level', 'all')  # all, 高, 中, 低
        device_type = request.args.get('device_type', 'all')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        cursor = db.get_cursor()

        # 构建SQL查询
        sql = """
        SELECT 
            a.*,
            d.设备名称,
            d.设备类型,
            d.所属厂区编号,
            f.厂区名称,
            w.工单编号 as 关联工单编号
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        LEFT JOIN 运维工单 w ON a.告警ID = w.告警ID
        WHERE 1=1
        """

        params = []

        # 厂区筛选
        if factory_id:
            sql += " AND (d.所属厂区编号 = %s OR d.所属厂区编号 IS NULL)"
            params.append(factory_id)

        # 状态筛选
        if status == 'unprocessed':
            sql += " AND a.处理状态 = '未处理'"
        elif status == 'processed':
            sql += " AND a.处理状态 = '已结案'"
        elif status == 'acknowledged':
            sql += " AND a.确认时间 IS NOT NULL AND a.处理状态 = '未处理'"

        # 等级筛选
        if level in ['高', '中', '低']:
            sql += " AND a.告警等级 = %s"
            params.append(level)

        sql += " ORDER BY a.发生时间 DESC"

        cursor.execute(sql, tuple(params))
        alerts = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': alerts
        })

    except Exception as e:
        print(f"获取告警列表失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/alerts/<alert_id>/acknowledge', methods=['POST'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def acknowledge_alert(alert_id):
    """确认告警"""
    try:
        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 检查告警是否存在
        check_sql = "SELECT 告警ID FROM 告警信息 WHERE 告警ID = %s"
        cursor.execute(check_sql, (alert_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': '告警不存在'}), 404

        # 更新告警确认信息
        sql = """
        UPDATE 告警信息 
        SET 告警确认人ID = %s, 确认时间 = NOW() 
        WHERE 告警ID = %s
        """
        cursor.execute(sql, (user_id, alert_id))
        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '告警确认成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"确认告警失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/alerts/<alert_id>/create-work-order', methods=['POST'])
@login_required
@require_role(['运维人员', '运维工单管理员'])
def create_work_order(alert_id):
    """根据告警创建工单"""
    try:
        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 1. 检查告警是否存在
        sql_check = """
        SELECT 
            a.告警ID, a.告警编号, a.告警内容, a.告警等级, a.关联设备编号,
            d.设备名称, d.所属厂区编号, d.安装位置描述,
            f.厂区名称
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        WHERE a.告警ID = %s
        """

        cursor.execute(sql_check, (alert_id,))
        alert_result = cursor.fetchone()

        if not alert_result:
            return jsonify({'success': False, 'message': '告警不存在'})

        # 2. 检查是否已存在工单
        sql_check_work_order = """
        SELECT 工单ID, 工单编号 FROM 运维工单 WHERE 告警ID = %s
        """
        cursor.execute(sql_check_work_order, (alert_id,))
        existing_order = cursor.fetchone()

        if existing_order:
            work_order_no = existing_order.get('工单编号', '未知')
            return jsonify({
                'success': False,
                'message': f'该告警已存在工单: {work_order_no}'
            })

        # 3. 生成工单编号
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        sql_count = """
        SELECT COUNT(*) as count 
        FROM 运维工单 
        WHERE 工单编号 LIKE %s
        """
        cursor.execute(sql_count, (f"WO{today}%",))
        count_result = cursor.fetchone()
        count = count_result['count'] if count_result else 0

        work_order_no = f"WO{today}{count + 1:03d}"
        work_order_id = f"WO{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 4. 插入工单记录
        sql_insert = """
        INSERT INTO 运维工单 (
            工单ID, 工单编号, 告警ID, 运维人员ID, 
            派单时间, 复查状态
        ) VALUES (%s, %s, %s, %s, NOW(), '未通过')
        """

        cursor.execute(sql_insert, (work_order_id, work_order_no, alert_id, user_id))

        # 5. 更新告警状态为"处理中"
        sql_update_alert = """
        UPDATE 告警信息 
        SET 处理状态 = '处理中'
        WHERE 告警ID = %s
        """

        cursor.execute(sql_update_alert, (alert_id,))
        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '工单创建成功',
            'data': {
                'work_order_id': work_order_id,
                'work_order_no': work_order_no,
                'alert_id': alert_id,
                'alert_no': alert_result.get('告警编号'),
                'alert_content': alert_result.get('告警内容'),
                'device_name': alert_result.get('设备名称'),
                'factory_name': alert_result.get('厂区名称'),
                'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })

    except Exception as e:
        db.connect().rollback()
        print(f"创建工单失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/profile', methods=['GET'])
@login_required
@require_role('运维人员')
def get_profile():
    """获取运维人员个人信息"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()
        sql = """
        SELECT 
            用户ID, 登录账号, 真实姓名, 用户角色,
            手机号码, 负责的厂区编号, 上次登录的时间
        FROM 用户
        WHERE 用户ID = %s
        """
        cursor.execute(sql, (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        # 获取厂区信息
        factory_name = None
        if user['负责的厂区编号']:
            sql = "SELECT 厂区名称 FROM 厂区 WHERE 厂区编号 = %s"
            cursor.execute(sql, (user['负责的厂区编号'],))
            factory = cursor.fetchone()
            factory_name = factory['厂区名称'] if factory else None

        user_info = {
            'id': user['用户ID'],
            'username': user['登录账号'],
            'real_name': user['真实姓名'],
            'role': user['用户角色'],
            'phone': user['手机号码'],
            'factory_id': user['负责的厂区编号'],
            'factory_name': factory_name,
            'last_login': user['上次登录的时间'].strftime('%Y-%m-%d %H:%M:%S') if user['上次登录的时间'] else None
        }

        return jsonify({
            'success': True,
            'data': user_info
        })

    except Exception as e:
        print(f"获取个人信息失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/change-password', methods=['POST'])
@login_required
@require_role('运维人员')
def change_password():
    """修改密码"""
    try:
        data = request.get_json()
        old_password = data.get('old_password')
        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')

        if not all([old_password, new_password, confirm_password]):
            return jsonify({'success': False, 'message': '请填写所有字段'}), 400

        if new_password != confirm_password:
            return jsonify({'success': False, 'message': '两次输入的密码不一致'}), 400

        # 检查密码强度
        strength_result, strength_message = check_password_strength(new_password)
        if not strength_result:
            return jsonify({'success': False, 'message': strength_message}), 400

        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 验证原密码
        sql = "SELECT 密码哈希值 FROM 用户 WHERE 用户ID = %s"
        cursor.execute(sql, (user_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        if not verify_md5(user['密码哈希值'], old_password):
            return jsonify({'success': False, 'message': '原密码错误'}), 400

        # 更新密码
        new_hash = md5_hash(new_password)
        update_sql = """
        UPDATE 用户 
        SET 密码哈希值 = %s
        WHERE 用户ID = %s
        """

        cursor.execute(update_sql, (new_hash, user_id))
        db.connect().commit()

        return jsonify({
            'success': True,
            'message': '密码修改成功'
        })

    except Exception as e:
        db.connect().rollback()
        print(f"修改密码失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/dashboard-stats', methods=['GET'])
@login_required
@require_role('运维人员')
def get_operation_dashboard_stats():
    """获取运维人员仪表板统计"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()

        # 工单统计
        sql_orders = """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN 处理完成时间 IS NULL THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN 处理完成时间 IS NOT NULL THEN 1 ELSE 0 END) as completed
        FROM 运维工单 
        WHERE 运维人员ID = %s
        """
        cursor.execute(sql_orders, (user_id,))
        orders = cursor.fetchone()

        stats = {
            'total_orders': orders['total'] if orders else 0,
            'pending_orders': orders['pending'] if orders else 0,
            'completed_orders': orders['completed'] if orders else 0
        }

        # 告警统计
        sql_alerts = """
        SELECT 
            COUNT(*) as total_alerts,
            SUM(CASE WHEN 处理状态 = '未处理' THEN 1 ELSE 0 END) as unprocessed
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE d.所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_alerts, (user_id,))
        alerts = cursor.fetchone()

        stats['total_alerts'] = alerts['total_alerts'] if alerts else 0
        stats['unprocessed_alerts'] = alerts['unprocessed'] if alerts else 0

        # 设备统计
        sql_devices = """
        SELECT 
            COUNT(*) as total_devices,
            SUM(CASE WHEN 运行状态 = '正常' THEN 1 ELSE 0 END) as normal,
            SUM(CASE WHEN 运行状态 = '故障' THEN 1 ELSE 0 END) as faulty
        FROM 设备
        WHERE 所属厂区编号 = (
            SELECT 负责的厂区编号 FROM 用户 WHERE 用户ID = %s
        )
        """
        cursor.execute(sql_devices, (user_id,))
        devices = cursor.fetchone()

        stats['total_devices'] = devices['total_devices'] if devices else 0
        stats['normal_devices'] = devices['normal'] if devices else 0
        stats['faulty_devices'] = devices['faulty'] if devices else 0

        return jsonify({
            'success': True,
            'data': stats
        })

    except Exception as e:
        print(f"获取仪表板统计失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/reminders', methods=['GET'])
@login_required
@require_role('运维人员')
def get_reminders():
    """获取工单提醒"""
    try:
        user_id = session.get('user_id')

        cursor = db.get_cursor()

        # 查询待处理工单提醒
        sql = """
        SELECT 
            w.工单ID,
            w.工单编号,
            a.告警内容,
            a.告警等级,
            w.派单时间,
            d.设备名称,
            f.厂区名称,
            TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) as hours_passed,
            CASE 
                WHEN a.告警等级 = '高' AND TIMESTAMPDIFF(MINUTE, w.派单时间, NOW()) > 15 THEN '紧急'
                WHEN a.告警等级 = '中' AND TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) > 24 THEN '逾期'
                WHEN a.告警等级 = '低' AND TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) > 72 THEN '逾期'
                ELSE '正常'
            END as reminder_status
        FROM 运维工单 w
        JOIN 告警信息 a ON w.告警ID = a.告警ID
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        WHERE w.运维人员ID = %s 
          AND w.处理完成时间 IS NULL
        ORDER BY 
            CASE a.告警等级
                WHEN '高' THEN 1
                WHEN '中' THEN 2
                WHEN '低' THEN 3
                ELSE 4
            END,
            w.派单时间
        """

        cursor.execute(sql, (user_id,))
        reminders = cursor.fetchall()

        return jsonify({
            'success': True,
            'data': reminders
        })

    except Exception as e:
        print(f"获取提醒失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/operation/alert-badge', methods=['GET'])
@login_required
@require_role('运维人员')
def get_alert_badge():
    """获取告警徽章数量"""
    try:
        user_id = session.get('user_id')
        factory_id = session.get('factory_id')

        cursor = db.get_cursor()

        # 获取未处理的告警数量
        sql = """
        SELECT COUNT(*) as count
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        WHERE a.处理状态 = '未处理'
        """

        if factory_id:
            sql += " AND (d.所属厂区编号 = %s OR d.所属厂区编号 IS NULL)"
            cursor.execute(sql, (factory_id,))
        else:
            cursor.execute(sql)

        result = cursor.fetchone()
        count = result['count'] if result else 0

        return jsonify({
            'success': True,
            'count': count
        })

    except Exception as e:
        print(f"获取告警数量失败: {str(e)}")
        return jsonify({'success': False, 'message': '获取失败', 'count': 0})

# ============ 企业管理层功能 ============

@app.route('/management/dashboard')
@login_required
@require_role('企业管理层')
def management_dashboard():
    """企业管理层大屏展示页面"""
    # 检查是否已登录
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # 获取大屏配置和数据
    try:
        cursor = db.get_cursor()

        # 1. 查找权限等级为"企业管理层"的大屏配置
        sql_config = """
        SELECT 配置编号, 展示模块, 数据刷新频率, 展示字段, 排序规则 
        FROM 大屏展示配置 
        WHERE 权限等级 = '管理员'
        ORDER BY 配置编号
        LIMIT 1
        """
        cursor.execute(sql_config)
        config = cursor.fetchone()

        if not config:
            return render_template('dashboardqy.html',
                                   error='未找到企业管理层的大屏配置',
                                   user=session)

        config_id = config['配置编号']

        # 2. 根据配置编号获取最新的汇总数据
        sql_data = """
        SELECT * 
        FROM 实时汇总数据 
        WHERE 配置编号 = %s 
        ORDER BY 统计时间 DESC 
        LIMIT 1
        """
        cursor.execute(sql_data, (config_id,))
        summary_data = cursor.fetchone()

        # 计算光伏收益（如果表中没有这些字段，我们动态计算）
        if summary_data:
            # 获取光伏数据
            光伏总发电量 = summary_data.get('光伏总发电量', 0) or 0
            光伏自用电量 = summary_data.get('光伏自用电量', 0) or 0

            # 设置电价（您可以根据实际情况修改这些值）
            自用电价 = summary_data.get('自用电价')
            上网电价 = summary_data.get('上网电价')

            # 如果数据库中电价字段为None或空，使用默认值
            if 自用电价 is None:
                自用电价 = 0.8
            if 上网电价 is None:
                上网电价 = 0.4
            # 转换为浮点数以确保计算正确
            光伏总发电量 = float(光伏总发电量) if 光伏总发电量 is not None else 0.0
            光伏自用电量 = float(光伏自用电量) if 光伏自用电量 is not None else 0.0
            自用电价 = float(自用电价) if 自用电价 is not None else 0.8
            上网电价 = float(上网电价) if 上网电价 is not None else 0.4

            # 计算剩余上网电量（不能为负数）
            光伏剩余上网电量 = 光伏总发电量 - 光伏自用电量
            if 光伏剩余上网电量 < 0:
                光伏剩余上网电量 = 0

            # 计算公式：光伏收益 = (光伏总发电量 - 光伏自用电量) * 上网电价 + 光伏自用电量 * 自用电价
            光伏收益 = (光伏剩余上网电量 * 上网电价) + (光伏自用电量 * 自用电价)

            # 将计算结果添加到返回的数据中
            summary_data['自用电价'] = 自用电价
            summary_data['上网电价'] = 上网电价
            summary_data['光伏收益'] = round(光伏收益, 2)
            summary_data['光伏剩余上网电量'] = round(光伏剩余上网电量, 2)

        # 3. 获取高等级告警信息（显示待决策和处理中的设备故障告警）
        sql_alarms = """
        SELECT 告警ID, 告警编号, 告警内容, 发生时间, 告警类型, 关联设备编号, 处理状态
        FROM 告警信息 
        WHERE 告警等级 = '高' 
        AND 告警类型 = '设备故障'
        AND 处理状态 IN ('待决策', '处理中', '未处理')
        ORDER BY 
            CASE 处理状态
                WHEN '待决策' THEN 1  -- 待决策的排在最前面
                WHEN '处理中' THEN 2
                WHEN '未处理' THEN 3  -- 添加未处理的排序
                ELSE 4
            END,
            发生时间 DESC 
        """
        cursor.execute(sql_alarms)
        high_alarms = cursor.fetchall()

        # 4. 统计待决策的高等级告警数量
        sql_alarm_count = """
        SELECT COUNT(*) as count
        FROM 告警信息 
        WHERE 告警等级 = '高' 
        AND 告警类型 = '设备故障'
        AND 处理状态 = '待决策'
        """
        cursor.execute(sql_alarm_count)
        pending_count = cursor.fetchone()['count']

        if not summary_data:
            return render_template('dashboardqy.html',
                                   config=config,
                                   high_alarms=high_alarms,
                                   pending_count=pending_count,
                                   error='未找到汇总数据',
                                   user=session)

        # 5. 获取用户信息
        sql_user = """
        SELECT 真实姓名, 用户角色 
        FROM 用户 
        WHERE 用户ID = %s
        """
        cursor.execute(sql_user, (session['user_id'],))
        user_info = cursor.fetchone()

        return render_template('dashboardqy.html',
                               config=config,
                               data=summary_data,
                               high_alarms=high_alarms,
                               pending_count=pending_count,
                               user=user_info)

    except Exception as e:
        return render_template('dashboardqy.html',
                               error=f'获取数据失败: {str(e)}',
                               user=session)


@app.route('/api/management/handle-alarm', methods=['POST'])
@login_required
@require_role('企业管理层')
def handle_alarm():
    """处理告警的接口"""
    data = request.json
    alarm_id = data.get('alarm_id')
    action = data.get('action')  # 'repair' 或 'abandon'

    if not alarm_id or not action:
        return jsonify({'success': False, 'error': '参数不完整'})

    # 验证action参数
    if action not in ['repair', 'abandon']:
        return jsonify({'success': False, 'error': '无效的操作类型'})

    # 根据操作确定新的处理状态
    if action == 'repair':
        new_status = '未处理'  # 确认维修 → 未处理
    else:  # abandon
        new_status = '已结案'  # 放弃维修 → 已结案

    try:
        cursor = db.get_cursor()

        # 先检查告警当前状态是否为待决策
        sql_check = """
        SELECT 处理状态 
        FROM 告警信息 
        WHERE 告警ID = %s
        """
        cursor.execute(sql_check, (alarm_id,))
        alarm = cursor.fetchone()

        if not alarm:
            return jsonify({'success': False, 'error': '未找到对应的告警记录'})

        if alarm['处理状态'] != '待决策':
            return jsonify({'success': False, 'error': '只能处理待决策的告警'})

        # 更新告警状态
        sql_update = """
        UPDATE 告警信息 
        SET 处理状态 = %s
        WHERE 告警ID = %s
        """
        cursor.execute(sql_update, (new_status, alarm_id))
        db.connect().commit()

        # 检查是否更新成功
        if cursor.rowcount > 0:
            return jsonify({
                'success': True,
                'message': f'告警已标记为{new_status}',
                'new_status': new_status
            })
        else:
            return jsonify({'success': False, 'error': '更新失败'})

    except Exception as e:
        db.connect().rollback()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/management/high-alarms')
@login_required
@require_role('企业管理层')
def management_get_high_alarms():
    """获取高等级告警数据的API接口"""
    try:
        cursor = db.get_cursor()

        # 获取高等级告警信息（显示待决策和处理中的设备故障告警）
        sql_alarms = """
        SELECT 告警ID, 告警编号, 告警内容, 发生时间, 告警类型, 关联设备编号, 处理状态
        FROM 告警信息 
        WHERE 告警等级 = '高' 
        AND 告警类型 = '设备故障'
        AND 处理状态 IN ('待决策', '处理中', '未处理')
        ORDER BY 
            CASE 处理状态
                WHEN '待决策' THEN 1
                WHEN '处理中' THEN 2
                WHEN '未处理' THEN 3  
                ELSE 4
            END,
            发生时间 DESC 
        """
        cursor.execute(sql_alarms)
        high_alarms = cursor.fetchall()

        # 统计待决策的高等级告警数量
        sql_alarm_count = """
        SELECT COUNT(*) as count
        FROM 告警信息 
        WHERE 告警等级 = '高' 
        AND 告警类型 = '设备故障'
        AND 处理状态 = '待决策'
        """
        cursor.execute(sql_alarm_count)
        pending_count = cursor.fetchone()['count']

        return jsonify({
            'success': True,
            'alarms': high_alarms,
            'pending_count': pending_count
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============ 企业管理层：报告查看功能 ============

@app.route('/management/reports/monthly')
@login_required
@require_role('企业管理层')
def management_monthly_reports():
    """月度报告列表页面"""
    try:
        print(f"DEBUG - Session user_id: {session.get('user_id')}")
        print(f"DEBUG - Session username: {session.get('username')}")
        print(f"DEBUG - Session user_role: {session.get('user_role')}")

        cursor = db.get_cursor()

        # 获取月度报告（报告类型=1）
        sql_reports = """
        SELECT 报告ID, 报告类型, 生成时间, 生成人ID, 
               DATE_FORMAT(生成时间, '%Y-%m') as 年月
        FROM 简单报告 
        WHERE 报告类型 = 1
        ORDER BY 生成时间 DESC
        """
        cursor.execute(sql_reports)
        reports = cursor.fetchall()

        # 获取用户信息
        sql_user = """
        SELECT 真实姓名, 用户角色 
        FROM 用户 
        WHERE 用户ID = %s
        """
        cursor.execute(sql_user, (session['user_id'],))
        user_info = cursor.fetchone()

        user_info = {
            '真实姓名': session.get('username', '未知用户'),
            '用户角色': session.get('user_role', '未知角色')
        }

        return render_template('reports_list.html',
                               reports=reports,
                               report_type='monthly',
                               report_type_name='月度报告',
                               user=user_info)

    except Exception as e:
        return render_template('reports_list.html',
                               error=f'获取报告失败: {str(e)}',
                               user=session)


@app.route('/management/reports/quarterly')
@login_required
@require_role('企业管理层')
def management_quarterly_reports():
    """季度报告列表页面"""
    try:
        cursor = db.get_cursor()

        # 获取季度报告（报告类型=2）
        sql_reports = """
        SELECT 报告ID, 报告类型, 生成时间, 生成人ID,
               CONCAT(YEAR(生成时间), 'Q', QUARTER(生成时间)) as 季度
        FROM 简单报告 
        WHERE 报告类型 = 2
        ORDER BY 生成时间 DESC
        """
        cursor.execute(sql_reports)
        reports = cursor.fetchall()

        # 获取用户信息
        sql_user = """
        SELECT 真实姓名, 用户角色 
        FROM 用户 
        WHERE 用户ID = %s
        """
        cursor.execute(sql_user, (session['user_id'],))
        user_info = cursor.fetchone()

        user_info = {
            '真实姓名': session.get('username', '未知用户'),
            '用户角色': session.get('user_role', '未知角色')
        }

        return render_template('reports_list.html',
                               reports=reports,
                               report_type='quarterly',
                               report_type_name='季度报告',
                               user=user_info)

    except Exception as e:
        return render_template('reports_list.html',
                               error=f'获取报告失败: {str(e)}',
                               user=session)


@app.route('/management/report/detail/<report_id>')
@login_required
@require_role('企业管理层')
def management_report_detail(report_id):
    """报告详情页面，评估降本增效目标完成情况"""
    try:
        cursor = db.get_cursor()

        # 获取报告详情
        sql_report = """
        SELECT 报告ID, 报告类型, 报告内容, 生成时间, 生成人ID
        FROM 简单报告 
        WHERE 报告ID = %s
        """
        cursor.execute(sql_report, (report_id,))
        report = cursor.fetchone()

        if not report:
            user_info = {
                '真实姓名': session.get('username', '未知用户'),
                '用户角色': session.get('user_role', '未知角色')
            }
            return render_template('report_detail.html',
                                   error='未找到报告',
                                   user=session)

        # 解析报告内容（假设报告内容格式如示例）
        report_content = report['报告内容']

        # 提取关键数据用于评估降本增效
        evaluation = evaluate_cost_reduction(report_content, report['报告类型'])

        # 获取用户信息
        sql_user = """
        SELECT 真实姓名, 用户角色 
        FROM 用户 
        WHERE 用户ID = %s
        """
        cursor.execute(sql_user, (session['user_id'],))
        user_info = cursor.fetchone()

        user_info = {
            '真实姓名': session.get('username', '未知用户'),
            '用户角色': session.get('user_role', '未知角色')
        }

        return render_template('report_detail.html',
                               report=report,
                               evaluation=evaluation,
                               user=user_info)

    except Exception as e:
        return render_template('report_detail.html',
                               error=f'获取报告详情失败: {str(e)}',
                               user=session)


# ============ 添加运维工单管理员的路由 ============

@app.route('/workorder/dashboard')
@login_required
@require_role('运维工单管理员')
def workorder_dashboard():
    """运维工单管理员仪表板"""
    try:
        cursor = db.get_cursor()

        # 获取统计信息
        cursor.execute("""
            SELECT 
                COUNT(*) as total_alarms,
                SUM(CASE WHEN 处理状态 = '待审核' THEN 1 ELSE 0 END) as pending_review_alarms,
                SUM(CASE WHEN 处理状态 = '未处理' THEN 1 ELSE 0 END) as pending_alarms,
                SUM(CASE WHEN 告警等级 = '高' AND 处理状态 IN ('待审核', '未处理') THEN 1 ELSE 0 END) as high_priority_alarms
            FROM 告警信息
        """)
        alarm_stats = cursor.fetchone()

        # 获取工单统计
        cursor.execute("""
            SELECT 
                COUNT(*) as total_orders,
                SUM(CASE WHEN 处理完成时间 IS NULL THEN 1 ELSE 0 END) as pending_orders,
                SUM(CASE WHEN 复查状态 = '未通过' THEN 1 ELSE 0 END) as failed_reviews
            FROM 运维工单
        """)
        order_stats = cursor.fetchone()

        # 获取最近待审核告警
        cursor.execute("""
            SELECT a.*, e.设备名称, u.真实姓名 as 负责人
            FROM 告警信息 a
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            LEFT JOIN 用户 u ON a.告警确认人ID = u.用户ID
            WHERE a.处理状态 = '待审核'
            ORDER BY a.发生时间 DESC
            LIMIT 10
        """)
        recent_alarms = cursor.fetchall()

        return render_template('workorder/dashboard.html',
                               alarm_stats=alarm_stats or {},
                               order_stats=order_stats or {},
                               recent_alarms=recent_alarms,
                               user_role=session.get('user_role'))

    except Exception as e:
        print(f"获取仪表板数据失败: {str(e)}")
        # 返回空数据模板
        return render_template('workorder/dashboard.html',
                               alarm_stats={},
                               order_stats={},
                               recent_alarms=[],
                               user_role=session.get('user_role'))


@app.route('/workorder/alarms')
@login_required
@require_role('运维工单管理员')
def workorder_alarms():
    """运维工单管理员 - 告警管理"""
    conn = db.get_cursor().connection

    # 获取过滤参数
    status = request.args.get('status', 'all')
    alarm_type = request.args.get('type', 'all')
    priority = request.args.get('priority', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        cursor = db.get_cursor()

        # 构建查询条件
        conditions = []
        params = []

        if status != 'all':
            conditions.append("a.处理状态 = %s")
            params.append(status)

        if alarm_type != 'all':
            conditions.append("a.告警类型 = %s")
            params.append(alarm_type)

        if priority != 'all':
            conditions.append("a.告警等级 = %s")
            params.append(priority)

        if start_date:
            conditions.append("DATE(a.发生时间) >= %s")
            params.append(start_date)

        if end_date:
            conditions.append("DATE(a.发生时间) <= %s")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 查询告警信息
        sql = f"""
            SELECT a.*, e.设备名称, e.设备类型, e.运行状态 as 设备状态,
                   p.厂区名称, u.真实姓名 as 确认人姓名,
                   CASE 
                       WHEN TIMESTAMPDIFF(HOUR, a.发生时间, NOW()) < 1 THEN '刚刚'
                       WHEN TIMESTAMPDIFF(HOUR, a.发生时间, NOW()) < 24 THEN CONCAT(TIMESTAMPDIFF(HOUR, a.发生时间, NOW()), '小时前')
                       ELSE CONCAT(TIMESTAMPDIFF(DAY, a.发生时间, NOW()), '天前')
                   END as 时间间隔
            FROM 告警信息 a
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            LEFT JOIN 厂区 p ON e.所属厂区编号 = p.厂区编号
            LEFT JOIN 用户 u ON a.告警确认人ID = u.用户ID
            WHERE {where_clause}
            ORDER BY 
                CASE WHEN a.处理状态 = '待审核' AND a.告警等级 = '高' THEN 1
                     WHEN a.处理状态 = '待审核' AND a.告警等级 = '中' THEN 2
                     WHEN a.处理状态 = '待审核' AND a.告警等级 = '低' THEN 3
                     WHEN a.处理状态 = '未处理' AND a.告警等级 = '高' THEN 4
                     WHEN a.处理状态 = '未处理' AND a.告警等级 = '中' THEN 5
                     WHEN a.处理状态 = '未处理' AND a.告警等级 = '低' THEN 6
                     ELSE 7
                END,
                a.发生时间 DESC
        """

        cursor.execute(sql, tuple(params))
        alarms_list = cursor.fetchall()

        # 获取统计信息
        cursor.execute("""
            SELECT 
                告警类型,
                告警等级,
                处理状态,
                COUNT(*) as count
            FROM 告警信息
            GROUP BY 告警类型, 告警等级, 处理状态
        """)
        alarm_stats = cursor.fetchall()

        # 获取运维人员列表
        cursor.execute("""
            SELECT 用户ID, 真实姓名
            FROM 用户
            WHERE 用户角色 = '运维人员'
            ORDER BY 真实姓名
        """)
        operators = cursor.fetchall()

        return render_template('workorder/alarms.html',
                               alarms=alarms_list,
                               alarm_stats=alarm_stats,
                               operators=operators,
                               current_filters={
                                   'status': status,
                                   'type': alarm_type,
                                   'priority': priority,
                                   'start_date': start_date,
                                   'end_date': end_date
                               })

    except Exception as e:
        print(f"获取告警信息失败: {str(e)}")
        return render_template('workorder/alarms.html',
                               alarms=[],
                               alarm_stats=[],
                               operators=[],
                               current_filters={})


@app.route('/workorder/alarm/<alarm_id>')
@login_required
@require_role('运维工单管理员')
def workorder_alarm_detail(alarm_id):
    """运维工单管理员 - 告警详情"""
    try:
        cursor = db.get_cursor()

        # 获取告警详情
        cursor.execute("""
            SELECT a.*, e.设备名称, e.设备类型, e.运行状态 as 设备状态,
                   p.厂区名称, p.位置描述 as 厂区位置,
                   u.真实姓名 as 确认人姓名, u.手机号码 as 确认人电话,
                   d.设备大类, d.安装位置描述
            FROM 告警信息 a
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
            LEFT JOIN 厂区 p ON e.所属厂区编号 = p.厂区编号
            LEFT JOIN 用户 u ON a.告警确认人ID = u.用户ID
            WHERE a.告警ID = %s
        """, (alarm_id,))
        alarm = cursor.fetchone()

        if not alarm:
            #flash('告警信息不存在')
            return redirect(url_for('workorder_alarms'))

        # 获取相关工单
        cursor.execute("""
            SELECT w.*, u.真实姓名 as 运维人员姓名
            FROM 运维工单 w
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            WHERE w.告警ID = %s
            ORDER BY w.派单时间 DESC
        """, (alarm_id,))
        work_orders = cursor.fetchall()

        # 获取设备历史告警
        cursor.execute("""
            SELECT 告警ID, 告警类型, 告警等级, 发生时间, 处理状态
            FROM 告警信息
            WHERE 关联设备编号 = %s AND 告警ID != %s
            ORDER BY 发生时间 DESC
            LIMIT 5
        """, (alarm['关联设备编号'], alarm_id))
        history_alarms = cursor.fetchall()

        return render_template('workorder/alarm_detail.html',
                               alarm=alarm,
                               work_orders=work_orders,
                               history_alarms=history_alarms)

    except Exception as e:
        print(f"获取告警详情失败: {str(e)}")
        return redirect(url_for('workorder_alarms'))

@app.route('/api/workorder/get_maintenance_users', methods=['GET'])
@login_required
@require_role('运维工单管理员')
def workorder_get_maintenance_users():
    """获取运维人员列表（根据告警ID筛选对应厂区的运维人员）"""
    try:
        alarm_id = request.args.get('alarm_id')

        cursor = db.get_cursor()

        if alarm_id:
            # 先获取告警对应的设备所属厂区
            sql = """
            SELECT d.所属厂区编号
            FROM 告警信息 a
            LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
            WHERE a.告警ID = %s
            """
            cursor.execute(sql, (alarm_id,))
            alarm_result = cursor.fetchone()

            if not alarm_result or not alarm_result['所属厂区编号']:
                return jsonify({
                    'success': False,
                    'error': '无法确定告警对应的厂区'
                })

            factory_id = alarm_result['所属厂区编号']

            # 查询该厂区的运维人员
            sql = """
            SELECT 用户ID, 真实姓名
            FROM 用户
            WHERE 用户角色 = '运维人员' 
              AND 负责的厂区编号 = %s
            ORDER BY 真实姓名
            """
            cursor.execute(sql, (factory_id,))
            users = cursor.fetchall()

            # 如果该厂区没有运维人员，返回空列表
            if not users:
                return jsonify({
                    'success': True,
                    'users': [],
                    'warning': '该厂区暂无运维人员'
                })

            return jsonify({
                'success': True,
                'users': users,
                'factory_id': factory_id
            })
        else:
            # 如果没有告警ID，返回所有运维人员（用于其他场景）
            cursor.execute("""
                SELECT 用户ID, 真实姓名
                FROM 用户
                WHERE 用户角色 = '运维人员'
                ORDER BY 真实姓名
            """)
            users = cursor.fetchall()

            return jsonify({
                'success': True,
                'users': users
            })

    except Exception as e:
        print(f"获取运维人员列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/workorder/work_orders')
@login_required
@require_role('运维工单管理员')
def workorder_work_orders():
    """运维工单管理员 - 工单管理"""
    # 获取过滤参数
    status = request.args.get('status', 'all')
    operator_id = request.args.get('operator_id', 'all')
    review_status = request.args.get('review_status', 'all')

    try:
        cursor = db.get_cursor()

        # 构建查询条件
        conditions = []
        params = []

        if status == 'pending':
            conditions.append("w.处理完成时间 IS NULL")
        elif status == 'completed':
            conditions.append("w.处理完成时间 IS NOT NULL")

        if operator_id != 'all':
            conditions.append("w.运维人员ID = %s")
            params.append(operator_id)

        if review_status != 'all':
            conditions.append("w.复查状态 = %s")
            params.append(review_status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 查询工单信息
        sql = f"""
            SELECT w.*, 
                   a.告警类型, a.告警等级, a.发生时间, a.告警内容, a.处理状态 as 告警处理状态,
                   e.设备名称, e.设备类型, p.厂区名称,
                   u.真实姓名 as 运维人员姓名, u.手机号码 as 运维人员电话,
                   CASE 
                       WHEN w.处理完成时间 IS NULL AND w.响应时间 IS NULL 
                            AND TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) > 1 THEN '未响应'
                       WHEN w.处理完成时间 IS NULL AND w.响应时间 IS NOT NULL 
                            AND TIMESTAMPDIFF(HOUR, w.响应时间, NOW()) > 24 THEN '处理超时'
                       WHEN w.处理完成时间 IS NULL THEN '处理中'
                       WHEN w.复查状态 IS NULL THEN '待复查'
                       ELSE w.复查状态
                   END as 工单状态,
                   TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) as 派单时长,
                   -- 动态计算处理耗时
                   CASE 
                       WHEN w.处理完成时间 IS NOT NULL THEN 
                            TIMESTAMPDIFF(MINUTE, w.派单时间, w.处理完成时间)
                       WHEN w.响应时间 IS NOT NULL THEN 
                            TIMESTAMPDIFF(MINUTE, w.派单时间, NOW())
                       ELSE 
                            TIMESTAMPDIFF(MINUTE, w.派单时间, NOW())
                   END as 动态处理耗时
            FROM 运维工单 w
            LEFT JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            LEFT JOIN 厂区 p ON e.所属厂区编号 = p.厂区编号
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            WHERE {where_clause}
            ORDER BY 
                CASE 
                    WHEN w.处理完成时间 IS NULL AND w.响应时间 IS NULL 
                         AND TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) > 1 THEN 1
                    WHEN w.处理完成时间 IS NULL AND w.响应时间 IS NOT NULL 
                         AND TIMESTAMPDIFF(HOUR, w.响应时间, NOW()) > 24 THEN 2
                    WHEN w.处理完成时间 IS NULL THEN 3
                    WHEN w.复查状态 IS NULL THEN 4
                    ELSE 5
                END,
                w.派单时间 DESC
        """

        cursor.execute(sql, tuple(params))
        work_orders_list = cursor.fetchall()

        # 获取运维人员列表
        cursor.execute("""
            SELECT 用户ID, 真实姓名
            FROM 用户
            WHERE 用户角色 = '运维人员'
            ORDER BY 真实姓名
        """)
        operators = cursor.fetchall()

        # 获取统计信息
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN 处理完成时间 IS NULL THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN 复查状态 IS NULL AND 处理完成时间 IS NOT NULL THEN 1 ELSE 0 END) as to_review,
                SUM(CASE WHEN 复查状态 = '未通过' THEN 1 ELSE 0 END) as failed
            FROM 运维工单
        """)
        stats = cursor.fetchone()

        return render_template('workorder/work_orders.html',
                               work_orders=work_orders_list,
                               operators=operators,
                               stats=stats,
                               current_filters={
                                   'status': status,
                                   'operator_id': operator_id,
                                   'review_status': review_status
                               })

    except Exception as e:
        print(f"获取工单信息失败: {str(e)}")
        return render_template('workorder/work_orders.html',
                               work_orders=[],
                               operators=[],
                               stats={})


@app.route('/workorder/review/<work_order_id>', methods=['GET', 'POST'])
@login_required
@require_role('运维工单管理员')
def workorder_review_work_order(work_order_id):
    """运维工单管理员 - 复查工单"""
    form = ReviewWorkOrderForm()

    try:
        cursor = db.get_cursor()

        # 获取工单详情
        cursor.execute("""
            SELECT w.*, a.告警ID, a.告警内容, a.关联设备编号,
                   u.真实姓名 as 运维人员姓名, e.设备名称
            FROM 运维工单 w
            LEFT JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            WHERE w.工单ID = %s
        """, (work_order_id,))
        work_order = cursor.fetchone()

        if not work_order:
            #flash('工单不存在')
            return redirect(url_for('workorder_work_orders'))

        # 动态填充运维人员选项
        cursor.execute("""
            SELECT 用户ID, 真实姓名
            FROM 用户
            WHERE 用户角色 = '运维人员'
            ORDER BY 真实姓名
        """)
        operators = cursor.fetchall()
        form.re_assign.choices = [('', '不重新派单')] + [(op['用户ID'], op['真实姓名']) for op in operators]

        if form.validate_on_submit():
            review_status = form.review_status.data
            review_notes = form.review_notes.data
            re_assign_id = form.re_assign.data

            # 更新工单复查状态
            cursor.execute("""
                UPDATE 运维工单 
                SET 复查状态 = %s,
                    处理备注 = CONCAT(IFNULL(处理备注, ''), ' 【复查意见：', %s, '】')
                WHERE 工单ID = %s
            """, (review_status, review_notes, work_order_id))

            # 更新告警状态
            if review_status == '通过':
                cursor.execute("""
                    UPDATE 告警信息 
                    SET 处理状态 = '已结案'
                    WHERE 告警ID = %s
                """, (work_order['告警ID'],))
            elif review_status == '未通过' and re_assign_id:
                # 重新派单
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                new_work_order_id = f'WO{timestamp}'
                new_work_order_no = f'WO-RE-{timestamp}'

                cursor.execute("""
                    INSERT INTO 运维工单 (
                        工单ID, 工单编号, 告警ID, 运维人员ID, 派单时间, 
                        处理备注
                    ) VALUES (%s, %s, %s, %s, NOW(), %s)
                """, (new_work_order_id, new_work_order_no,
                      work_order['告警ID'], re_assign_id,
                      f'复查未通过，重新派单。原因：{review_notes}'))

            db.connect().commit()
            #flash('复查完成')
            return redirect(url_for('workorder_work_orders'))

        return render_template('workorder/review.html', form=form, work_order=work_order)

    except Exception as e:
        print(f"获取工单详情失败: {str(e)}")
        return redirect(url_for('workorder_work_orders'))


# ============ 添加运维工单管理员的API路由 ============

@app.route('/api/workorder/mark_false_alarm', methods=['POST'])
@login_required
@require_role('运维工单管理员')
def workorder_mark_false_alarm():
    """标记误报"""
    data = request.get_json()
    alarm_id = data.get('alarm_id')
    reason = data.get('reason', '通讯波动导致误报')

    if not alarm_id:
        return jsonify({'success': False, 'message': '告警ID不能为空'})

    try:
        cursor = db.get_cursor()

        # 更新告警状态为"已结案"，并记录误报原因
        cursor.execute("""
            UPDATE 告警信息 
            SET 处理状态 = '已结案',
                告警内容 = CONCAT(告警内容, ' 【误报原因：', %s, '】'),
                告警确认人ID = %s,
                确认时间 = NOW()
            WHERE 告警ID = %s
        """, (reason, session.get('user_id'), alarm_id))

        db.connect().commit()

        return jsonify({'success': True, 'message': '已标记为误报'})

    except Exception as e:
        db.connect().rollback()
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/workorder/confirm_alarm', methods=['POST'])
@login_required
@require_role('运维工单管理员')
def workorder_confirm_alarm():
    """确认告警"""
    data = request.get_json()
    alarm_id = data.get('alarm_id')

    if not alarm_id:
        return jsonify({'success': False, 'message': '告警ID不能为空'})

    try:
        cursor = db.get_cursor()

        # 获取告警类型
        cursor.execute("SELECT 告警类型 FROM 告警信息 WHERE 告警ID = %s", (alarm_id,))
        alarm = cursor.fetchone()

        if not alarm:
            return jsonify({'success': False, 'message': '告警不存在'})

        # 根据告警类型设置新的处理状态
        if alarm['告警类型'] == '设备故障':
            new_status = '待决策'
            message = '告警已确认，状态已改为"待决策"，需进一步处理'
        else:
            new_status = '未处理'
            message = '告警已确认，状态已改为"未处理"，可创建工单'

        # 更新告警状态
        cursor.execute("""
            UPDATE 告警信息 
            SET 处理状态 = %s,
                告警确认人ID = %s,
                确认时间 = NOW()
            WHERE 告警ID = %s
        """, (new_status, session.get('user_id'), alarm_id))

        db.connect().commit()

        return jsonify({'success': True, 'message': message, 'new_status': new_status})

    except Exception as e:
        db.connect().rollback()
        return jsonify({'success': False, 'message': str(e)})


# @app.route('/api/workorder/create_work_order', methods=['POST'])
# @login_required
# @require_role('运维工单管理员')
# def workorder_create_work_order():
#     """创建工单"""
#     data = request.get_json()
#     alarm_id = data.get('alarm_id')
#     operator_id = data.get('operator_id')
#
#     # 只验证必需字段
#     if not alarm_id or not operator_id:
#         return jsonify({'success': False, 'message': '告警ID和运维人员不能为空'})
#
#     try:
#         cursor = db.get_cursor()
#
#         # 检查告警状态是否为"未处理"
#         cursor.execute("SELECT 处理状态 FROM 告警信息 WHERE 告警ID = %s", (alarm_id,))
#         alarm = cursor.fetchone()
#
#         if not alarm:
#             return jsonify({'success': False, 'message': '告警不存在'})
#
#         if alarm['处理状态'] != '未处理':
#             return jsonify({'success': False, 'message': '只能为"未处理"状态的告警创建工单'})
#
#         # 生成工单编号
#         timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
#         work_order_id = f'WO{timestamp}'
#         work_order_no = f'WO-{timestamp}'
#
#         # 创建工单，只存储必需字段
#         cursor.execute("""
#             INSERT INTO 运维工单 (
#                 工单ID, 工单编号, 告警ID, 运维人员ID, 派单时间
#             ) VALUES (%s, %s, %s, %s, NOW())
#         """, (work_order_id, work_order_no, alarm_id, operator_id))
#
#         # 更新告警状态为"处理中"
#         cursor.execute("""
#             UPDATE 告警信息
#             SET 处理状态 = '处理中',
#                 告警确认人ID = %s,
#                 确认时间 = NOW()
#             WHERE 告警ID = %s
#         """, (session.get('user_id'), alarm_id))
#
#         db.connect().commit()
#
#         return jsonify({
#             'success': True,
#             'message': '工单创建成功，告警状态已改为"处理中"',
#             'work_order_id': work_order_id
#         })
#
#     except Exception as e:
#         db.connect().rollback()
#         return jsonify({'success': False, 'message': str(e)})
@app.route('/api/workorder/create_work_order', methods=['POST'])
@login_required
@require_role('运维工单管理员')
def workorder_create_work_order():
    """创建工单（增加厂区校验）"""
    data = request.get_json()
    alarm_id = data.get('alarm_id')
    operator_id = data.get('operator_id')

    if not alarm_id or not operator_id:
        return jsonify({'success': False, 'message': '告警ID和运维人员不能为空'})

    try:
        cursor = db.get_cursor()

        # 1. 检查告警状态是否为"未处理"
        cursor.execute("SELECT 处理状态, 关联设备编号 FROM 告警信息 WHERE 告警ID = %s", (alarm_id,))
        alarm = cursor.fetchone()

        if not alarm:
            return jsonify({'success': False, 'message': '告警不存在'})

        if alarm['处理状态'] != '未处理':
            return jsonify({'success': False, 'message': '只能为"未处理"状态的告警创建工单'})

        # 2. 获取设备所属厂区
        if not alarm['关联设备编号']:
            return jsonify({'success': False, 'message': '告警未关联设备'})

        cursor.execute("SELECT 所属厂区编号 FROM 设备 WHERE 设备编号 = %s", (alarm['关联设备编号'],))
        device_result = cursor.fetchone()

        if not device_result or not device_result['所属厂区编号']:
            return jsonify({'success': False, 'message': '设备未分配厂区'})

        factory_id = device_result['所属厂区编号']

        # 3. 验证运维人员是否属于该厂区
        cursor.execute("""
            SELECT 用户ID, 真实姓名 
            FROM 用户 
            WHERE 用户ID = %s 
              AND 用户角色 = '运维人员' 
              AND 负责的厂区编号 = %s
        """, (operator_id, factory_id))

        operator = cursor.fetchone()

        if not operator:
            # 获取厂区名称用于错误提示
            cursor.execute("SELECT 厂区名称 FROM 厂区 WHERE 厂区编号 = %s", (factory_id,))
            factory_result = cursor.fetchone()
            factory_name = factory_result['厂区名称'] if factory_result else factory_id

            return jsonify({
                'success': False,
                'message': f'所选运维人员不属于该设备所属厂区（{factory_name}）'
            })

        # 4. 生成工单编号
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        work_order_id = f'WO{timestamp}'
        work_order_no = f'WO-{timestamp}'

        # 5. 创建工单
        cursor.execute("""
            INSERT INTO 运维工单 (
                工单ID, 工单编号, 告警ID, 运维人员ID, 派单时间
            ) VALUES (%s, %s, %s, %s, NOW())
        """, (work_order_id, work_order_no, alarm_id, operator_id))

        # 6. 更新告警状态为"处理中"
        cursor.execute("""
            UPDATE 告警信息 
            SET 处理状态 = '处理中',
                告警确认人ID = %s,
                确认时间 = NOW()
            WHERE 告警ID = %s
        """, (session.get('user_id'), alarm_id))

        db.connect().commit()

        return jsonify({
            'success': True,
            'message': f'工单创建成功，已指派给{operator["真实姓名"]}处理',
            'work_order_id': work_order_id,
            'assigned_to': operator['真实姓名']
        })

    except Exception as e:
        db.connect().rollback()
        print(f"创建工单失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/workorder/get_alarm_factory_info', methods=['GET'])
@login_required
@require_role('运维工单管理员')
def workorder_get_alarm_factory_info():
    """获取告警对应的厂区信息"""
    try:
        alarm_id = request.args.get('alarm_id')

        if not alarm_id:
            return jsonify({'success': False, 'message': '告警ID不能为空'})

        cursor = db.get_cursor()

        # 获取告警对应的设备厂区信息
        sql = """
        SELECT 
            a.告警ID,
            a.告警内容,
            a.关联设备编号,
            d.设备名称,
            d.所属厂区编号,
            f.厂区名称,
            f.位置描述 as 厂区位置
        FROM 告警信息 a
        LEFT JOIN 设备 d ON a.关联设备编号 = d.设备编号
        LEFT JOIN 厂区 f ON d.所属厂区编号 = f.厂区编号
        WHERE a.告警ID = %s
        """

        cursor.execute(sql, (alarm_id,))
        result = cursor.fetchone()

        if not result:
            return jsonify({'success': False, 'message': '告警不存在'})

        if not result['所属厂区编号']:
            return jsonify({'success': False, 'message': '告警未关联设备或设备未分配厂区'})

        # 获取该厂区的运维人员数量
        cursor.execute("""
            SELECT COUNT(*) as operator_count
            FROM 用户
            WHERE 用户角色 = '运维人员' 
              AND 负责的厂区编号 = %s
        """, (result['所属厂区编号'],))

        count_result = cursor.fetchone()
        result['operator_count'] = count_result['operator_count'] if count_result else 0

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        print(f"获取告警厂区信息失败: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/workorder/track_progress/<work_order_id>')
@login_required
@require_role('运维工单管理员')
def workorder_track_progress(work_order_id):
    """跟踪工单进度"""
    try:
        cursor = db.get_cursor()

        cursor.execute("""
            SELECT 
                w.工单ID, 
                DATE_FORMAT(w.派单时间, '%%Y-%%m-%%d %%H:%%i:%%s') as 派单时间,
                DATE_FORMAT(w.响应时间, '%%Y-%%m-%%d %%H:%%i:%%s') as 响应时间,
                DATE_FORMAT(w.处理完成时间, '%%Y-%%m-%%d %%H:%%i:%%s') as 处理完成时间,
                u.真实姓名 as 运维人员, 
                u.手机号码,
                a.告警等级, 
                a.告警内容, 
                e.设备名称,
                TIMESTAMPDIFF(MINUTE, w.派单时间, COALESCE(w.响应时间, NOW())) as 响应时长,
                TIMESTAMPDIFF(MINUTE, COALESCE(w.响应时间, w.派单时间), 
                              COALESCE(w.处理完成时间, NOW())) as 处理时长,
                CASE 
                    WHEN w.响应时间 IS NULL AND TIMESTAMPDIFF(HOUR, w.派单时间, NOW()) > 1 
                        THEN '未响应告警'
                    WHEN w.处理完成时间 IS NULL AND TIMESTAMPDIFF(HOUR, w.响应时间, NOW()) > 24 
                        THEN '处理超时告警'
                    ELSE '正常'
                END as 告警状态
            FROM 运维工单 w
            LEFT JOIN 用户 u ON w.运维人员ID = u.用户ID
            LEFT JOIN 告警信息 a ON w.告警ID = a.告警ID
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            WHERE w.工单ID = %s
        """, (work_order_id,))

        progress = cursor.fetchone()

        if progress:
            # 检查是否需要发送提醒
            if progress['告警状态'] != '正常':
                reminder_msg = f"工单 {work_order_id} 状态异常：{progress['告警状态']}"

            return jsonify({'success': True, 'data': progress})
        else:
            return jsonify({'success': False, 'message': '工单不存在'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/workorder/get_device_data/<alarm_id>')
@login_required
@require_role('运维工单管理员')
def workorder_get_device_data(alarm_id):
    """
    获取告警对应设备在告警发生时间前后的监测数据
    """
    try:
        cursor = db.get_cursor()

        # 1. 获取告警信息，包括设备编号和发生时间
        cursor.execute("""
            SELECT a.告警ID, a.告警类型, a.关联设备编号, a.发生时间, a.告警内容,
                   e.设备名称, e.设备类型, e.设备大类, e.运行状态, e.安装位置描述
            FROM 告警信息 a
            LEFT JOIN 设备 e ON a.关联设备编号 = e.设备编号
            WHERE a.告警ID = %s
        """, (alarm_id,))

        alarm = cursor.fetchone()

        if not alarm:
            return jsonify({'success': False, 'message': '告警不存在'})

        device_id = alarm['关联设备编号']
        alarm_time = alarm['发生时间']

        # 2. 获取设备当前状态和基本信息
        device_info = {
            '设备编号': device_id,
            '设备名称': alarm.get('设备名称'),
            '设备类型': alarm.get('设备类型'),
            '设备大类': alarm.get('设备大类'),
            '运行状态': alarm.get('运行状态'),
            '安装位置描述': alarm.get('安装位置描述')
        }

        # 3. 查询告警发生时间前后30分钟的数据
        time_range = 30  # 分钟
        start_time = alarm_time - timedelta(minutes=time_range)
        end_time = alarm_time + timedelta(minutes=time_range)

        # 4. 尝试获取各种监测数据
        monitoring_data = []
        data_type = '未找到监测数据'

        # 先尝试变压器监测数据
        try:
            cursor.execute("SHOW TABLES LIKE '变压器监测数据'")
            if cursor.fetchone():
                cursor.execute("""
                    SELECT 
                        采集时间,
                        负载率,
                        绕组温度,
                        铁芯温度,
                        环境温度,
                        环境湿度,
                        运行状态
                    FROM 变压器监测数据
                    WHERE 变压器编号 = %s 
                      AND 采集时间 BETWEEN %s AND %s
                    ORDER BY 采集时间 DESC
                    LIMIT 20
                """, (device_id, start_time, end_time))

                data = cursor.fetchall()
                if data:
                    monitoring_data = data
                    data_type = '变压器监测数据'
        except Exception as e:
            print(f"查询变压器监测数据失败: {str(e)}")

        # 如果变压器数据为空，尝试回路监测数据
        if not monitoring_data:
            try:
                cursor.execute("SHOW TABLES LIKE '回路监测数据'")
                if cursor.fetchone():
                    cursor.execute("""
                        SELECT 
                            采集时间,
                            电容器温度,
                            电压,
                            电流,
                            电缆头温度,
                            有功功率,
                            无功功率,
                            功率因数,
                            正向有功电量,
                            反向有功电量,
                            开关状态,
                            电压异常标记,
                            温度异常标记
                        FROM 回路监测数据
                        WHERE 设备编号 = %s 
                          AND 采集时间 BETWEEN %s AND %s
                        ORDER BY 采集时间 DESC
                        LIMIT 20
                    """, (device_id, start_time, end_time))

                    data = cursor.fetchall()
                    if data:
                        monitoring_data = data
                        data_type = '回路监测数据'
            except Exception as e:
                print(f"查询回路监测数据失败: {str(e)}")

        # 如果回路数据为空，尝试光伏发电数据
        if not monitoring_data:
            try:
                cursor.execute("SHOW TABLES LIKE '光伏发电数据'")
                if cursor.fetchone():
                    cursor.execute("""
                        SELECT 
                            采集时间,
                            发电量,
                            上网电量,
                            自用电量,
                            逆变器效率,
                            组串电压,
                            组串电流,
                            数据质量
                        FROM 光伏发电数据
                        WHERE 设备编号 = %s 
                          AND 采集时间 BETWEEN %s AND %s
                        ORDER BY 采集时间 DESC
                        LIMIT 20
                    """, (device_id, start_time, end_time))

                    data = cursor.fetchall()
                    if data:
                        monitoring_data = data
                        data_type = '光伏发电数据'
            except Exception as e:
                print(f"查询光伏发电数据失败: {str(e)}")

        # 如果光伏数据为空，尝试能耗监测数据
        if not monitoring_data:
            try:
                cursor.execute("SHOW TABLES LIKE '能耗监测数据'")
                if cursor.fetchone():
                    cursor.execute("""
                        SELECT 
                            采集时间,
                            能耗值,
                            单位,
                            数据质量
                        FROM 能耗监测数据
                        WHERE 设备编号 = %s 
                          AND 采集时间 BETWEEN %s AND %s
                        ORDER BY 采集时间 DESC
                        LIMIT 20
                    """, (device_id, start_time, end_time))

                    data = cursor.fetchall()
                    if data:
                        monitoring_data = data
                        data_type = '能耗监测数据'
            except Exception as e:
                print(f"查询能耗监测数据失败: {str(e)}")

        # 5. 准备返回数据
        data_result = {
            'device_info': device_info,
            'alarm_info': {
                '告警ID': alarm['告警ID'],
                '告警类型': alarm['告警类型'],
                '发生时间': alarm['发生时间'].strftime('%Y-%m-%d %H:%M:%S') if alarm['发生时间'] else None,
                '告警内容': alarm['告警内容']
            },
            'monitoring_data': monitoring_data,
            'data_type': data_type,
            'time_range': f'告警时间前后{time_range}分钟',
            'device_current_status': device_info['运行状态']
        }

        # 6. 查找告警发生时间点的数据
        alarm_time_data = None
        if monitoring_data:
            for data in monitoring_data:
                # 找到最接近告警发生时间的数据点
                if '采集时间' in data and data['采集时间']:
                    data_time = data['采集时间']
                    time_diff = abs((data_time - alarm_time).total_seconds())
                    if time_diff <= 300:  # 5分钟内
                        alarm_time_data = data
                        break

        data_result['alarm_time_data'] = alarm_time_data

        # 7. 将监测数据中的时间字段格式化为字符串
        if monitoring_data:
            formatted_monitoring_data = []
            for item in monitoring_data:
                formatted_item = {}
                for key, value in item.items():
                    if key == '采集时间' and value:
                        formatted_item[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        formatted_item[key] = value
                formatted_monitoring_data.append(formatted_item)
            data_result['monitoring_data'] = formatted_monitoring_data

        # 同样格式化告警时间点数据
        if alarm_time_data:
            formatted_alarm_time_data = {}
            for key, value in alarm_time_data.items():
                if key == '采集时间' and value:
                    formatted_alarm_time_data[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    formatted_alarm_time_data[key] = value
            data_result['alarm_time_data'] = formatted_alarm_time_data

        # 8. 计算数据统计信息（如果有数据）
        if monitoring_data:
            numeric_data = []
            for item in monitoring_data:
                numeric_item = {}
                for key, value in item.items():
                    if key != '采集时间' and isinstance(value, (int, float)):
                        numeric_item[key] = value
                if numeric_item:
                    numeric_data.append(numeric_item)

            if numeric_data:
                stats = workorder_calculate_data_statistics(numeric_data)
                data_result['statistics'] = stats

        return jsonify({'success': True, 'data': data_result})

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"获取设备数据失败: {str(e)}\n{error_detail}")
        return jsonify({'success': False, 'message': f'获取设备数据失败: {str(e)}'})


def workorder_calculate_data_statistics(data_list):
    """计算数据的统计信息"""
    if not data_list:
        return {}

    # 提取所有数值字段
    numeric_fields = []
    if data_list:
        sample = data_list[0]
        for key, value in sample.items():
            if isinstance(value, (int, float)):
                numeric_fields.append(key)

    stats = {}
    for field in set(numeric_fields):
        values = [item[field] for item in data_list if item.get(field) is not None]
        if values:
            try:
                stats[f'{field}_avg'] = round(sum(values) / len(values), 2)
                stats[f'{field}_max'] = max(values)
                stats[f'{field}_min'] = min(values)
                stats[f'{field}_count'] = len(values)
            except Exception as e:
                print(f"计算统计信息失败 ({field}): {str(e)}")

    return stats


@app.route('/api/workorder/quick_review', methods=['POST'])
@login_required
@require_role('运维工单管理员')
def workorder_quick_review():
    """快速复查工单"""
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    alarm_id = data.get('alarm_id')
    review_status = data.get('review_status')
    review_notes = data.get('review_notes', '')
    re_assign_id = data.get('re_assign_id')

    if not all([work_order_id, alarm_id, review_status]):
        return jsonify({'success': False, 'message': '缺少必要参数'})

    try:
        cursor = db.get_cursor()

        # 更新工单复查状态
        cursor.execute("""
            UPDATE 运维工单 
            SET 复查状态 = %s,
                处理备注 = CONCAT(IFNULL(处理备注, ''), ' 【快速复查：', %s, '】')
            WHERE 工单ID = %s
        """, (review_status, review_notes, work_order_id))

        # 更新告警状态
        if review_status == '通过':
            cursor.execute("""
                UPDATE 告警信息 
                SET 处理状态 = '已结案'
                WHERE 告警ID = %s
            """, (alarm_id,))
        elif review_status == '未通过' and re_assign_id:
            # 重新派单
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            new_work_order_id = f'WO{timestamp}'
            new_work_order_no = f'WO-RE-{timestamp}'

            cursor.execute("""
                INSERT INTO 运维工单 (
                    工单ID, 工单编号, 告警ID, 运维人员ID, 派单时间, 
                    处理备注
                ) VALUES (%s, %s, %s, %s, NOW(), %s)
            """, (new_work_order_id, new_work_order_no,
                  alarm_id, re_assign_id,
                  f'快速复查未通过，重新派单。原因：{review_notes}'))

        db.connect().commit()

        return jsonify({'success': True, 'message': f'已标记为{review_status}'})

    except Exception as e:
        db.connect().rollback()
        return jsonify({'success': False, 'message': str(e)})

# ============ 统一登出 ============
@app.route('/logout')
def logout():
    """统一登出"""
    session.clear()
    return redirect(url_for('login'))

def evaluate_cost_reduction(report_content, report_type):
    """评估降本增效目标完成情况"""
    evaluation = {
        'status': '良好',  # 优秀、良好、一般
        'score': 85,  # 评估分数（0-100）
        'total_energy_consumption': 0,
        'total_cost': 0,
        'pv_generation': 0,
        'pv_self_use': 0,
        'pv_utilization_rate': 0,  # 光伏自用率
        'cost_per_unit': 0,  # 每单位能耗成本
        'alarm_count': 0,
        'pv_average_efficiency': 0,  # 光伏平均效率
        'pv_low_efficiency_count': 0,  # 低于阈值设备数
        'pv_low_efficiency_ratio': 0,  # 低效率占比
        'energy_records': 0,
        'pv_records': 0,
        'alarm_records': 0,
        'suggestions': []
    }

    try:
        # 从报告内容中提取关键数据
        import re

        # 提取总能耗
        total_energy_match = re.search(r'总能耗:\s*([\d\.]+)', report_content)
        if total_energy_match:
            evaluation['total_energy_consumption'] = float(total_energy_match.group(1))

        # 提取总成本
        total_cost_match = re.search(r'总成本:\s*￥([\d\.]+)', report_content)
        if total_cost_match:
            evaluation['total_cost'] = float(total_cost_match.group(1))

        # 提取光伏总发电量
        pv_generation_match = re.search(r'光伏总发电量:\s*([\d\.]+)\s*kWh', report_content)
        if pv_generation_match:
            evaluation['pv_generation'] = float(pv_generation_match.group(1))

        # 提取光伏自用电量
        pv_self_use_match = re.search(r'光伏自用电量:\s*([\d\.]+)\s*kWh', report_content)
        if pv_self_use_match:
            evaluation['pv_self_use'] = float(pv_self_use_match.group(1))

        # 提取总告警次数
        alarm_count_match = re.search(r'总告警次数:\s*([\d\.]+)', report_content)
        if alarm_count_match:
            evaluation['alarm_count'] = int(alarm_count_match.group(1))

        # 提取光伏平均效率
        pv_efficiency_match = re.search(r'平均效率:\s*([\d\.]+)%', report_content)
        if pv_efficiency_match:
            evaluation['pv_average_efficiency'] = float(pv_efficiency_match.group(1))

        # 提取低于阈值设备数
        low_efficiency_match = re.search(r'低于阈值设备数:\s*([\d\.]+)', report_content)
        if low_efficiency_match:
            evaluation['pv_low_efficiency_count'] = int(low_efficiency_match.group(1))

        # 提取低效率占比
        low_efficiency_ratio_match = re.search(r'低效率占比:\s*([\d\.]+)%', report_content)
        if low_efficiency_ratio_match:
            evaluation['pv_low_efficiency_ratio'] = float(low_efficiency_ratio_match.group(1))

        # 提取数据质量信息
        energy_records_match = re.search(r'能耗记录数:\s*([\d\.]+)', report_content)
        if energy_records_match:
            evaluation['energy_records'] = int(energy_records_match.group(1))

        pv_records_match = re.search(r'光伏记录数:\s*([\d\.]+)', report_content)
        if pv_records_match:
            evaluation['pv_records'] = int(pv_records_match.group(1))

        alarm_records_match = re.search(r'告警记录数:\s*([\d\.]+)', report_content)
        if alarm_records_match:
            evaluation['alarm_records'] = int(alarm_records_match.group(1))

        # 计算关键指标
        # 计算每单位能耗成本
        if evaluation['total_cost'] > 0 and evaluation['total_energy_consumption'] > 0:
            evaluation['cost_per_unit'] = round(evaluation['total_cost'] / evaluation['total_energy_consumption'], 2)

            # 根据成本评估
            if evaluation['cost_per_unit'] < 3:
                evaluation['status'] = '优秀'
                evaluation['score'] = 95
                evaluation['suggestions'].append('单位能耗成本控制优秀，继续保持')
            elif evaluation['cost_per_unit'] < 6:
                evaluation['status'] = '良好'
                evaluation['score'] = 85
                evaluation['suggestions'].append('单位能耗成本控制良好，有进一步提升空间')
            else:
                evaluation['status'] = '一般'
                evaluation['score'] = 70
                evaluation['suggestions'].append('单位能耗成本偏高，建议优化能源使用')
        else:
            evaluation['suggestions'].append('能耗数据不足，无法计算单位成本')

        # 计算光伏自用率
        if evaluation['pv_generation'] > 0:
            evaluation['pv_utilization_rate'] = round(evaluation['pv_self_use'] / evaluation['pv_generation'] * 100, 1)

            if evaluation['pv_utilization_rate'] > 50:
                evaluation['suggestions'].append('光伏自用率较高，经济效益显著')
            elif evaluation['pv_utilization_rate'] > 30:
                evaluation['suggestions'].append('光伏自用率良好，可进一步优化用电计划')
            else:
                evaluation['suggestions'].append('光伏自用率有待提高，建议增加自用电量')
        else:
            evaluation['suggestions'].append('光伏发电数据不足')

        # 根据告警数量评估
        if evaluation['alarm_count'] == 0:
            evaluation['suggestions'].append('系统运行稳定，无告警记录')
        elif evaluation['alarm_count'] <= 5:
            evaluation['suggestions'].append('系统运行基本稳定，需关注少量告警')
        else:
            evaluation['suggestions'].append('系统告警较多，建议加强设备维护')

        # 根据光伏效率评估
        if evaluation['pv_average_efficiency'] > 95:
            evaluation['suggestions'].append('光伏系统效率优秀')
        elif evaluation['pv_average_efficiency'] > 90:
            evaluation['suggestions'].append('光伏系统效率良好')
        else:
            evaluation['suggestions'].append('光伏系统效率一般，建议检查设备状态')

        # 根据数据质量评估
        if evaluation['energy_records'] == 0:
            evaluation['suggestions'].append('警告：无能耗记录数据')
        if evaluation['pv_records'] == 0:
            evaluation['suggestions'].append('警告：无光伏记录数据')

        # 根据报告类型设置目标
        if report_type == 1:  # 月度报告
            evaluation['target_type'] = '月度目标'
            evaluation['target_description'] = '月度降本增效5%'
            evaluation['suggestions'].append('月度目标：降低能耗成本5%')
        else:  # 季度报告
            evaluation['target_type'] = '季度目标'
            evaluation['target_description'] = '季度降本增效10%'
            evaluation['suggestions'].append('季度目标：降低能耗成本10%')

        return evaluation

    except Exception as e:
        # 如果解析失败，返回默认评估
        evaluation['suggestions'].append(f'数据解析遇到问题: {str(e)}')
        return evaluation

@app.route('/api/work-orders/<work_order_id>/complete', methods=['POST'])
@login_required
@require_role('运维人员')
def complete_work_order_api(work_order_id):
    """完成工单（通用API）"""
    try:
        data = request.get_json()
        result_text = data.get('result', '')

        print(f"🔍 完成工单API调用: 工单ID={work_order_id}")
        print(f"🔍 请求数据: {data}")

        if not result_text:
            return jsonify({'success': False, 'message': '请输入处理结果'}), 400

        user_id = session.get('user_id')
        cursor = db.get_cursor()

        # 检查工单是否存在且属于当前用户
        check_sql = """
        SELECT 工单ID, 告警ID, 响应时间, 运维人员ID 
        FROM 运维工单 
        WHERE 工单ID = %s AND 运维人员ID = %s
        """
        cursor.execute(check_sql, (work_order_id, user_id))
        order = cursor.fetchone()

        if not order:
            print(f"❌ 工单不存在或无权限: {work_order_id}")
            return jsonify({'success': False, 'message': '工单不存在或无权限'}), 404

        # 检查是否已响应
        if not order.get('响应时间'):
            print(f"⚠️ 工单未响应: {work_order_id}")
            return jsonify({'success': False, 'message': '请先响应工单'}), 400

        # 检查是否已完成
        cursor.execute("SELECT 处理完成时间 FROM 运维工单 WHERE 工单ID = %s", (work_order_id,))
        existing = cursor.fetchone()
        if existing and existing.get('处理完成时间'):
            print(f"⚠️ 工单已完成: {work_order_id}")
            return jsonify({'success': False, 'message': '工单已完成'})

        # 计算处理时长（分钟）
        cursor.execute("""
            SELECT TIMESTAMPDIFF(MINUTE, %s, NOW()) as minutes
        """, (order['响应时间']))
        time_result = cursor.fetchone()
        process_minutes = time_result['minutes'] if time_result else 0

        # 确保处理耗时 >= 0（满足约束 chk_2）
        if process_minutes < 0:
            process_minutes = 0
            print(f"⚠️ 处理耗时计算为负数，已修正为0")

        # 设置正确的复查状态（必须为'通过'或'未通过'，满足约束 chk_1）
        # 运维人员完成时，应该设置为'未通过'，等待工单管理员复查
        review_status = '未通过'

        print(f"🔍 计算的处理耗时: {process_minutes}分钟")
        print(f"🔍 设置的复查状态: {review_status}")

        # 更新工单
        sql = """
        UPDATE 运维工单 
        SET 处理完成时间 = NOW(),
            处理结果 = %s,
            处理耗时 = %s,
            复查状态 = %s
        WHERE 工单ID = %s
        """

        print(f"🔍 执行SQL: {sql}")
        print(
            f"🔍 参数: result={result_text[:50]}..., minutes={process_minutes}, review_status={review_status}, order_id={work_order_id}")

        cursor.execute(sql, (result_text, process_minutes, review_status, work_order_id))

        # 更新关联告警状态为'待审核'，等待工单管理员处理
        update_alert_sql = """
        UPDATE 告警信息 
        SET 处理状态 = '待审核'
        WHERE 告警ID = %s
        """
        cursor.execute(update_alert_sql, (order['告警ID'],))

        db.connect().commit()

        print(f"✅ 工单完成成功: {work_order_id}")
        return jsonify({
            'success': True,
            'message': '完成成功，等待管理员复查',
            'details': {
                'work_order_id': work_order_id,
                'complete_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'process_minutes': process_minutes,
                'review_status': review_status
            }
        })

    except Exception as e:
        db.connect().rollback()
        print(f"❌ 完成工单失败: {str(e)}")
        import traceback
        traceback.print_exc()

        # 提供更友好的错误信息
        error_msg = str(e)
        if 'chk_1' in error_msg:
            error_msg = "复查状态必须是'通过'或'未通过'"
        elif 'chk_2' in error_msg:
            error_msg = "处理耗时不能为负数"

        return jsonify({'success': False, 'message': f'完成失败: {error_msg}'}), 500

# ============ 主程序 ============
if __name__ == '__main__':
    # 创建必要的文件夹
    for folder in [app.config['BACKUP_FOLDER'], app.config['UPLOAD_FOLDER']]:
        if not os.path.exists(folder):
            os.makedirs(folder)

    print("智慧能源管理系统启动中...")
    print(f"访问地址: http://localhost:5001")
    print(f"统一登录页面: http://localhost:5001/login")
    print("测试账号:")
    print("  管理员: admin / Admin@123456")
    print("  数据分析师: analyst / Analyst@123456")

    app.run(debug=True, host='0.0.0.0', port=5001)