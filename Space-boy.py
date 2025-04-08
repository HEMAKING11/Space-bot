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

# Bot token - replace with your token
TOKEN = "7717260828:AAFIyiwyX_ifmmBcebYXFEdLuYXZtC_R3Go"

# Logging setup
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
        self.update_interval = 30  # seconds between updates

    def log_action(self, message, account_id=None, level='info'):
        """Log actions to file and console"""
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
        """Load accounts from Accounts.txt file"""
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
            self.log_action(f"Successfully loaded {len(self.accounts)} accounts!")
        except FileNotFoundError:
            self.log_action("❌ Error: Accounts.txt file not found!", level='error')
            raise

    async def send_error_notification(self, context: ContextTypes.DEFAULT_TYPE, account_id, error_msg):
        """Send error notification to admin"""
        account = self.accounts[account_id]
        msg = (
            f"⚠️ <b>Error in account {account['account_number']}</b>\n"
            f"🆔: <code>{account_id}</code>\n"
            f"📛 Error: <code>{error_msg}</code>\n"
            f"⏱️ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await context.bot.send_message(
            chat_id=self.chat_id,
            text=msg,
            parse_mode='HTML'
        )

    def authenticate_account(self, account_id, retry=False):
        """Authenticate account"""
        account = self.accounts[account_id]
        try:
            url = f"{self.base_url}/auth/telegram"
            data = account['query_id']
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': str(len(data)),
                'User-Agent': 'Mozilla/5.0',
            }

            self.log_action(f"Authenticating account...", account_id)
            response = account['session'].post(url, data=data, headers=headers)
            response.raise_for_status()
            data = response.json()

            if 'token' in data:
                account['token'] = data['token']
                account['auth_id'] = account_id
                account['failed_auth'] = 0
                account['last_error'] = None
                self.log_action(f"Authentication successful", account_id)
                return True
            else:
                account['failed_auth'] += 1
                account['last_error'] = "Authentication failed: No token received"
                self.log_action(f"Authentication failed: No token in response", account_id, 'error')
                return False
        except Exception as e:
            account['failed_auth'] += 1
            account['last_error'] = f"Authentication error: {str(e)}"
            self.log_action(f"Authentication failed: {str(e)}", account_id, 'error')
            return False

    def get_user_data(self, account_id):
        """Get user data"""
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
            self.log_action(f"Fetching user data...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['last_error'] = None
            data = response.json()
            self.log_action(f"Successfully fetched user data", account_id)
            return data
        except Exception as e:
            account['last_error'] = f"Error fetching data: {str(e)}"
            self.log_action(f"Failed to fetch user data: {str(e)}", account_id, 'error')
            return None

    def get_boost_data(self, account_id):
        """Get boost data"""
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
            self.log_action(f"Fetching boost data...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['boost_data'] = response.json()
            account['last_boost_check'] = time.time()
            account['last_error'] = None
            self.log_action(f"Successfully fetched boost data", account_id)
            return account['boost_data']
        except Exception as e:
            account['last_error'] = f"Error fetching boosts: {str(e)}"
            self.log_action(f"Failed to fetch boost data: {str(e)}", account_id, 'error')
            return None

    def buy_boost(self, account_id, boost_id):
        """Buy boost"""
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
                1: "⛽ Fuel Refill",
                2: "🔧 Shield Repair", 
                3: "🌀 Force Field"
            }.get(boost_id, f"Boost {boost_id}")
            
            self.log_action(f"Buying {boost_name}...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            account['last_action'] = f"{boost_name} ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action(f"Successfully bought {boost_name}", account_id)
            return True
        except Exception as e:
            account['last_action'] = f"Error in boost {boost_id}"
            account['last_error'] = f"Boost purchase error: {str(e)}"
            self.log_action(f"Failed to buy {boost_name}: {str(e)}", account_id, 'error')
            return False

    def play_roulette(self, account_id):
        """Play roulette"""
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
            
            self.log_action("Playing roulette...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers['Authorization'] = f"Bearer {account['token']}"
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            account['last_action'] = "🎰 Roulette ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            self.log_action("Successfully played roulette", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎰 Roulette error"
            account['last_error'] = f"Roulette error: {str(e)}"
            self.log_action(f"Failed to play roulette: {str(e)}", account_id, 'error')
            return False

    def claim_rewards(self, account_id):
        """Claim rewards"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/game/claiming/"
            headers = {
                'Authorization': f"Bearer {account['token']}",
                'X-Auth-Id': account['auth_id']
            }
            self.log_action("Claiming rewards...", account_id)
            response = account['session'].post(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
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
            self.log_action("Successfully claimed rewards", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🪙 Claim Failed❌"
            account['last_error'] = f"🪙 Claim Failed❌: {str(e)}"
            self.log_action(f"Failed to claim rewards: {str(e)}", account_id, 'error')
            return False

    def upgrade_boost(self, account_id, boost_id):
        """Upgrade boost"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            # Check upgrade level limits
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
            
            # Set max level based on boost_id
            max_level = 6 if boost_id == 4 else 5
            if current_level >= max_level:
                self.log_action(f"Cannot upgrade boost {boost_id} beyond level {max_level}", account_id, 'warning')
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
            
            self.log_action(f"Upgrading {boost_name}...", account_id)
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
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
            self.log_action(f"Successfully upgraded {boost_name}", account_id)
            return True
        except Exception as e:
            account['last_action'] = f"❌🚀 Upgrade error {boost_id}"
            account['last_error'] = f"❌🚀 Upgrade error: {str(e)}"
            self.log_action(f"Failed to upgrade boost {boost_id}: {str(e)}", account_id, 'error')
            return False

    def check_and_upgrade(self, account_id):
        """Check and upgrade boosts"""
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
        """Get upgrade price"""
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
        """Check boost availability with null checks"""
        if not user_data or 'user' not in user_data:
            return {}

        user = user_data['user']
        current_time = user.get('locale_time', int(time.time() * 1000))
        
        # Handle null values and set defaults
        fuel_free_at = user.get('fuel_free_at', 0)
        shield_free_at = user.get('shield_free_at', 0)
        shield_free_immunity_at = user.get('shield_free_immunity_at', 0)
        spin_after_at = user.get('spin_after_at', 0)
        
        # Verify all values are numeric
        if not all(isinstance(x, (int, float)) for x in [current_time, fuel_free_at, shield_free_at, shield_free_immunity_at, spin_after_at]):
            self.log_action("Invalid time values for boost check", account_id, 'warning')
            return {
                'fuel_ready': False,
                'shield_ready': False,
                'field_ready': False,
                'roulette_ready': False,
            }
        
        fuel_ready = fuel_free_at <= current_time
        shield_ready = shield_free_at <= current_time and user.get('shield_damage', 0) != 0
        field_ready = shield_free_immunity_at <= current_time
        roulette_ready = spin_after_at <= current_time

        return {
            'fuel_ready': fuel_ready,
            'shield_ready': shield_ready,
            'field_ready': field_ready,
            'roulette_ready': roulette_ready,
        }

    def safe_time_diff(self, future_time, current_time):
        """Calculate time difference safely with null checks"""
        if future_time is None or current_time is None:
            return 0  # Return 0 instead of None to avoid comparison errors
        return max(0, future_time - current_time)  # Ensure result is not negative

    def check_and_act(self, account_id):
        """Check and perform actions"""
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
        """Format time"""
        if milliseconds is None or milliseconds <= 0:
            return "Ready"
        seconds = milliseconds / 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes):02d}:{int(seconds):02d}"

    def format_number(self, num):
        """Format numbers"""
        if isinstance(num, str):
            return num
        return "{:,}".format(num)

    async def generate_status_message(self):
        """Generate status message"""
        message = "⌯ <b>Space Adventure Bot 🚀</b>\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for account_id, account in self.accounts.items():
            user_data = self.get_user_data(account_id)
            if not user_data or 'user' not in user_data:
                continue
                
            user = user_data['user']
            current_time = user.get('locale_time', int(time.time() * 1000))
            
            # Calculate remaining times
            fuel_remaining = self.safe_time_diff(user.get('fuel_free_at'), current_time)
            shield_remaining = self.safe_time_diff(user.get('shield_free_at'), current_time)
            field_remaining = self.safe_time_diff(user.get('shield_free_immunity_at'), current_time)
            roulette_remaining = self.safe_time_diff(user.get('spin_after_at'), current_time)
            
            # Build account message
            message += f"➥ <b>ACCOUNT [ {account['account_number']} ] 🚀</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n"
            message += f"➥ 🟡 <b>Coins:</b> {self.format_number(user.get('balance', 0))}   💎 <b>Gems:</b> {user.get('gems', 0)}\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n"
            message += f"➥ [⛏️Lv{user.get('level_claims', 1)}] [💰Lv{user.get('level_claim_max', 1)}] "
            message += f"[🛢️Lv{user.get('level_fuel', 1)}] [🛡Lv{user.get('level_shield', 1)}]\n\n"
            
            message += f"➥ [ 🎰{self.format_time(roulette_remaining)} ] [ ⛽{self.format_time(fuel_remaining)} ]\n"
            message += f"➥ [ 🔧{self.format_time(shield_remaining)} ] [ 🌀{self.format_time(field_remaining)} ]\n"
            
            # Show last action or error
            if account['last_error']:
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                message += f"➥ ❌ <code>{account['last_error']}</code>\n"
            elif account['last_action'] and time.time() - account['last_action_time'] < 60:
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                message += f"➥ ✅ {account['last_action']}\n"
            
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Add last update time
        message += f"🔄 <i>Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}</i>"
        
        return message

    async def update_status_message(self, context: ContextTypes.DEFAULT_TYPE):
        """Update status message"""
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
            self.log_action(f"Error updating status message: {e}", level='error')

    async def run_accounts_loop(self, context: ContextTypes.DEFAULT_TYPE):
        """Main accounts loop"""
        while self.running:
            start_time = time.time()
            
            with self.lock:
                for account_id in self.accounts:
                    try:
                        self.check_and_act(account_id)
                    except Exception as e:
                        self.log_action(f"Account error: {e}", account_id, 'error')
                        await self.send_error_notification(context, account_id, str(e))
                        
                await self.update_status_message(context)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, self.update_interval - elapsed)
            time.sleep(sleep_time)

    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start bot command"""
        if self.running:
            await update.message.reply_text("✅ Bot is already running!")
            return
            
        self.running = True
        self.chat_id = update.effective_chat.id
        
        # Send initial status message
        message = await self.generate_status_message()
        sent_message = await context.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode='HTML'
        )
        self.status_message_id = sent_message.message_id
        
        # Start background loop
        threading.Thread(
            target=lambda: asyncio.run(self.run_accounts_loop(context)),
            daemon=True
        ).start()
        
        await update.message.reply_text("🚀 Bot started successfully!")

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop bot command"""
        if not self.running:
            await update.message.reply_text("🛑 Bot is already stopped!")
            return
            
        self.running = False
        await update.message.reply_text("🛑 Bot stopped successfully!")

    async def update_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Force update command"""
        if not self.running:
            await update.message.reply_text("⚠️ Bot is stopped. Please start it first!")
            return
            
        with self.lock:
            await self.update_status_message(context)
            await update.message.reply_text("🔄 Status updated now!")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message"""
        help_text = (
            "🚀 <b>Space Adventure Bot - Help</b>\n\n"
            "📌 <b>Available commands:</b>\n"
            "/start - Start the bot\n"
            "/stop - Stop the bot\n"
            "/update - Force status update\n"
            "/help - Show this message\n\n"
            "⚙️ <b>Bot features:</b>\n"
            "- Multiple account management\n"
            "- Automatic status updates\n"
            "- Instant error notifications\n"
            "- Full control interface\n\n"
            "📂 <b>Configuration files:</b>\n"
            "Place Accounts.txt in the same folder"
        )
        await update.message.reply_text(help_text, parse_mode='HTML')

def main():
    """Main function to run the bot"""
    print(f"{B}{C}🚀 Starting Space Adventure Telegram Bot...{S}")
    
    try:
        bot = SpaceAdventureBot()
        
        # Create Telegram application
        application = Application.builder().token(TOKEN).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", bot.start_bot))
        application.add_handler(CommandHandler("stop", bot.stop_bot))
        application.add_handler(CommandHandler("update", bot.update_now))
        application.add_handler(CommandHandler("help", bot.show_help))
        
        print(f"{B}{G}✅ Bot is ready!{S}")
        
        # Start bot
        application.run_polling()
        
    except Exception as e:
        print(f"{B}{R}❌ Error starting bot: {e}{S}")
        raise

if __name__ == "__main__":
    import asyncio
    main()
