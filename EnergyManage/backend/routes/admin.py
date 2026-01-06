# backend/analyst_routes.py
import json

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from .persistence import PersistenceLayer

analyst_bp = Blueprint('analyst', __name__)


@analyst_bp.route('/api/analyst/pv-analysis', methods=['GET'])
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

        success, result = PersistenceLayer.DataAnalystFunctions.analyze_pv_prediction_accuracy(
            start_date, end_date
        )

        if success:
            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500


@analyst_bp.route('/api/analyst/optimize-model', methods=['POST'])
@login_required
def optimize_model():
    """优化预测模型"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        data = request.get_json()
        deviation_threshold = data.get('deviation_threshold', 15)

        success, result = PersistenceLayer.DataAnalystFunctions.optimize_prediction_model(
            deviation_threshold
        )

        if success:
            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'优化失败: {str(e)}'}), 500


@analyst_bp.route('/api/analyst/energy-patterns', methods=['GET'])
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
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d')

        success, result = PersistenceLayer.DataAnalystFunctions.analyze_energy_patterns(
            plant_id, start_date, end_date
        )

        if success:
            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'分析失败: {str(e)}'}), 500


# 修改 analyst_routes.py 中的 generate_report 函数

@analyst_bp.route('/api/analyst/generate-report', methods=['POST'])
@login_required
def generate_report():
    """生成能源报告并保存到数据库"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        data = request.get_json()
        report_type = data.get('report_type', 'monthly')
        year = data.get('year')
        month = data.get('month')

        # 1. 生成报告内容
        success, result = PersistenceLayer.DataAnalystFunctions.generate_energy_report(
            report_type, year, month
        )

        if not success:
            return jsonify({'success': False, 'message': result}), 400

        # 2. 将报告内容转换为文本格式
        import json
        report_content = format_report_to_text(result, report_type, year, month)

        # 3. 确定报告类型编号
        report_type_int = 1 if report_type == 'monthly' else 2

        # 4. 保存报告到数据库
        save_success, save_result = PersistenceLayer.SimpleReports.save_report(
            report_type_int,
            report_content,
            current_user.用户ID
        )

        if not save_success:
            return jsonify({'success': False, 'message': save_result}), 400

        return jsonify({
            'success': True,
            'message': '报告生成并保存成功',
            'report_id': save_result,
            'report_data': result  # 同时返回报告数据给前端显示
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'报告生成失败: {str(e)}'}), 500


# 修改 format_report_to_text 函数，提供更好的格式

def format_report_to_text(report_data, report_type, year, month):
    """将报告数据格式化为文本"""
    try:
        # 根据报告类型生成标题
        if report_type == 'monthly':
            period_str = f"{year}年{month}月"
        elif report_type == 'quarterly':
            quarter = (month - 1) // 3 + 1 if month else 1
            period_str = f"{year}年第{quarter}季度"
        else:
            period_str = f"{year}年"

        # 生成报告文本
        report_text = f"智慧能源管理系统 - {period_str}分析报告\n"
        report_text += "=" * 50 + "\n\n"

        report_text += f"报告ID: {report_data.get('report_id', 'N/A')}\n"
        report_text += f"生成时间: {report_data.get('generation_time', 'N/A')}\n"
        report_text += f"数据范围: {report_data.get('data_range', {}).get('start', 'N/A')} 至 {report_data.get('data_range', {}).get('end', 'N/A')}\n\n"

        # 一、摘要
        summary = report_data.get('summary', {})
        report_text += "一、报告摘要\n"
        report_text += "-" * 30 + "\n"
        report_text += f"总能耗: {summary.get('total_energy_consumption', 0):.2f}\n"
        report_text += f"总成本: ￥{summary.get('total_energy_cost', 0):.2f}\n"
        report_text += f"光伏总发电量: {summary.get('total_pv_generation', 0):.2f} kWh\n"
        report_text += f"光伏自用电量: {summary.get('total_pv_self_use', 0):.2f} kWh\n"
        report_text += f"总告警次数: {summary.get('total_alarms', 0)}\n"
        report_text += f"告警处理率: {summary.get('resolution_rate', 0):.1f}%\n\n"

        # 二、详细分析
        detailed = report_data.get('detailed_analysis', {})
        report_text += "二、详细分析\n"
        report_text += "-" * 30 + "\n"

        # 2.1 按能源类型
        energy_by_type = detailed.get('energy_by_type', {})
        if energy_by_type:
            report_text += "1. 按能源类型统计:\n"
            for energy_type, data in energy_by_type.items():
                report_text += f"   {energy_type}: {data.get('total_energy', 0):.2f} ({data.get('percentage', 0):.1f}%) - 成本: ￥{data.get('total_cost', 0):.2f}\n"
            report_text += "\n"

        # 2.2 按厂区
        energy_by_plant = detailed.get('energy_by_plant', [])
        if energy_by_plant:
            report_text += "2. 按厂区统计:\n"
            for plant in energy_by_plant:
                report_text += f"   {plant.get('plant_name', plant.get('plant_id', 'N/A'))}: {plant.get('total_energy', 0):.2f} ({plant.get('percentage', 0):.1f}%)\n"
            report_text += "\n"

        # 2.3 告警统计
        alarm_stats = detailed.get('alarm_statistics', {})
        if alarm_stats:
            report_text += "3. 告警统计:\n"
            report_text += f"   高等级告警: {alarm_stats.get('by_level', {}).get('高', 0)}\n"
            report_text += f"   中等级告警: {alarm_stats.get('by_level', {}).get('中', 0)}\n"
            report_text += f"   低等级告警: {alarm_stats.get('by_level', {}).get('低', 0)}\n"
            report_text += f"   处理完成率: {alarm_stats.get('resolution_rate', 0):.1f}%\n"
            report_text += "\n"

        # 2.4 光伏效率
        pv_efficiency = detailed.get('pv_efficiency', {})
        if pv_efficiency:
            report_text += "4. 光伏效率分析:\n"
            report_text += f"   平均效率: {pv_efficiency.get('average_efficiency', 0):.1f}%\n"
            report_text += f"   低于阈值设备数: {pv_efficiency.get('below_threshold', 0)}\n"
            report_text += f"   低效率占比: {pv_efficiency.get('below_threshold_percentage', 0):.1f}%\n"
            report_text += "\n"

        # 2.5 峰谷分析
        peak_valley = detailed.get('peak_valley_analysis', [])
        if peak_valley:
            report_text += "5. 峰谷用电分析:\n"
            for item in peak_valley:
                report_text += f"   厂区{item.get('plant_id', 'N/A')}: 峰段{item.get('peak_ratio', 0):.1f}% 谷段{item.get('valley_ratio', 0):.1f}%\n"
                report_text += f"   建议: {item.get('suggestion', '')}\n"
            report_text += "\n"

        # 三、优化建议
        recommendations = detailed.get('recommendations', [])
        report_text += "三、优化建议\n"
        report_text += "-" * 30 + "\n"
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                report_text += f"{i}. {rec}\n"
        else:
            report_text += "暂无优化建议\n"

        # 四、小时能耗模式（可选展示）
        energy_by_hour = detailed.get('energy_by_hour', {})
        if len(energy_by_hour) > 0:
            report_text += "\n四、小时能耗模式\n"
            report_text += "-" * 30 + "\n"

            # 只显示关键时段
            key_hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
            for hour in key_hours:
                hour_data = energy_by_hour.get(str(hour), {})
                if hour_data:
                    report_text += f"   {hour:02d}:00 - {hour_data.get('average', 0):.2f}\n"

        # 五、数据质量说明
        raw_data = report_data.get('raw_data_summary', {})
        report_text += "\n五、数据质量说明\n"
        report_text += "-" * 30 + "\n"
        report_text += f"能耗记录数: {raw_data.get('energy_records', 0)}\n"
        report_text += f"光伏记录数: {raw_data.get('pv_records', 0)}\n"
        report_text += f"告警记录数: {raw_data.get('alarm_records', 0)}\n"

        return report_text

    except Exception as e:
        import json
        return f"报告生成错误: {str(e)}\n原始数据: {json.dumps(report_data, ensure_ascii=False, indent=2)}"

# 添加获取报告列表的接口
@analyst_bp.route('/api/analyst/my-simple-reports', methods=['GET'])
@login_required
def get_my_simple_reports():
    """获取当前用户的简单报告列表"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        report_type = request.args.get('report_type')

        success, result = PersistenceLayer.SimpleReports.get_reports(
            report_type=int(report_type) if report_type else None,
            generator_id=current_user.用户ID
        )

        if success:
            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取报告失败: {str(e)}'}), 500


@analyst_bp.route('/api/analyst/dashboard', methods=['GET'])
@login_required
def analyst_dashboard():
    """数据分析师仪表盘数据"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        # 获取最近30天的数据
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        # 光伏预测准确率
        _, pv_analysis = PersistenceLayer.DataAnalystFunctions.analyze_pv_prediction_accuracy(
            start_date, end_date
        )

        # 能耗模式分析
        _, energy_analysis = PersistenceLayer.DataAnalystFunctions.analyze_energy_patterns(
            start_date=start_date, end_date=end_date
        )

        dashboard_data = {
            'pv_analysis': pv_analysis if isinstance(pv_analysis, dict) else {},
            'energy_analysis': energy_analysis if isinstance(energy_analysis, dict) else {},
            'summary': {
                'date_range': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                }
            }
        }

        return jsonify({'success': True, 'data': dashboard_data})

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取仪表盘数据失败: {str(e)}'}), 500


# 在 analyst_routes.py 中添加

@analyst_bp.route('/api/analyst/report/<report_id>', methods=['GET'])
@login_required
def get_report_detail(report_id):
    """获取报告详情"""
    if current_user.用户角色 != '数据分析师':
        return jsonify({'success': False, 'message': '权限不足'}), 403

    try:
        success, result = PersistenceLayer.SimpleReports.get_report(report_id)

        if success:
            # 检查是否是当前用户的报告
            if result['生成人ID'] != current_user.用户ID:
                return jsonify({'success': False, 'message': '无权查看此报告'}), 403

            return jsonify({'success': True, 'data': result})
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取报告详情失败: {str(e)}'}), 500