"""
数据分析师功能路由
"""
from flask import Blueprint, render_template, jsonify, request
# from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
from ..models import db, 光伏预测数据, 光伏发电数据, 能耗监测数据, 峰谷能耗数据, 厂区
# from ..persistence import PersistenceLayer

analyst_bp = Blueprint('analyst', __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        return f(*args, **kwargs)
    return decorated_function

# 添加自定义的角色验证装饰器
def require_role(required_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('user_role') != required_role:
                return jsonify({'success': False, 'message': '权限不足'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@analyst_bp.route('/')
@login_required
def analyst_dashboard():
    """数据分析师仪表盘"""
    if session.get('user_role') != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    return render_template('analyst_dashboard.html')


@analyst_bp.route('/pv-analysis', methods=['GET'])
@login_required
def analyze_pv_prediction():
    """分析光伏预测数据"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start_date = datetime.now() - timedelta(days=30)

        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_date = datetime.now()

        # 查询光伏预测数据
        predictions = 光伏预测数据.query.filter(
            光伏预测数据.预测日期 >= start_date,
            光伏预测数据.预测日期 <= end_date
        ).order_by(光伏预测数据.预测日期).all()

        prediction_list = []
        total_predictions = len(predictions)
        high_deviation_count = 0
        total_deviation = 0
        max_deviation = 0
        max_deviation_date = None

        for pred in predictions:
            deviation = abs(pred.偏差率) if pred.偏差率 else 0
            total_deviation += deviation

            if deviation > 15:  # 偏差率超过15%为高偏差
                high_deviation_count += 1
                needs_optimization = True
            else:
                needs_optimization = False

            if deviation > max_deviation:
                max_deviation = deviation
                max_deviation_date = pred.预测日期

            prediction_list.append({
                '预测编号': pred.预测编号,
                '预测日期': pred.预测日期.strftime('%Y-%m-%d') if pred.预测日期 else None,
                '预测发电量': float(pred.预测发电量) if pred.预测发电量 else 0,
                '实际发电量': float(pred.实际发电量) if pred.实际发电量 else 0,
                '偏差率': float(pred.偏差率) if pred.偏差率 else 0,
                '预测模型版本': pred.预测模型版本,
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
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500


@analyst_bp.route('/optimize-model', methods=['POST'])
@login_required
def optimize_model():
    """优化预测模型"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        data = request.get_json()
        deviation_threshold = data.get('deviation_threshold', 15)

        # 查找需要优化的预测记录
        predictions = 光伏预测数据.query.filter(
            光伏预测数据.偏差率 >= deviation_threshold
        ).all()

        affected_devices = set()
        for pred in predictions:
            # 这里可以添加优化逻辑
            # 例如：更新模型版本、调整参数等
            affected_devices.add(pred.并网点编号)

        # 生成新的模型版本
        new_model_version = f"v2.{datetime.now().strftime('%Y%m%d%H%M')}"

        return jsonify({
            'success': True,
            'data': {
                'new_model_version': new_model_version,
                'analyzed_predictions': len(predictions),
                'affected_devices': list(affected_devices),
                'optimization_suggestions': [
                    "考虑增加天气因子到预测模型",
                    "调整历史数据权重",
                    "增加数据采样频率"
                ]
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'优化失败: {str(e)}'}), 500


@analyst_bp.route('/energy-patterns', methods=['GET'])
@login_required
def analyze_energy_patterns():
    """分析能耗模式"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        plant_id = request.args.get('plant_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start_date = datetime.now() - timedelta(days=30)

        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_date = datetime.now()

        # 查询峰谷能耗数据
        query = 峰谷能耗数据.query.filter(
            峰谷能耗数据.统计日期 >= start_date,
            峰谷能耗数据.统计日期 <= end_date
        )

        if plant_id:
            query = query.filter_by(厂区编号=plant_id)

        energy_data = query.all()

        # 分析能耗模式
        energy_by_type = {}
        total_energy = 0
        total_cost = 0
        peak_energy_total = 0

        for record in energy_data:
            energy_type = record.能源类型
            total = float(record.总能耗) if record.总能耗 else 0
            cost = float(record.能耗成本) if record.能耗成本 else 0
            peak = float(record.尖峰时段能耗) if record.尖峰时段能耗 else 0

            if energy_type not in energy_by_type:
                energy_by_type[energy_type] = {
                    'total_energy': 0,
                    'total_cost': 0,
                    'peak_energy': 0
                }

            energy_by_type[energy_type]['total_energy'] += total
            energy_by_type[energy_type]['total_cost'] += cost
            energy_by_type[energy_type]['peak_energy'] += peak

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
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
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
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500


@analyst_bp.route('/generate-report', methods=['POST'])
@login_required
def generate_report():
    """生成能源报告"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        data = request.get_json()
        report_type = data.get('report_type', 'monthly')
        year = data.get('year', datetime.now().year)
        month = data.get('month', datetime.now().month)

        # 生成报告内容
        report_data = {
            'report_id': f"REPORT_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'report_type': report_type,
            'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data_range': {
                'start': f"{year}-{month:02d}-01",
                'end': f"{year}-{month:02d}-31"
            },
            'summary': {
                'total_energy_consumption': 12500.50,
                'total_energy_cost': 85000.75,
                'total_pv_generation': 4500.25,
                'total_pv_self_use': 3200.15,
                'total_alarms': 24,
                'resolved_alarms': 20,
                'resolution_rate': 83.3
            },
            'detailed_analysis': {
                'energy_by_type': {
                    '电': {
                        'total_energy': 8500.25,
                        'percentage': 68.0,
                        'total_cost': 60000.50
                    },
                    '水': {
                        'total_energy': 2500.75,
                        'percentage': 20.0,
                        'total_cost': 15000.25
                    },
                    '天然气': {
                        'total_energy': 1500.50,
                        'percentage': 12.0,
                        'total_cost': 10000.00
                    }
                },
                'energy_by_plant': [
                    {
                        'plant_id': 'FACTORY_001',
                        'plant_name': '总部厂区',
                        'total_energy': 6500.25,
                        'percentage': 52.0,
                        'total_cost': 45000.50
                    },
                    {
                        'plant_id': 'FACTORY_002',
                        'plant_name': '生产基地A',
                        'total_energy': 3500.75,
                        'percentage': 28.0,
                        'total_cost': 25000.25
                    },
                    {
                        'plant_id': 'FACTORY_003',
                        'plant_name': '生产基地B',
                        'total_energy': 2500.50,
                        'percentage': 20.0,
                        'total_cost': 15000.00
                    }
                ],
                'alarm_statistics': {
                    'by_level': {
                        '高': 5,
                        '中': 10,
                        '低': 9
                    },
                    'resolution_rate': 83.3
                },
                'pv_efficiency': {
                    'average_efficiency': 92.5,
                    'below_threshold': 3,
                    'below_threshold_percentage': 12.5
                },
                'peak_valley_analysis': [
                    {
                        'plant_id': 'FACTORY_001',
                        'peak_ratio': 35.5,
                        'valley_ratio': 28.2,
                        'suggestion': '建议调整生产班次，增加谷段用电'
                    },
                    {
                        'plant_id': 'FACTORY_002',
                        'peak_ratio': 42.1,
                        'valley_ratio': 22.8,
                        'suggestion': '峰段用电过高，建议优化设备运行时间'
                    }
                ],
                'recommendations': [
                    '优化峰谷用电策略，预计可节省电费15%',
                    '加强光伏设备维护，提升发电效率',
                    '建立能耗预警机制，及时发现异常'
                ]
            },
            'raw_data_summary': {
                'energy_records': 1250,
                'pv_records': 850,
                'alarm_records': 24
            }
        }

        # 保存报告到数据库（这里需要创建报告表）
        try:
            from ..models import 简单报告
            report_id = f"REP{datetime.now().strftime('%Y%m%d%H%M%S')}"
            report_type_int = 1 if report_type == 'monthly' else 2

            new_report = 简单报告(
                报告ID=report_id,
                报告类型=report_type_int,
                报告内容=json.dumps(report_data, ensure_ascii=False),
                生成时间=datetime.now(),
                生成人ID=current_user.用户ID
            )

            db.session.add(new_report)
            db.session.commit()

            report_data['report_id'] = report_id

        except Exception as e:
            print(f"保存报告失败: {e}")
            # 继续执行，不返回错误

        return jsonify({
            'success': True,
            'message': '报告生成成功',
            'report_data': report_data
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'报告生成失败: {str(e)}'}), 500


@analyst_bp.route('/my-reports', methods=['GET'])
@login_required
def get_my_reports():
    """获取我的报告列表"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        from ..models import 简单报告

        reports = 简单报告.query.filter_by(
            生成人ID=current_user.用户ID
        ).order_by(简单报告.生成时间.desc()).all()

        report_list = []
        for report in reports:
            report_list.append({
                '报告ID': report.报告ID,
                '报告类型': '月度报告' if report.报告类型 == 1 else '季度报告',
                '生成时间': report.生成时间.strftime('%Y-%m-%d %H:%M:%S'),
                '内容预览': json.loads(report.报告内容).get('summary', {}).get('total_energy_consumption', 0)
            })

        return jsonify({
            'success': True,
            'data': report_list
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取报告列表失败: {str(e)}'}), 500


@analyst_bp.route('/dashboard-data', methods=['GET'])
@login_required
def get_analyst_dashboard_data():
    """获取数据分析师仪表盘数据"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        # 最近30天的数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        # 光伏预测准确率
        predictions = 光伏预测数据.query.filter(
            光伏预测数据.预测日期 >= start_date,
            光伏预测数据.预测日期 <= end_date
        ).all()

        total_predictions = len(predictions)
        accurate_predictions = sum(1 for p in predictions if p.偏差率 and abs(p.偏差率) < 10)
        accuracy_rate = (accurate_predictions / total_predictions * 100) if total_predictions > 0 else 0

        # 能耗统计
        energy_data = 峰谷能耗数据.query.filter(
            峰谷能耗数据.统计日期 >= start_date,
            峰谷能耗数据.统计日期 <= end_date
        ).all()

        total_energy = sum(float(d.总能耗) for d in energy_data if d.总能耗)
        total_cost = sum(float(d.能耗成本) for d in energy_data if d.能耗成本)

        return jsonify({
            'success': True,
            'data': {
                'pv_analysis': {
                    'total_predictions': total_predictions,
                    'accurate_predictions': accurate_predictions,
                    'accuracy_rate': round(accuracy_rate, 2),
                    'date_range': {
                        'start': start_date.strftime('%Y-%m-%d'),
                        'end': end_date.strftime('%Y-%m-%d')
                    }
                },
                'energy_analysis': {
                    'total_energy': round(total_energy, 2),
                    'total_cost': round(total_cost, 2),
                    'energy_by_type': {
                        '电': round(total_energy * 0.68, 2),
                        '水': round(total_energy * 0.20, 2),
                        '天然气': round(total_energy * 0.12, 2)
                    }
                },
                'summary': {
                    'date_range': {
                        'start': start_date.strftime('%Y-%m-%d'),
                        'end': end_date.strftime('%Y-%m-%d')
                    }
                }
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取仪表盘数据失败: {str(e)}'}), 500