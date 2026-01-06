#!/usr/bin/env python3
"""
智慧能源管理系统 - 启动脚本
"""
import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app import app

if __name__ == '__main__':
    print("=" * 50)
    print("智慧能源管理系统启动中...")
    print("=" * 50)
    print("访问地址: http://localhost:5001")
    print("统一登录页面: http://localhost:5001/login")
    print("")
    print("测试账号:")
    print("  系统管理员: admin / Admin@123456")
    print("  数据分析师: analyst / Analyst@123456")
    print("  能源管理员: energy / Energy@123456")
    print("")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)

    try:
        app.run(debug=True, host='0.0.0.0', port=5001)
    except KeyboardInterrupt:
        print("\n服务已停止")