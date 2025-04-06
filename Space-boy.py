import os
import time
import threading
import requests
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# توكن البوت - استبدله بتوكنك
TOKEN = "7717260828:AAFIyiwyX_ifmmBcebYXFEdLuYXZtC_R3Go"

# إعدادات اللوج
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

# Color codes for terminal
B = "\033[1m"  # Bold
G = "\033[92m"  # Green
Y = "\033[93m"  # Yellow
R = "\033[91m"  # Red
C = "\033[96m"  # Cyan
W = "\033[97m"  # White
S = "\033[0m"   # Reset

class SpaceAdventureBot:
    def __init__(self):
        self.accounts = {}
        self.lock = threading.Lock()
        self.base_url = "https://space-adventure.online/api"
        self.load_accounts()
        self.status_message_id = None
        self.chat_id = None
        self.running = False
        self.update_interval = 30  # ثواني بين التحديثات
        self.last_daily_claim_check = 0
        self.last_reward_video_check = 0

    def log_action(self, message, account_id=None, level='info'):
        """تسجيل الأحداث في اللوج"""
        log_msg = message
        if account_id:
            account = self.accounts.get(account_id, {})
            acc_num = account.get('account_number', '?')
            log_msg = f"[Account {acc_num}] {message}"
        
        if level == 'info':
            logger.info(log_msg)
            print(f"{B}{G}{log_msg}{S}")
        elif level == 'warning':
            logger.warning(log_msg)
            print(f"{B}{Y}{log_msg}{S}")
        elif level == 'error':
            logger.error(log_msg)
            print(f"{B}{R}{log_msg}{S}")

    def load_accounts(self):
        """تحميل الحسابات من ملف Accounts.txt"""
        try:
            with open("Accounts.txt", "r") as f:
                for idx, line in enumerate(f.readlines(), 1):
                    if ":" in line:
                        id, query_id = line.strip().split(":")
                        self.accounts[id] = {
                            'query_id': query_id,
                            'token': None,
                            'auth_id': None,
                            'last_claim': 0,
                            'account_number': idx,
                            'last_status': {},
                            'failed_auth': 0,
                            'session': requests.Session(),
                            'last_boost_check': 0,
                            'boost_data': None,
                            'last_action': None,
                            'last_action_time': 0,
                            'last_upgrade': 0,
                            'last_error': None,
                            'last_daily_claim': 0,
                            'last_reward_video': 0
                        }
            self.log_action(f"تم تحميل {len(self.accounts)} حساب بنجاح!")
        except FileNotFoundError:
            self.log_action("❌ خطأ: لم يتم العثور على ملف Accounts.txt!", level='error')
            raise

    async def send_error_notification(self, context: ContextTypes.DEFAULT_TYPE, account_id, error_msg):
        """إرسال إشعار بالخطأ إلى المسؤول"""
        account = self.accounts[account_id]
        msg = (
            f"⚠️ <b>خطأ في الحساب {account['account_number']}</b>\n"
            f"🆔: <code>{account_id}</code>\n"
            f"📛 الخطأ: <code>{error_msg}</code>\n"
            f"⏱️ الوقت: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await context.bot.send_message(
            chat_id=self.chat_id,
            text=msg,
            parse_mode='HTML'
        )

    def authenticate_account(self, account_id, retry=False):
        """مصادقة الحساب"""
        account = self.accounts[account_id]
        try:
            url = f"{self.base_url}/auth/telegram"
            data = account['query_id']
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': str(len(data)),
                'User-Agent': 'Mozilla/5.0',
            }

            self.log_action(f"جاري مصادقة الحساب...", account_id)
            response = account['session'].post(url, data=data, headers=headers)
            response.raise_for_status()
            data = response.json()

            if 'token' in data:
                account['token'] = data['token']
                account['auth_id'] = account_id
                account['failed_auth'] = 0
                account['last_error'] = None
                self.log_action(f"تمت المصادقة بنجاح", account_id)
                return True
            else:
                account['failed_auth'] += 1
                account['last_error'] = "فشل المصادقة: لا يوجد توكن"
                self.log_action(f"فشل المصادقة: لا يوجد توكن في الاستجابة", account_id, 'error')
                return False
        except Exception as e:
            account['failed_auth'] += 1
            account['last_error'] = f"خطأ المصادقة: {str(e)}"
            self.log_action(f"فشل المصادقة: {str(e)}", account_id, 'error')
            return False

    def get_user_data(self, account_id):
        """جلب بيانات المستخدم"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            if self.authenticate_account(account_id, retry=True):
                return self.get_user_data(account_id)
            return None

        try:
            url = f"{self.base_url}/user/get"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            self.log_action(f"جلب بيانات المستخدم...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['last_error'] = None
            data = response.json()
            self.log_action(f"تم جلب بيانات المستخدم بنجاح", account_id)
            return data
        except Exception as e:
            account['last_error'] = f"خطأ جلب البيانات: {str(e)}"
            self.log_action(f"فشل جلب بيانات المستخدم: {str(e)}", account_id, 'error')
            return None

    def get_boost_data(self, account_id):
        """جلب بيانات التعزيزات"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return None
            
        if time.time() - account['last_boost_check'] < 300 and account['boost_data']:
            return account['boost_data']
            
        try:
            url = f"{self.base_url}/boost/get/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            self.log_action(f"جلب بيانات التعزيزات...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['boost_data'] = response.json()
            account['last_boost_check'] = time.time()
            account['last_error'] = None
            self.log_action(f"تم جلب بيانات التعزيزات بنجاح", account_id)
            return account['boost_data']
        except Exception as e:
            account['last_error'] = f"خطأ جلب التعزيزات: {str(e)}"
            self.log_action(f"فشل جلب بيانات التعزيزات: {str(e)}", account_id, 'error')
            return None

    def buy_boost(self, account_id, boost_id):
        """شراء تعزيز"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/boost/buy/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id'],
                'Content-Type': 'application/json'
            }
            payload = {"id": boost_id, "method": "free"}
            
            boost_name = {
                1: "⛽ تعبئة الوقود",
                2: "🔧 إصلاح الدرع", 
                3: "🌀 حقل القوة"
            }.get(boost_id, f"التعزيز {boost_id}")
            
            self.log_action(f"جاري شراء {boost_name}...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            account['last_action'] = f"{boost_name} تم ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action(f"تم شراء {boost_name} بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = f"خطأ في التعزيز {boost_id}"
            account['last_error'] = f"خطأ شراء التعزيز: {str(e)}"
            self.log_action(f"فشل شراء {boost_name}: {str(e)}", account_id, 'error')
            return False

    def play_roulette(self, account_id):
        """لعب الروليت"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/roulette/buy/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id'],
                'Content-Type': 'application/json'
            }
            payload = {"method": "free"}
            
            self.log_action("جاري لعب الروليت...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            account['last_action'] = "🎰 لعب الروليت ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action("تم لعب الروليت بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎰 خطأ في الروليت"
            account['last_error'] = f"خطأ لعب الروليت: {str(e)}"
            self.log_action(f"فشل لعب الروليت: {str(e)}", account_id, 'error')
            return False

    def claim_rewards(self, account_id):
        """جمع المكافآت"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/game/claiming/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            self.log_action("جاري جمع المكافآت...", account_id)
            response = account['session'].post(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers)
                else:
                    return False

            response.raise_for_status()
            account['last_claim'] = time.time()
            account['last_action'] = "🪙 Coin Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action("تم جمع المكافآت بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🪙 Claim Failed❌"
            account['last_error'] = f"🪙 Claim Failed❌: {str(e)}"
            self.log_action(f"فشل جمع المكافآت: {str(e)}", account_id, 'error')
            return False

    def claim_daily_reward(self, account_id):
        """جمع المكافأة اليومية"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/dayli/claim_activity/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            self.log_action("جاري جمع المكافأة اليومية...", account_id)
            response = account['session'].post(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers)
                else:
                    return False

            response.raise_for_status()
            account['last_daily_claim'] = time.time()
            account['last_action'] = "🎁 Daily Reward Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action("تم جمع المكافأة اليومية بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎁 Daily Claim Failed❌"
            account['last_error'] = f"🎁 Daily Claim Failed❌: {str(e)}"
            self.log_action(f"فشل جمع المكافأة اليومية: {str(e)}", account_id, 'error')
            return False

    def claim_reward_video(self, account_id):
        """جمع مكافأة الفيديو"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/tasks/reward-video/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            
            # إرسال 3 طلبات كما هو مطلوب
            self.log_action("جاري جمع مكافأة الفيديو (1/3)...", account_id)
            response1 = account['session'].put(url, headers=headers)
            response1.raise_for_status()
            data1 = response1.json()
            
            if data1.get('event') != 'watch' or data1.get('count') != 1:
                raise Exception("Invalid response for first request")
            
            self.log_action("جاري جمع مكافأة الفيديو (2/3)...", account_id)
            response2 = account['session'].put(url, headers=headers)
            response2.raise_for_status()
            data2 = response2.json()
            
            if data2.get('event') != 'watch' or data2.get('count') != 2:
                raise Exception("Invalid response for second request")
            
            self.log_action("جاري جمع مكافأة الفيديو (3/3)...", account_id)
            response3 = account['session'].put(url, headers=headers)
            response3.raise_for_status()
            data3 = response3.json()
            
            if data3.get('event') != 'reward' or data3.get('count') != 0:
                raise Exception("Invalid response for third request")
            
            account['last_reward_video'] = time.time()
            account['last_action'] = "🎥 Video Reward Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action("تم جمع مكافأة الفيديو بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎥 Video Claim Failed❌"
            account['last_error'] = f"🎥 Video Claim Failed❌: {str(e)}"
            self.log_action(f"فشل جمع مكافأة الفيديو: {str(e)}", account_id, 'error')
            return False

    def upgrade_boost(self, account_id, boost_id):
        """ترقية التعزيز"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            # التحقق من مستوى الترقية المسموح به
            user_data = self.get_user_data(account_id)
            if not user_data or 'user' not in user_data:
                return False
                
            user = user_data['user']
            current_level = {
                4: user.get('level_claims', 1),
                5: user.get('level_claim_max', 1),
                6: user.get('level_fuel', 1),
                7: user.get('level_shield', 1)
            }.get(boost_id, 1)
            
            # تحديد الحد الأقصى للترقية حسب boost_id
            max_level = 6 if boost_id == 4 else 5
            if current_level >= max_level:
                self.log_action(f"لا يمكن ترقية التعزيز {boost_id} أكثر من المستوى {max_level}", account_id, 'warning')
                return False

            url = f"{self.base_url}/boost/buy/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id'],
                'Content-Type': 'application/json'
            }
            payload = {"id": boost_id, "method": "coin"}
            
            boost_name = {
                4: "⛏️ Coin Mining",
                5: "💰 Coin Capacity",
                6: "🛢️ Tank Volume",
                7: "🛡️ Shield"
            }.get(boost_id, f"Boost {boost_id}")
            
            self.log_action(f"جاري ترقية {boost_name}...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"انتهت صلاحية التوكن، جاري إعادة المصادقة...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            account['last_action'] = f"🚀 {boost_name} Upgraded ✓"
            account['last_action_time'] = time.time()
            account['last_upgrade'] = time.time()
            account['last_error'] = None
            self.log_action(f"تم ترقية {boost_name} بنجاح", account_id)
            return True
        except Exception as e:
            account['last_action'] = f"❌🚀 Upgrade error {boost_id}"
            account['last_error'] = f"❌🚀 Upgrade error: {str(e)}"
            self.log_action(f"فشل ترقية التعزيز {boost_id}: {str(e)}", account_id, 'error')
            return False

    def check_and_upgrade(self, account_id):
        """التحقق وترقية التعزيزات"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        if time.time() - account['last_upgrade'] < 300:
            return False

        user_data = self.get_user_data(account_id)
        if not user_data or 'user' not in user_data:
            return False

        user = user_data['user']
        boost_data = self.get_boost_data(account_id)
        if not boost_data:
            return False

        balance = user.get('balance', 0)
        mining_lvl = user.get('level_claims', 1)
        luggage_lvl = user.get('level_claim_max', 1)
        fuel_lvl = user.get('level_fuel', 1)
        shield_lvl = user.get('level_shield', 1)

        mining_price = self.get_upgrade_price(boost_data, 4, mining_lvl)
        luggage_price = self.get_upgrade_price(boost_data, 5, luggage_lvl)
        tank_price = self.get_upgrade_price(boost_data, 6, fuel_lvl)
        shield_price = self.get_upgrade_price(boost_data, 7, shield_lvl)

        if (mining_lvl == luggage_lvl == fuel_lvl == shield_lvl and 
            mining_price != "MAX" and balance >= mining_price):
            if self.upgrade_boost(account_id, 4):
                return True

        if mining_lvl > luggage_lvl and luggage_price != "MAX" and balance >= luggage_price:
            if self.upgrade_boost(account_id, 5):
                return True

        if mining_lvl > fuel_lvl and tank_price != "MAX" and balance >= tank_price:
            if self.upgrade_boost(account_id, 6):
                return True

        if mining_lvl > shield_lvl and shield_price != "MAX" and balance >= shield_price:
            if self.upgrade_boost(account_id, 7):
                return True

        if (mining_lvl <= luggage_lvl and mining_lvl <= fuel_lvl and mining_lvl <= shield_lvl and
            mining_price != "MAX" and balance >= mining_price):
            if self.upgrade_boost(account_id, 4):
                return True

        return False

    def get_upgrade_price(self, boost_data, boost_id, current_level):
        """الحصول على سعر الترقية"""
        if not boost_data or 'list' not in boost_data:
            return None
            
        for boost in boost_data['list']:
            if boost['id'] == boost_id and 'level_list' in boost:
                next_level = current_level + 1
                if str(next_level) in boost['level_list']:
                    return boost['level_list'][str(next_level)]['price_coin']
                else:
                    return "MAX"
        return None

    def check_boost_availability(self, account_id, user_data):
        """التحقق من توفر التعزيزات"""
        if not user_data or 'user' not in user_data:
            return {}

        user = user_data['user']
        current_time = user.get('locale_time', int(time.time() * 1000))
        
        fuel_ready = user.get('fuel_free_at') is None or user['fuel_free_at'] <= current_time
        shield_ready = (user.get('shield_free_at') is None or user['shield_free_at'] <= current_time) and user.get('shield_damage', 0) != 0
        field_ready = user.get('shield_free_immunity_at') is None or user['shield_free_immunity_at'] <= current_time
        roulette_ready = user.get('spin_after_at') is None or user['spin_after_at'] <= current_time

        return {
            'fuel_ready': fuel_ready,
            'shield_ready': shield_ready,
            'field_ready': field_ready,
            'roulette_ready': roulette_ready,
        }

    def check_daily_claim(self, account_id, user_data):
        """التحقق من المكافأة اليومية"""
        if not user_data or 'user' not in user_data:
            return False
            
        user = user_data['user']
        current_time = user.get('locale_time', int(time.time() * 1000))
        daily_next_at = user.get('daily_next_at', 0)
        
        # إذا كان الوقت الحالي أكبر من وقت المكافأة التالية أو لم يتم المطالبة بها اليوم
        if current_time >= daily_next_at or time.time() - self.accounts[account_id]['last_daily_claim'] >= 86400:
            return True
        return False

    def check_reward_video(self, account_id):
        """التحقق من مكافأة الفيديو"""
        # كل ساعتين (7200 ثانية)
        if time.time() - self.accounts[account_id]['last_reward_video'] >= 7200:
            return True
        return False

    def check_and_act(self, account_id):
        """التحقق وتنفيذ الإجراءات"""
        user_data = self.get_user_data(account_id)
        if not user_data:
            return

        # التحقق من المكافأة اليومية
        if self.check_daily_claim(account_id, user_data):
            if self.claim_daily_reward(account_id):
                return

        # التحقق من مكافأة الفيديو
        if self.check_reward_video(account_id):
            if self.claim_reward_video(account_id):
                return

        if self.check_and_upgrade(account_id):
            return

        availability = self.check_boost_availability(account_id, user_data)
        
        action_performed = False
        if availability.get('fuel_ready'):
            if self.buy_boost(account_id, 1):
                action_performed = True
        if availability.get('shield_ready'):
            if self.buy_boost(account_id, 2):
                action_performed = True
        if availability.get('field_ready'):
            if self.buy_boost(account_id, 3):
                action_performed = True
        if availability.get('roulette_ready'):
            if self.play_roulette(account_id):
                action_performed = True

        if time.time() - self.accounts[account_id]['last_claim'] >= 300:
            if self.claim_rewards(account_id):
                action_performed = True

    def format_time(self, milliseconds):
        """تنسيق الوقت"""
        if milliseconds is None or milliseconds <= 0:
            return "Ready"
        seconds = milliseconds / 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02d}:{int(seconds):02d}"

    def format_number(self, num):
        """تنسيق الأرقام"""
        if isinstance(num, str):
            return num
        return "{:,}".format(num)

    async def generate_status_message(self):
        """إنشاء رسالة الحالة"""
        message = "⌯ <b>Space Adventure Bot 🚀</b>\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for account_id, account in self.accounts.items():
            user_data = self.get_user_data(account_id)
            if not user_data or 'user' not in user_data:
                continue
                
            user = user_data['user']
            current_time = user.get('locale_time', int(time.time() * 1000))
            
            # حساب الأوقات المتبقية
            fuel_remaining = self.safe_time_diff(user.get('fuel_free_at'), current_time)
            shield_remaining = self.safe_time_diff(user.get('shield_free_at'), current_time)
            field_remaining = self.safe_time_diff(user.get('shield_free_immunity_at'), current_time)
            roulette_remaining = self.safe_time_diff(user.get('spin_after_at'), current_time)
            
            # بناء رسالة الحساب
            message += f"➥ <b>ACCOUNT [ {account['account_number']} ] 🚀</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n"
            message += f"➥ 🟡 <b>Coins:</b> {self.format_number(user.get('balance', 0))}   💎 <b>Gems:</b> {user.get('gems', 0)}\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n"
            message += f"➥ [⛏️Lv{user.get('level_claims', 1)}] [💰Lv{user.get('level_claim_max', 1)}] "
            message += f"[🛢️Lv{user.get('level_fuel', 1)}] [🛡Lv{user.get('level_shield', 1)}]\n\n"
            
            message += f"➥ [ 🎰{self.format_time(roulette_remaining)} ] [ ⛽{self.format_time(fuel_remaining)} ]\n"
            message += f"➥ [ 🔧{self.format_time(shield_remaining)} ] [ 🌀{self.format_time(field_remaining)} ]\n"
            
            # إظهار آخر إجراء أو خطأ
            if account['last_error']:
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                message += f"➥ ❌ <code>{account['last_error']}</code>\n"
            elif account['last_action'] and time.time() - account['last_action_time'] < 60:
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                message += f"➥ ✅ {account['last_action']}\n"
            
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # إضافة وقت التحديث الأخير
        message += f"🔄 <i>Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}</i>"
        
        return message

    def safe_time_diff(self, future_time, current_time):
        """حساب الفارق الزمني بأمان"""
        if future_time is None or current_time is None:
            return None
        return future_time - current_time

    async def update_status_message(self, context: ContextTypes.DEFAULT_TYPE):
        """تحديث رسالة الحالة"""
        if not self.status_message_id or not self.chat_id:
            return
            
        try:
            message = await self.generate_status_message()
            await context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.status_message_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            self.log_action(f"خطأ في تحديث رسالة الحالة: {e}", level='error')

    async def run_accounts_loop(self, context: ContextTypes.DEFAULT_TYPE):
        """حلقة تشغيل الحسابات"""
        while self.running:
            start_time = time.time()
            
            with self.lock:
                for account_id in self.accounts:
                    try:
                        self.check_and_act(account_id)
                    except Exception as e:
                        self.log_action(f"خطأ في الحساب: {e}", account_id, 'error')
                        await self.send_error_notification(context, account_id, str(e))
                        
                await self.update_status_message(context)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, self.update_interval - elapsed)
            time.sleep(sleep_time)

    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء تشغيل البوت"""
        if self.running:
            await update.message.reply_text("✅ البوت يعمل بالفعل!")
            return
            
        self.running = True
        self.chat_id = update.effective_chat.id
        
        # إرسال رسالة الحالة الأولى
        message = await self.generate_status_message()
        sent_message = await context.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode='HTML'
        )
        self.status_message_id = sent_message.message_id
        
        # بدء حلقة التشغيل في خلفية
        threading.Thread(
            target=lambda: asyncio.run(self.run_accounts_loop(context)),
            daemon=True
        ).start()
        
        await update.message.reply_text("🚀 بدأ تشغيل البوت بنجاح!")

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إيقاف البوت"""
        if not self.running:
            await update.message.reply_text("🛑 البوت متوقف بالفعل!")
            return
            
        self.running = False
        await update.message.reply_text("🛑 تم إيقاف البوت بنجاح!")

    async def update_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تحديث الحالة الآن"""
        if not self.running:
            await update.message.reply_text("⚠️ البوت متوقف. يرجى تشغيله أولاً!")
            return
            
        with self.lock:
            await self.update_status_message(context)
            await update.message.reply_text("🔄 تم تحديث الحالة الآن!")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض رسالة المساعدة"""
        help_text = (
            "🚀 <b>Space Adventure Bot - Help</b>\n\n"
            "📌 <b>الأوامر المتاحة:</b>\n"
            "/start - بدء تشغيل البوت\n"
            "/stop - إيقاف البوت\n"
            "/update - تحديث الحالة الآن\n"
            "/help - عرض هذه الرسالة\n\n"
            "⚙️ <b>ميزات البوت:</b>\n"
            "- إدارة متعددة الحسابات\n"
            "- تحديث تلقائي للحالة\n"
            "- إشعارات فورية بالأخطاء\n"
            "- واجهة تحكم كاملة\n\n"
            "📂 <b>ملفات التكوين:</b>\n"
            "يجب وضع ملف Accounts.txt في نفس المجلد"
        )
        await update.message.reply_text(help_text, parse_mode='HTML')

def main():
    """الدالة الرئيسية لتشغيل البوت"""
    print(f"{B}{C}🚀 Starting Space Adventure Telegram Bot...{S}")
    
    try:
        bot = SpaceAdventureBot()
        
        # إنشاء تطبيق التليجرام
        application = Application.builder().token(TOKEN).build()
        
        # إضافة معالجات الأوامر
        application.add_handler(CommandHandler("start", bot.start_bot))
        application.add_handler(CommandHandler("stop", bot.stop_bot))
        application.add_handler(CommandHandler("update", bot.update_now))
        application.add_handler(CommandHandler("help", bot.show_help))
        
        print(f"{B}{G}✅ Bot is ready!{S}")
        
        # بدء البوت
        application.run_polling()
        
    except Exception as e:
        print(f"{B}{R}❌ Error starting bot: {e}{S}")
        raise

if __name__ == "__main__":
    import asyncio
    main()
