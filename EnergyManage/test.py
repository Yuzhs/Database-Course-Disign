#!/usr/bin/env python3
"""
创建必要的文件夹
"""

import os

# 需要创建的文件夹列表
folders = [
    'database_backups',
    'uploads',
    'logs',
    '../frontend/templates'
]

print("创建必要的文件夹...")
for folder in folders:
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
        print(f"✅ 创建文件夹: {folder}")
    else:
        print(f"📁 文件夹已存在: {folder}")

print("\n文件夹结构创建完成!")