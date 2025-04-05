import os
import time
import threading
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
                            'last_error': None
                        }
            print(f"{B}{G}✅ تم تحميل {len(self.accounts)} حساب بنجاح!{S}")
        except FileNotFoundError:
            print(f"{B}{R}❌ خطأ: لم يتم العثور على ملف Accounts.txt!{S}")
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

            response = account['session'].post(url, data=data, headers=headers)
            response.raise_for_status()
            data = response.json()

            if 'token' in data:
                account['token'] = data['token']
                account['auth_id'] = account_id
                account['failed_auth'] = 0
                account['last_error'] = None
                return True
            else:
                account['failed_auth'] += 1
                account['last_error'] = "فشل المصادقة: لا يوجد توكن"
                return False
        except Exception as e:
            account['failed_auth'] += 1
            account['last_error'] = f"خطأ المصادقة: {str(e)}"
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
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['last_error'] = None
            return response.json()
        except Exception as e:
            account['last_error'] = f"خطأ جلب البيانات: {str(e)}"
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
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['boost_data'] = response.json()
            account['last_boost_check'] = time.time()
            account['last_error'] = None
            return account['boost_data']
        except Exception as e:
            account['last_error'] = f"خطأ جلب التعزيزات: {str(e)}"
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
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            boost_name = {
                1: "⛽ تعبئة الوقود",
                2: "🔧 إصلاح الدرع", 
                3: "🌀 حقل القوة"
            }.get(boost_id, f"التعزيز {boost_id}")
            
            account['last_action'] = f"{boost_name} تم ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            return True
        except Exception as e:
            account['last_action'] = f"خطأ في التعزيز {boost_id}"
            account['last_error'] = f"خطأ شراء التعزيز: {str(e)}"
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
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            account['last_action'] = "🎰 لعب الروليت ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            return True
        except Exception as e:
            account['last_action'] = "🎰 خطأ في الروليت"
            account['last_error'] = f"خطأ لعب الروليت: {str(e)}"
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
            response = account['session'].post(url, headers=headers)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers)
                else:
                    return False

            response.raise_for_status()
            account['last_claim'] = time.time()
            account['last_action'] = "🪙 جمع العملات ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            return True
        except Exception as e:
            account['last_action'] = "🪙 خطأ في الجمع"
            account['last_error'] = f"خطأ جمع المكافآت: {str(e)}"
            return False

    def upgrade_boost(self, account_id, boost_id):
        """ترقية التعزيز"""
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
            payload = {"id": boost_id, "method": "coin"}
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            boost_name = {
                4: "⛏️ التعدين",
                5: "💰 الأمتعة",
                6: "🛢️ خزان الوقود",
                7: "🛡️ الدرع"
            }.get(boost_id, f"التعزيز {boost_id}")
            
            account['last_action'] = f"🚀 {boost_name} تمت ترقيته ✓"
            account['last_action_time'] = time.time()
            account['last_upgrade'] = time.time()
            account['last_error'] = None
            return True
        except Exception as e:
            account['last_action'] = f"🚀 خطأ في الترقية {boost_id}"
            account['last_error'] = f"خطأ ترقية التعزيز: {str(e)}"
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

    def check_and_act(self, account_id):
        """التحقق وتنفيذ الإجراءات"""
        user_data = self.get_user_data(account_id)
        if not user_data:
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
            return "جاهز"
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
            print(f"{R}❌ Error updating status message: {e}{S}")

    async def run_accounts_loop(self, context: ContextTypes.DEFAULT_TYPE):
        """حلقة تشغيل الحسابات"""
        while self.running:
            start_time = time.time()
            
            with self.lock:
                for account_id in self.accounts:
                    try:
                        self.check_and_act(account_id)
                    except Exception as e:
                        print(f"{R}❌ Error in account {account_id}: {e}{S}")
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
           - "تحديث تلقائي للحالة\n"
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