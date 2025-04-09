import os
import time
import random
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
        self.last_reward_video_check = 0

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
                            'last_error': None,
                            'last_daily_claim': 0,
                            'last_reward_video': 0,
                            'retry_delay': 5,  # Initial retry delay in seconds
                            'xsrf_token': None,
                            'session_token': None
                        }
            self.log_action(f"Successfully loaded {len(self.accounts)} accounts!")
        except FileNotFoundError:
            self.log_action("❌ Error: Accounts.txt file not found!", level='error')
            raise

    async def send_error_notification(self, context: ContextTypes.DEFAULT_TYPE, account_id, error_msg, response_text=None):
        """Send error notification to admin"""
        account = self.accounts[account_id]
        msg = (
            f"⚠️ <b>Error in account {account['account_number']}</b>\n"
            f"🆔: <code>{account_id}</code>\n"
            f"📛 Error: <code>{error_msg}</code>\n"
        )
        
        if response_text:
            msg += f"📄 Response: <code>{response_text[:1000]}</code>\n"
        
        msg += f"⏱️ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        await context.bot.send_message(
            chat_id=self.chat_id,
            text=msg,
            parse_mode='HTML'
        )

    def get_headers(self, account_id):
        """Generate headers for API requests"""
        account = self.accounts.get(account_id)
        if not account:
            return {}
            
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'en-US,en;q=0.7',
            'Authorization': f"Bearer {account['token']}",
            'Origin': 'https://space-adventure.online',
            'Priority': 'u=1, i',
            'Referer': 'https://space-adventure.online/game',
            'Sec-Ch-Ua': '"Brave";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Gpc': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
            'X-Auth-Id': str(account['auth_id']),
            'X-Deviceid': self.generate_device_id(),
            'X-Nonce': self.generate_nonce(),
            'X-Timestamp': str(int(time.time())),
        }
        
        if account['xsrf_token']:
            headers['X-Xsrf-Token'] = account['xsrf_token']
            
        return headers

    def generate_device_id(self):
        """Generate a random device ID"""
        return ''.join(random.choices('0123456789abcdef', k=32))

    def generate_nonce(self):
        """Generate a random nonce"""
        return f"{uuid.uuid4()}-{int(time.time())}"

    def authenticate_account(self, account_id, retry=False):
        """Authenticate account with retry logic"""
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
                account['retry_delay'] = 5  # Reset retry delay on success
                
                # Extract cookies from response
                if 'set-cookie' in response.headers:
                    cookies = response.headers['set-cookie'].split(',')
                    for cookie in cookies:
                        if 'XSRF-TOKEN' in cookie:
                            account['xsrf_token'] = cookie.split(';')[0].split('=')[1]
                        elif 'spaceadventure_session' in cookie:
                            account['session_token'] = cookie.split(';')[0].split('=')[1]
                
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
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff, max 5 minutes
            self.log_action(f"Authentication failed: {str(e)}", account_id, 'error')
            return False

    def get_user_data(self, account_id):
        """Get user data with retry logic"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            if self.authenticate_account(account_id, retry=True):
                return self.get_user_data(account_id)
            return None

        try:
            url = f"{self.base_url}/user/get"
            headers = self.get_headers(account_id)
            
            self.log_action(f"Fetching user data...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers = self.get_headers(account_id)
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            data = response.json()
            self.log_action(f"Successfully fetched user data", account_id)
            return data
        except Exception as e:
            account['last_error'] = f"Error fetching data: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to fetch user data: {str(e)}", account_id, 'error')
            return None

    def get_boost_data(self, account_id):
        """Get boost data with retry logic"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return None
            
        if time.time() - account['last_boost_check'] < 300 and account['boost_data']:
            return account['boost_data']
            
        try:
            url = f"{self.base_url}/boost/get/"
            headers = self.get_headers(account_id)
            
            self.log_action(f"Fetching boost data...", account_id)
            response = account['session'].get(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers = self.get_headers(account_id)
                    response = account['session'].get(url, headers=headers)
                else:
                    return None

            response.raise_for_status()
            account['boost_data'] = response.json()
            account['last_boost_check'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action(f"Successfully fetched boost data", account_id)
            return account['boost_data']
        except Exception as e:
            account['last_error'] = f"Error fetching boosts: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to fetch boost data: {str(e)}", account_id, 'error')
            return None

    def buy_boost(self, account_id, boost_id):
        """Buy boost with retry logic"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/boost/buy/"
            headers = self.get_headers(account_id)
            headers['Content-Type'] = 'application/json'
            
            payload = {"id": boost_id, "method": "free"}
            
            boost_name = {
                1: "⛽ Fuel Refill",
                2: "🔧 Shield Repair", 
                3: "🌀 Force Field"
            }.get(boost_id, f"Boost {boost_id}")
            
            self.log_action(f"Buying {boost_name}...", account_id)
            time.sleep(random.uniform(0.5, 1.5))  # Random delay to mimic human behavior
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers = self.get_headers(account_id)
                    headers['Content-Type'] = 'application/json'
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            
            account['last_action'] = f"{boost_name} ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action(f"Successfully bought {boost_name}", account_id)
            return True
        except Exception as e:
            account['last_action'] = f"Error in boost {boost_id}"
            account['last_error'] = f"Boost purchase error: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to buy {boost_name}: {str(e)}", account_id, 'error')
            return False

    def play_roulette(self, account_id):
        """Play roulette with retry logic"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/roulette/buy/"
            headers = self.get_headers(account_id)
            headers['Content-Type'] = 'application/json'
            
            payload = {"method": "free"}
            
            self.log_action("Playing roulette...", account_id)
            time.sleep(random.uniform(0.5, 1.5))  # Random delay to mimic human behavior
            response = account['session'].post(url, headers=headers, json=payload)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers = self.get_headers(account_id)
                    headers['Content-Type'] = 'application/json'
                    response = account['session'].post(url, headers=headers, json=payload)
                else:
                    return False

            response.raise_for_status()
            account['last_action'] = "🎰 Roulette ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action("Successfully played roulette", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎰 Roulette error"
            account['last_error'] = f"Roulette error: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to play roulette: {str(e)}", account_id, 'error')
            return False

    def claim_rewards(self, account_id):
        """Claim rewards with retry logic"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            url = f"{self.base_url}/game/claiming/"
            headers = self.get_headers(account_id)
            
            self.log_action("Claiming rewards...", account_id)
            time.sleep(random.uniform(0.5, 1.5))  # Random delay to mimic human behavior
            response = account['session'].post(url, headers=headers)

            if response.status_code == 401:
                self.log_action(f"Token expired, re-authenticating...", account_id, 'warning')
                if self.authenticate_account(account_id, retry=True):
                    headers = self.get_headers(account_id)
                    response = account['session'].post(url, headers=headers)
                else:
                    return False

            response.raise_for_status()
            account['last_claim'] = time.time()
            account['last_action'] = "🪙 Coin Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action("Successfully claimed rewards", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🪙 Claim Failed❌"
            account['last_error'] = f"🪙 Claim Failed❌: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to claim rewards: {str(e)}", account_id, 'error')
            return False

    def claim_daily_reward(self, account_id):
        """Claim daily reward with proper sequence"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            headers = self.get_headers(account_id)
            headers['Content-Type'] = 'application/json'
            
            # First request to get ads
            get_ads_url = f"{self.base_url}/user/get_ads/"
            payload = {"type": "daily_activity"}
            
            self.log_action("Requesting daily ads...", account_id)
            time.sleep(random.uniform(1, 3))  # Random delay to mimic human behavior
            ads_response = account['session'].post(get_ads_url, headers=headers, json=payload)
            ads_response.raise_for_status()
            
            # Then claim the reward
            claim_url = f"{self.base_url}/dayli/claim_activity/"
            self.log_action("Claiming daily reward...", account_id)
            time.sleep(random.uniform(1, 3))  # Random delay to mimic human behavior
            claim_response = account['session'].post(claim_url, headers=headers)
            claim_response.raise_for_status()
            
            account['last_daily_claim'] = time.time()
            account['last_action'] = "🎁 Daily Reward Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action("Successfully claimed daily reward", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎁 Daily Claim Failed❌"
            account['last_error'] = f"🎁 Daily Claim Failed❌: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to claim daily reward: {str(e)}", account_id, 'error')
            return False

    def claim_reward_video(self, account_id):
        """Claim video reward with proper sequence"""
        account = self.accounts.get(account_id)
        if not account or not account['token']:
            return False

        try:
            headers = self.get_headers(account_id)
            headers['Content-Type'] = 'application/json'
            
            # We need to make 3 successful requests with ads request before each
            for i in range(1, 4):
                # First request ads
                get_ads_url = f"{self.base_url}/user/get_ads/"
                ads_payload = {"type": "tasks_reward"}
                
                self.log_action(f"Requesting video reward ads ({i}/3)...", account_id)
                time.sleep(random.uniform(1, 3))  # Random delay to mimic human behavior
                ads_response = account['session'].post(get_ads_url, headers=headers, json=ads_payload)
                ads_response.raise_for_status()
                
                # Then make the video reward request
                reward_url = f"{self.base_url}/tasks/reward-video/"
                self.log_action(f"Claiming video reward ({i}/3)...", account_id)
                time.sleep(random.uniform(1, 3))  # Random delay to mimic human behavior
                reward_response = account['session'].put(reward_url, headers=headers)
                reward_response.raise_for_status()
                
                data = reward_response.json()
                
                # Verify expected response
                if i < 3 and (data.get('event') != 'watch' or data.get('count') != i):
                    raise Exception(f"Unexpected response for request {i}: {data}")
                elif i == 3 and (data.get('event') != 'reward' or data.get('count') != 0):
                    raise Exception(f"Final reward not received: {data}")
            
            account['last_reward_video'] = time.time()
            account['last_action'] = "🎥 Video Reward Claimed ✓"
            account['last_action_time'] = time.time()
            account['last_error'] = None
            account['retry_delay'] = 5  # Reset retry delay on success
            self.log_action("Successfully claimed video reward", account_id)
            return True
        except Exception as e:
            account['last_action'] = "🎥 Video Claim Failed❌"
            account['last_error'] = f"🎥 Video Claim Failed❌: {str(e)}"
            account['retry_delay'] = min(account['retry_delay'] * 2, 300)  # Exponential backoff
            self.log_action(f"Failed to claim video reward: {str(e)}", account_id, 'error')
            return False

    # ... (rest of the methods remain the same as in the previous version)

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
    import uuid  # Added for nonce generation
    main()
