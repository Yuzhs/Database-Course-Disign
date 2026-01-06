"""
数据库模型定义
对应物理结构中的所有表
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


# ============ 1. 厂区表 ============
class 厂区(db.Model):
    __tablename__ = '厂区'

    厂区编号 = db.Column(db.String(20), primary_key=True)
    厂区名称 = db.Column(db.String(100), unique=True, nullable=False)
    位置描述 = db.Column(db.Text)

    # 关系
    用户列表 = db.relationship('User', backref='负责厂区', lazy=True)
    设备列表 = db.relationship('设备', backref='所属厂区对象', lazy=True)
    屋顶区域列表 = db.relationship('屋顶区域', backref='所属厂区对象', lazy=True)
    并网点列表 = db.relationship('并网点', backref='所属厂区对象', lazy=True)
    峰谷能耗数据列表 = db.relationship('峰谷能耗数据', backref='厂区对象', lazy=True)


# ============ 2. 用户表 ============
class User(db.Model, UserMixin):
    __tablename__ = '用户'

    用户ID = db.Column(db.String(20), primary_key=True)
    登录账号 = db.Column(db.String(50), unique=True, nullable=False)
    密码哈希值 = db.Column(db.String(255), nullable=False)
    真实姓名 = db.Column(db.String(50), nullable=False)
    用户角色 = db.Column(db.String(20), nullable=False)
    手机号码 = db.Column(db.String(15))
    上次登录的时间 = db.Column(db.DateTime)
    登录失败的次数 = db.Column(db.Integer, default=0)
    负责的厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))

    # Flask-Login 必需的方法
    def get_id(self):
        return self.用户ID

    # 关系
    负责的配电房列表 = db.relationship('配电房', backref='负责人对象', lazy=True)
    确认的告警列表 = db.relationship('告警信息', backref='确认人对象', lazy=True)
    运维工单列表 = db.relationship('运维工单', backref='运维人员对象', lazy=True)
    简单报告列表 = db.relationship('简单报告', backref='生成人对象', lazy=True)


# ============ 3. 设备表 ============
class 设备(db.Model):
    __tablename__ = '设备'

    设备编号 = db.Column(db.String(30), primary_key=True)
    设备名称 = db.Column(db.String(100), nullable=False)
    设备大类 = db.Column(db.String(20))
    设备类型 = db.Column(db.String(20))
    所属厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))
    安装位置描述 = db.Column(db.Text)
    运行状态 = db.Column(db.String(20))

    # 关系
    光伏设备详情 = db.relationship('光伏设备', backref='设备对象', uselist=False, lazy=True)
    能耗计量设备详情 = db.relationship('能耗计量设备', backref='设备对象', uselist=False, lazy=True)
    配电房列表 = db.relationship('配电房', backref='设备对象', lazy=True)
    变压器监测数据列表 = db.relationship('变压器监测数据', backref='变压器对象', lazy=True)
    回路监测数据列表 = db.relationship('回路监测数据', backref='回路设备对象', lazy=True)
    告警列表 = db.relationship('告警信息', backref='告警设备对象', lazy=True)
    设备台账记录 = db.relationship('设备台账', backref='设备对象', uselist=False, lazy=True)


# ============ 4. 能耗计量设备表 ============
class 能耗计量设备(db.Model):
    __tablename__ = '能耗计量设备'

    设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'), primary_key=True)
    能源类型 = db.Column(db.String(20), nullable=False)
    管径规格 = db.Column(db.String(20))
    通讯协议 = db.Column(db.String(50))
    运行状态 = db.Column(db.String(20))
    校准周期 = db.Column(db.Integer)
    生产厂家 = db.Column(db.String(100))

    # 关系
    监测数据列表 = db.relationship('能耗监测数据', backref='计量设备对象', lazy=True)


# ============ 5. 光伏设备表 ============
class 光伏设备(db.Model):
    __tablename__ = '光伏设备'

    设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'), primary_key=True)
    设备类型 = db.Column(db.String(20), nullable=False)
    安装区域编号 = db.Column(db.String(20), db.ForeignKey('屋顶区域.区域编号'))
    接入并网点编号 = db.Column(db.String(20), db.ForeignKey('并网点.并网点编号'))
    装机容量 = db.Column(db.Numeric(10, 2))
    生产厂家 = db.Column(db.String(100))
    设备型号 = db.Column(db.String(50))
    投运时间 = db.Column(db.Date)
    校准周期 = db.Column(db.Integer)
    运行状态 = db.Column(db.String(20))
    通信协议 = db.Column(db.String(50))

    # 关系
    安装区域对象 = db.relationship('屋顶区域', backref='光伏设备列表', lazy=True)
    接入并网点对象 = db.relationship('并网点', backref='光伏设备列表', lazy=True)
    发电数据列表 = db.relationship('光伏发电数据', backref='光伏设备对象', lazy=True)


# ============ 6. 配电房表 ============
class 配电房(db.Model):
    __tablename__ = '配电房'

    配电房编号 = db.Column(db.String(20), primary_key=True)
    名称 = db.Column(db.String(100), nullable=False)
    位置描述 = db.Column(db.Text)
    电压等级 = db.Column(db.String(20))
    联系电话 = db.Column(db.String(15))
    变压器数量 = db.Column(db.Integer)
    投运时间 = db.Column(db.Date)
    负责人ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'))
    所属厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))

    # 关系
    变压器监测数据列表 = db.relationship('变压器监测数据', backref='配电房对象', lazy=True)
    回路监测数据列表 = db.relationship('回路监测数据', backref='配电房对象', lazy=True)


# ============ 7. 变压器监测数据表 ============
class 变压器监测数据(db.Model):
    __tablename__ = '变压器监测数据'

    变压器监测数据编号 = db.Column(db.String(30), primary_key=True)
    采集时间 = db.Column(db.DateTime, nullable=False)
    负载率 = db.Column(db.Numeric(5, 2))
    绕组温度 = db.Column(db.Numeric(8, 2))
    铁芯温度 = db.Column(db.Numeric(8, 2))
    环境温度 = db.Column(db.Numeric(6, 2))
    环境湿度 = db.Column(db.Numeric(5, 2))
    运行状态 = db.Column(db.String(20))
    配电房编号 = db.Column(db.String(20), db.ForeignKey('配电房.配电房编号'))
    变压器编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'))


# ============ 8. 回路监测数据表 ============
class 回路监测数据(db.Model):
    __tablename__ = '回路监测数据'

    回路监测数据编号 = db.Column(db.String(30), primary_key=True)
    回路编号 = db.Column(db.String(30), nullable=False)
    采集时间 = db.Column(db.DateTime, nullable=False)
    电容器温度 = db.Column(db.Numeric(8, 2))
    电压 = db.Column(db.Numeric(10, 2))
    电流 = db.Column(db.Numeric(10, 2))
    电缆头温度 = db.Column(db.Numeric(8, 2))
    有功功率 = db.Column(db.Numeric(10, 2))
    无功功率 = db.Column(db.Numeric(10, 2))
    功率因数 = db.Column(db.Numeric(5, 4))
    正向有功电量 = db.Column(db.Numeric(15, 2))
    反向有功电量 = db.Column(db.Numeric(15, 2))
    开关状态 = db.Column(db.String(10))
    电压异常标记 = db.Column(db.Boolean, default=False)
    温度异常标记 = db.Column(db.Boolean, default=False)
    配电房编号 = db.Column(db.String(20), db.ForeignKey('配电房.配电房编号'))
    设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'))


# ============ 9. 屋顶区域表 ============
class 屋顶区域(db.Model):
    __tablename__ = '屋顶区域'

    区域编号 = db.Column(db.String(20), primary_key=True)
    区域名称 = db.Column(db.String(100), nullable=False)
    屋顶材质 = db.Column(db.String(50))
    可用面积 = db.Column(db.Numeric(10, 2))
    已安装容量 = db.Column(db.Numeric(10, 2))
    最大可装机容量 = db.Column(db.Numeric(10, 2))
    所属建筑编号 = db.Column(db.String(30))
    所属厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))


# ============ 10. 井网点表 ============
class 并网点(db.Model):
    __tablename__ = '并网点'

    并网点编号 = db.Column(db.String(20), primary_key=True)
    并网点名称 = db.Column(db.String(100), nullable=False)
    电压等级 = db.Column(db.String(20))
    接入容量 = db.Column(db.Numeric(10, 2))
    并网时间 = db.Column(db.Date)
    所属厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))
    地理位置 = db.Column(db.Text)

    # 关系
    预测数据列表 = db.relationship('光伏预测数据', backref='并网点对象', lazy=True)
    光伏发电数据列表 = db.relationship('光伏发电数据', backref='并网点对象', lazy=True)


# ============ 11. 光伏发电数据表 ============
class 光伏发电数据(db.Model):
    __tablename__ = '光伏发电数据'

    数据编号 = db.Column(db.String(30), primary_key=True)
    设备编号 = db.Column(db.String(30), db.ForeignKey('光伏设备.设备编号'))
    并网点编号 = db.Column(db.String(20), db.ForeignKey('并网点.并网点编号'))
    采集时间 = db.Column(db.DateTime, nullable=False)
    发电量 = db.Column(db.Numeric(10, 2))
    上网电量 = db.Column(db.Numeric(10, 2))
    自用电量 = db.Column(db.Numeric(10, 2))
    逆变器效率 = db.Column(db.Numeric(5, 2))
    组串电压 = db.Column(db.Numeric(8, 2))
    组串电流 = db.Column(db.Numeric(8, 2))
    数据质量 = db.Column(db.String(10))


# ============ 12. 光伏预测数据表 ============
class 光伏预测数据(db.Model):
    __tablename__ = '光伏预测数据'

    预测编号 = db.Column(db.String(30), primary_key=True)
    并网点编号 = db.Column(db.String(20), db.ForeignKey('并网点.并网点编号'))
    预测日期 = db.Column(db.Date)
    预测时段 = db.Column(db.String(20))
    预测发电量 = db.Column(db.Numeric(10, 2))
    实际发电量 = db.Column(db.Numeric(10, 2))
    偏差率 = db.Column(db.Numeric(5, 2))
    预测模型版本 = db.Column(db.String(50))


# ============ 13. 能耗监测数据表 ============
class 能耗监测数据(db.Model):
    __tablename__ = '能耗监测数据'

    数据编号 = db.Column(db.String(30), primary_key=True)
    设备编号 = db.Column(db.String(30), db.ForeignKey('能耗计量设备.设备编号'))
    采集时间 = db.Column(db.DateTime, nullable=False)
    能耗值 = db.Column(db.Numeric(15, 4))
    单位 = db.Column(db.String(10))
    数据质量 = db.Column(db.String(10))


# ============ 14. 峰谷能耗数据表 ============
class 峰谷能耗数据(db.Model):
    __tablename__ = '峰谷能耗数据'

    记录编号 = db.Column(db.String(30), primary_key=True)
    能源类型 = db.Column(db.String(20))
    厂区编号 = db.Column(db.String(20), db.ForeignKey('厂区.厂区编号'))
    统计日期 = db.Column(db.Date)
    尖峰时段能耗 = db.Column(db.Numeric(15, 4))
    高峰时段能耗 = db.Column(db.Numeric(15, 4))
    平段能耗 = db.Column(db.Numeric(15, 4))
    低谷时段能耗 = db.Column(db.Numeric(15, 4))
    总能耗 = db.Column(db.Numeric(15, 4))
    峰谷电价 = db.Column(db.Numeric(10, 4))
    能耗成本 = db.Column(db.Numeric(15, 2))


# ============ 15. 告警信息表 ============
class 告警信息(db.Model):
    __tablename__ = '告警信息'

    告警ID = db.Column(db.String(30), primary_key=True)
    告警编号 = db.Column(db.String(30), unique=True)
    告警类型 = db.Column(db.String(20))
    关联设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'))
    发生时间 = db.Column(db.DateTime, nullable=False)
    告警等级 = db.Column(db.String(10))
    告警内容 = db.Column(db.Text, nullable=False)
    处理状态 = db.Column(db.String(20))
    告警触发阈值 = db.Column(db.Numeric(12, 4))
    告警确认人ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    确认时间 = db.Column(db.DateTime)

    # 关系
    运维工单列表 = db.relationship('运维工单', backref='告警对象', lazy=True)


# ============ 16. 运维工单表 ============
class 运维工单(db.Model):
    __tablename__ = '运维工单'

    工单ID = db.Column(db.String(30), primary_key=True)
    工单编号 = db.Column(db.String(30), unique=True)
    告警ID = db.Column(db.String(30), db.ForeignKey('告警信息.告警ID'))
    运维人员ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    派单时间 = db.Column(db.DateTime, nullable=False)
    响应时间 = db.Column(db.DateTime)
    处理完成时间 = db.Column(db.DateTime)
    处理结果 = db.Column(db.Text)
    复查状态 = db.Column(db.String(10))
    附件路径 = db.Column(db.Text)
    处理耗时 = db.Column(db.Integer)
    处理备注 = db.Column(db.Text)


# ============ 17. 设备台账表 ============
class 设备台账(db.Model):
    __tablename__ = '设备台账'

    台账编号 = db.Column(db.String(30), primary_key=True)
    设备编号 = db.Column(db.String(30), db.ForeignKey('设备.设备编号'), unique=True)
    型号规格 = db.Column(db.String(50))
    安装时间 = db.Column(db.Date)
    质保期 = db.Column(db.Integer)
    维修记录 = db.Column(db.Text)
    校准记录 = db.Column(db.Text)
    报废状态 = db.Column(db.String(20))
    报废时间 = db.Column(db.Date)
    报废原因 = db.Column(db.Text)


# ============ 18. 大屏展示配置表 ============
class 大屏展示配置(db.Model):
    __tablename__ = '大屏展示配置'

    配置编号 = db.Column(db.String(30), primary_key=True)
    展示模块 = db.Column(db.String(50))
    数据刷新频率 = db.Column(db.String(20))
    展示字段 = db.Column(db.Text)
    排序规则 = db.Column(db.String(50))
    权限等级 = db.Column(db.String(20))

    # 关系
    实时汇总数据列表 = db.relationship('实时汇总数据', backref='配置对象', lazy=True)
    历史趋势数据列表 = db.relationship('历史趋势数据', backref='配置对象', lazy=True)


# ============ 19. 实时汇总数据表 ============
class 实时汇总数据(db.Model):
    __tablename__ = '实时汇总数据'

    汇总编号 = db.Column(db.String(30), primary_key=True)
    统计时间 = db.Column(db.DateTime, nullable=False)
    总用电量 = db.Column(db.Numeric(15, 2))
    总用水量 = db.Column(db.Numeric(15, 2))
    总蒸汽消耗量 = db.Column(db.Numeric(15, 2))
    总天然气消耗量 = db.Column(db.Numeric(15, 2))
    光伏总发电量 = db.Column(db.Numeric(15, 2))
    光伏自用电量 = db.Column(db.Numeric(15, 2))
    总告警次数 = db.Column(db.Integer)
    高等级告警数 = db.Column(db.Integer)
    中等级告警数 = db.Column(db.Integer)
    低等级告警数 = db.Column(db.Integer)
    配置编号 = db.Column(db.String(30), db.ForeignKey('大屏展示配置.配置编号'))


# ============ 20. 历史趋势数据表 ============
class 历史趋势数据(db.Model):
    __tablename__ = '历史趋势数据'

    趋势编号 = db.Column(db.String(30), primary_key=True)
    能源类型 = db.Column(db.String(20))
    统计周期 = db.Column(db.String(10))
    统计时间 = db.Column(db.DateTime, nullable=False)
    能耗_发电量数值 = db.Column(db.Numeric(15, 2))
    同比增长率 = db.Column(db.Numeric(8, 4))
    环比增长率 = db.Column(db.Numeric(8, 4))
    配置编号 = db.Column(db.String(30), db.ForeignKey('大屏展示配置.配置编号'))


# ============ 21. 简单报告表（自定义扩展） ============
class 简单报告(db.Model):
    __tablename__ = '简单报告'

    报告ID = db.Column(db.String(30), primary_key=True)
    报告类型 = db.Column(db.Integer, nullable=False)  # 1:月度报告 2:季度报告
    报告内容 = db.Column(db.Text, nullable=False)
    生成时间 = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    生成人ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'), nullable=False)
#
# class 简单报告(db.Model):
#     __tablename__ = '简单报告'
#
#     报告ID = db.Column(db.String(30), primary_key=True)
#     报告类型 = db.Column(db.Integer, nullable=False)  # 1:月度报告 2:季度报告
#     报告内容 = db.Column(db.Text, nullable=False)
#     生成时间 = db.Column(db.DateTime, nullable=False)
#     生成人ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'), nullable=False)
#
#     生成人 = db.relationship('User', backref='简单报告列表', lazy=True)

# ============ 22. 操作日志表（自定义扩展） ============
class 操作日志(db.Model):
    __tablename__ = '操作日志'

    日志ID = db.Column(db.String(30), primary_key=True)
    操作类型 = db.Column(db.String(50), nullable=False)
    操作人员ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    操作时间 = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    操作内容 = db.Column(db.Text)
    操作结果 = db.Column(db.String(20))
    操作IP = db.Column(db.String(45))
    用户代理 = db.Column(db.Text)


# ============ 23. 登录日志表（自定义扩展） ============
class 登录日志(db.Model):
    __tablename__ = '登录日志'

    日志ID = db.Column(db.String(30), primary_key=True)
    用户ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'), nullable=False)
    登录时间 = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    登录IP = db.Column(db.String(45))
    登录状态 = db.Column(db.String(20), nullable=False)
    失败原因 = db.Column(db.Text)


# ============ 24. 告警规则表（自定义扩展） ============
class 告警规则(db.Model):
    __tablename__ = '告警规则'

    规则ID = db.Column(db.String(30), primary_key=True)
    规则名称 = db.Column(db.String(100), nullable=False)
    设备类型 = db.Column(db.String(50), nullable=False)
    告警参数 = db.Column(db.String(50), nullable=False)
    告警条件 = db.Column(db.String(10), nullable=False)
    告警阈值 = db.Column(db.Numeric(12, 4), nullable=False)
    告警等级 = db.Column(db.String(10))
    启用状态 = db.Column(db.Boolean, default=True)
    创建时间 = db.Column(db.DateTime, default=datetime.utcnow)
    创建人员ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    备注 = db.Column(db.Text)


# ============ 25. 备份日志表（自定义扩展） ============
class 备份日志(db.Model):
    __tablename__ = '备份日志'

    备份ID = db.Column(db.String(30), primary_key=True)
    备份时间 = db.Column(db.DateTime, nullable=False)
    备份文件 = db.Column(db.String(255), nullable=False)
    备份类型 = db.Column(db.String(20), nullable=False)
    操作人员ID = db.Column(db.String(20), db.ForeignKey('用户.用户ID'))
    备份大小 = db.Column(db.Numeric(10, 2))
    完成状态 = db.Column(db.String(20), default='成功')
    备注 = db.Column(db.Text)