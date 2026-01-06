# backend/routes/common.py
from flask import Blueprint, jsonify
from flask_login import login_required, current_user

common_bp = Blueprint('common', __name__)


@common_bp.route('/api/common/user-info', methods=['GET'])
@login_required
def get_user_info():
    """获取当前用户信息"""
    try:
        return jsonify({
            'success': True,
            'data': {
                'id': current_user.用户ID,
                'username': current_user.登录账号,
                'realname': current_user.真实姓名,
                'role': current_user.用户角色,
                'phone': current_user.手机号码
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取用户信息失败: {str(e)}'}), 500


@common_bp.route('/api/common/system-status', methods=['GET'])
@login_required
def get_system_status():
    """获取系统状态"""
    try:
        from ..models import db
        import datetime

        # 获取用户数量
        from ..models import User
        user_count = User.query.count()

        # 获取最近登录时间
        recent_login = User.query.order_by(User.上次登录的时间.desc()).first()

        status_data = {
            'user_count': user_count,
            'last_login': recent_login.上次登录时间.strftime(
                '%Y-%m-%d %H:%M:%S') if recent_login.上次登录时间 else '从未登录',
            'server_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'roles': ['系统管理员', '数据分析师', '能源管理员', '运维人员', '企业管理层']
        }

        return jsonify({'success': True, 'data': status_data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取系统状态失败: {str(e)}'}), 500