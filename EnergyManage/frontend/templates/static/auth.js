// frontend/static/js/auth.js
// 通用身份验证函数

const API_BASE = '/api';

class AuthManager {
    constructor() {
        this.user = null;
        this.isChecking = false;
    }

    // 检查登录状态
    async checkLogin() {
        if (this.isChecking) return;

        this.isChecking = true;

        try {
            const response = await fetch(`${API_BASE}/check-login`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.status === 401) {
                console.log('用户未登录，跳转到登录页面');
                window.location.href = '/login';
                return null;
            }

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    this.user = result.data;
                    console.log('用户已登录:', this.user);
                    return this.user;
                } else {
                    console.log('登录检查失败，跳转到登录页面');
                    window.location.href = '/login';
                    return null;
                }
            }
        } catch (error) {
            console.error('检查登录状态失败:', error);
            // 如果是网络错误，不跳转登录页
            if (error.name !== 'TypeError') {
                window.location.href = '/login';
            }
        } finally {
            this.isChecking = false;
        }

        return null;
    }

    // 获取当前用户信息
    async getCurrentUser() {
        if (this.user) {
            return this.user;
        }
        return await this.checkLogin();
    }

    // 更新页面上的用户信息
    updateUserInfo(user) {
        // 更新用户名
        const userNameElements = document.querySelectorAll('#userName, .user-name');
        userNameElements.forEach(el => {
            if (user.real_name) {
                el.textContent = user.real_name;
            }
        });

        // 更新用户角色
        const userRoleElements = document.querySelectorAll('#userRole, .user-role');
        userRoleElements.forEach(el => {
            if (user.role) {
                el.textContent = user.role;
            }
        });

        // 如果有厂区信息，更新
        if (user.factory_name) {
            const factoryElements = document.querySelectorAll('.factory-name');
            factoryElements.forEach(el => {
                el.textContent = user.factory_name;
            });
        }
    }

    // 退出登录
    async logout() {
        try {
            await fetch(`${API_BASE}/logout`, {
                method: 'POST',
                credentials: 'include'
            });
        } catch (error) {
            console.error('退出登录失败:', error);
        } finally {
            this.user = null;
            window.location.href = '/login';
        }
    }

    // 确保用户已登录
    async ensureLoggedIn() {
        const user = await this.checkLogin();
        if (!user) {
            return false;
        }
        this.updateUserInfo(user);
        return true;
    }
}

// 创建全局认证管理器
window.authManager = new AuthManager();

// 页面加载时自动检查登录状态
document.addEventListener('DOMContentLoaded', async function() {
    // 如果是登录页面，不检查
    if (window.location.pathname === '/login' ||
        window.location.pathname === '/') {
        return;
    }

    const isLoggedIn = await window.authManager.ensureLoggedIn();
    if (!isLoggedIn) {
        // 如果未登录，会跳转到登录页
        return;
    }

    // 绑定退出登录按钮
    document.querySelectorAll('.logout-btn, #logoutBtn, #logoutBtn2').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            window.authManager.logout();
        });
    });

    console.log('页面初始化完成，用户已登录');
});