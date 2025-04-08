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

# Bot configuration
TOKEN = "7717260828:AAFIyiwyX_ifmmBcebYXFEdLuYXZtC_R3Go"
BASE_URL = "https://space-adventure.online/api"
UPDATE_INTERVAL = 30  # seconds between updates
REWARD_VIDEO_INTERVAL = 7200  # 2 hours in seconds

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

class SpaceAdventureBot:
    def __init__(self):
        self.accounts = {}
        self.lock = threading.Lock()
        self.status_message_id = None
        self.chat_id = None
        self.running = False
        self.load_accounts()

    def load_accounts(self):
        """Load accounts from Accounts.txt file with enhanced error handling"""
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
                            'failed_auth': 0,
                            'session': requests.Session(),
                            'last_action': None,
                            'last_action_time': 0,
                            'last_error': None,
                            'last_daily_check': 0,
                            'last_reward_video': 0,
                            'reward_video_attempts': 0
                        }
            logger.info(f"Successfully loaded {len(self.accounts)} accounts")
        except Exception as e:
            logger.error(f"Failed to load accounts: {str(e)}")
            raise

    async def send_error_notification(self, context: ContextTypes.DEFAULT_TYPE, account_id, error_msg, response=None):
        """Send detailed error notification to admin"""
        account = self.accounts[account_id]
        msg = (
            f"⚠️ <b>Error in account {account['account_number']}</b>\n"
            f"🆔: <code>{account_id}</code>\n"
            f"📛 Error: <code>{error_msg}</code>\n"
        )
        
        if response:
            msg += f"📄 Response: <code>{response.text[:200]}</code>\n"
        
        msg += f"⏱️ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        await context.bot.send_message(
            chat_id=self.chat_id,
            text=msg,
            parse_mode='HTML'
        )

    def authenticate_account(self, account_id):
        """Authenticate account with proper error handling"""
        account = self.accounts[account_id]
        try:
            response = account['session'].post(
                f"{BASE_URL}/auth/telegram",
                data=account['query_id'],
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Content-Length': str(len(account['query_id'])),
                    'User-Agent': 'Mozilla/5.0',
                }
            )
            response.raise_for_status()
            data = response.json()

            if 'token' not in data:
                raise ValueError("No token in response")
                
            account['token'] = data['token']
            account['auth_id'] = account_id
            account['failed_auth'] = 0
            account['last_error'] = None
            logger.info(f"Account {account['account_number']} authenticated successfully")
            return True
            
        except Exception as e:
            account['failed_auth'] += 1
            error_msg = f"Auth failed: {str(e)}"
            account['last_error'] = error_msg
            logger.error(f"Account {account['account_number']} authentication failed: {error_msg}")
            return False

    def make_api_request(self, account_id, method, endpoint, payload=None, expected_status=200):
        """Generic API request handler with retry logic"""
        account = self.accounts.get(account_id)
        if not account:
            return None

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                if not account['token'] and not self.authenticate_account(account_id):
                    continue

                headers = {
                    'Authorization': f"Bearer {account['token']}",
                    'X-Auth-Id': account['auth_id'],
                    'Content-Type': 'application/json'
                }

                url = f"{BASE_URL}/{endpoint}"
                
                if method == 'GET':
                    response = account['session'].get(url, headers=headers)
                elif method == 'POST':
                    response = account['session'].post(url, headers=headers, json=payload)
                elif method == 'PUT':
                    response = account['session'].put(url, headers=headers, json=payload)
                else:
                    raise ValueError("Unsupported HTTP method")

                if response.status_code == 401 and attempt < max_retries:
                    logger.warning(f"Account {account['account_number']} token expired, reauthenticating...")
                    if not self.authenticate_account(account_id):
                        continue
                    headers['Authorization'] = f"Bearer {account['token']}"
                    continue

                response.raise_for_status()
                return response.json()

            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"Account {account['account_number']} API request failed: {str(e)}")
                    account['last_error'] = f"API error: {str(e)}"
                    return None

        return None

    def check_daily_reward(self, account_id):
        """Check and claim daily reward with proper timing"""
        account = self.accounts[account_id]
        
        # Get user data to check daily_next_at
        user_data = self.make_api_request(account_id, 'GET', 'user/get')
        if not user_data or 'user' not in user_data:
            return False
            
        user = user_data['user']
        current_time = user.get('locale_time', int(time.time() * 1000))
        daily_next_at = user.get('daily_next_at', 0)
        
        # Check if daily reward is available
        if daily_next_at == 0 or current_time >= daily_next_at:
            # First request ads
            ads_response = self.make_api_request(
                account_id,
                'POST',
                'user/get_ads/',
                {'type': 'daily_activity'}
            )
            
            if not ads_response:
                return False
                
            # Then claim the reward
            claim_response = self.make_api_request(
                account_id,
                'POST',
                'dayli/claim_activity/'
            )
            
            if claim_response:
                account['last_action'] = "🎁 Daily reward claimed ✓"
                account['last_action_time'] = time.time()
                account['last_daily_check'] = time.time()
                logger.info(f"Account {account['account_number']} successfully claimed daily reward")
                return True
                
        return False

    def claim_video_rewards(self, account_id):
        """Claim video rewards with 3-step process"""
        account = self.accounts[account_id]
        success = True
        
        for step in range(1, 4):
            # First request ads for each step
            ads_response = self.make_api_request(
                account_id,
                'POST',
                'user/get_ads/',
                {'type': 'tasks_reward'}
            )
            
            if not ads_response:
                success = False
                break
                
            # Then make the reward video request
            reward_response = self.make_api_request(
                account_id,
                'PUT',
                'tasks/reward-video/'
            )
            
            if not reward_response:
                success = False
                break
                
            # Verify expected response
            if step < 3 and reward_response.get('event') != 'watch' or reward_response.get('count') != step:
                success = False
                logger.warning(f"Account {account['account_number']} invalid reward video response at step {step}")
                break
                
            if step == 3 and reward_response.get('event') != 'reward' or reward_response.get('count') != 0:
                success = False
                logger.warning(f"Account {account['account_number']} final reward video response invalid")
                break
                
            time.sleep(1)  # Small delay between steps
        
        if success:
            account['last_reward_video'] = time.time()
            account['reward_video_attempts'] = 0
            account['last_action'] = "🎥 Video rewards claimed ✓"
            account['last_action_time'] = time.time()
            logger.info(f"Account {account['account_number']} successfully claimed video rewards")
        else:
            account['reward_video_attempts'] += 1
            logger.warning(f"Account {account['account_number']} failed to claim video rewards (attempt {account['reward_video_attempts']})")
            
        return success

    def perform_account_actions(self, account_id):
        """Perform all required actions for an account"""
        account = self.accounts[account_id]
        
        # Check daily reward every hour
        if time.time() - account['last_daily_check'] >= 3600:
            self.check_daily_reward(account_id)
            
        # Check video rewards every 2 hours
        if time.time() - account['last_reward_video'] >= REWARD_VIDEO_INTERVAL:
            self.claim_video_rewards(account_id)
            
        # Other existing actions (boosts, roulette, etc.)
        # ... (keep your existing action logic here)

    async def update_status_message(self, context: ContextTypes.DEFAULT_TYPE):
        """Generate and update status message with all account info"""
        if not self.status_message_id or not self.chat_id:
            return
            
        try:
            message = "⌯ <b>Space Adventure Bot Status</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for account_id, account in self.accounts.items():
                user_data = self.make_api_request(account_id, 'GET', 'user/get')
                
                message += f"➥ <b>Account {account['account_number']}</b>\n"
                message += "━━━━━━━━━━━━━━━━━━━━\n"
                
                if user_data and 'user' in user_data:
                    user = user_data['user']
                    message += f"🟡 Coins: {user.get('balance', 0):,} | 💎 Gems: {user.get('gems', 0)}\n"
                    message += f"⛏️ Mining: Lv{user.get('level_claims', 1)} | 💰 Capacity: Lv{user.get('level_claim_max', 1)}\n"
                    
                    # Show next daily reward time if available
                    if 'daily_next_at' in user:
                        remaining = (user['daily_next_at'] - user.get('locale_time', int(time.time() * 1000))) / 1000
                        if remaining > 0:
                            message += f"🎁 Next daily: {time.strftime('%H:%M:%S', time.gmtime(remaining))}\n"
                        else:
                            message += "🎁 Daily reward available\n"
                
                # Show last action or error
                if account['last_error']:
                    message += f"❌ Error: {account['last_error']}\n"
                elif account['last_action']:
                    message += f"✅ {account['last_action']}\n"
                    
                message += "━━━━━━━━━━━━━━━━━━━━\n\n"
            
            message += f"🔄 Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            await context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.status_message_id,
                text=message,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Failed to update status message: {str(e)}")

    async def run_accounts_loop(self, context: ContextTypes.DEFAULT_TYPE):
        """Main processing loop for all accounts"""
        while self.running:
            start_time = time.time()
            
            with self.lock:
                for account_id in self.accounts:
                    try:
                        self.perform_account_actions(account_id)
                    except Exception as e:
                        logger.error(f"Account {self.accounts[account_id]['account_number']} processing error: {str(e)}")
                        await self.send_error_notification(context, account_id, str(e))
                        
                await self.update_status_message(context)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, UPDATE_INTERVAL - elapsed)
            time.sleep(sleep_time)

    # Telegram command handlers (keep your existing start/stop/update/help commands)
    # ... (your existing command handlers here)

def main():
    """Main application entry point"""
    try:
        bot = SpaceAdventureBot()
        application = Application.builder().token(TOKEN).build()
        
        # Register command handlers
        application.add_handler(CommandHandler("start", bot.start_bot))
        application.add_handler(CommandHandler("stop", bot.stop_bot))
        application.add_handler(CommandHandler("update", bot.update_now))
        application.add_handler(CommandHandler("help", bot.show_help))
        
        logger.info("Bot started successfully")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Bot startup failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()
