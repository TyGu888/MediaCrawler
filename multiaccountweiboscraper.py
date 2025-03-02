import asyncio
import csv
import os
import sys
import random
import json
import time
import traceback
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright, BrowserContext, BrowserType, Page
import httpx
from media_platform.weibo.client import WeiboClient
from media_platform.weibo.login import WeiboLogin
from media_platform.weibo.help import filter_search_result_card
from media_platform.weibo.field import SearchType
from store import weibo as weibo_store
from tools import utils
from var import crawler_type_var, source_keyword_var
from proxy.types import IpInfoModel, ProviderNameEnum
from proxy.proxy_ip_pool import create_ip_pool

# Set your KuaiDaiLi proxy credentials here
# These will be used by the proxy module
os.environ["kdl_secret_id"] = "or7tj6mpxdi46dj6kjro"
os.environ["kdl_signature"] = "b5rabce1uvphqgpo189cctqbl0bfrhl5" 
os.environ["kdl_user_name"] = "d1414933521"
os.environ["kdl_user_pwd"] = "drur7qnt"

# Set the proxy provider to KuaiDaiLi
os.environ["IP_PROXY_PROVIDER_NAME"] = ProviderNameEnum.KUAI_DAILI_PROVIDER.value


class WeiboAccount:
    def __init__(self, username="", password="", cookie_str="", login_type="qrcode"):
        self.username = username
        self.password = password
        self.cookie_str = cookie_str
        self.login_type = login_type
        self.browser_context = None
        self.context_page = None
        self.wb_client = None
        self.is_logged_in = False
        self.last_used_time = 0
        self.request_count = 0  # Track number of requests made
        self.error_count = 0    # Track number of errors encountered
        self.cooldown_until = 0  # Timestamp when cooldown ends
        
    def to_dict(self):
        return {
            "username": self.username,
            "cookie_str": self.cookie_str,
            "login_type": self.login_type,
            "is_logged_in": self.is_logged_in
        }
    
    def is_in_cooldown(self):
        """Check if account is in cooldown"""
        return time.time() < self.cooldown_until
    
    def set_cooldown(self, minutes=15):
        """Set account in cooldown for specified minutes"""
        self.cooldown_until = time.time() + (minutes * 60)
        utils.logger.info(f"Account set to cooldown until {datetime.fromtimestamp(self.cooldown_until).strftime('%H:%M:%S')}")


class CommentScrapingStats:
    """Track comment scraping statistics"""
    def __init__(self):
        self.total_posts_processed = 0
        self.successful_posts = 0
        self.failed_posts = 0
        self.total_comments_scraped = 0
        self.empty_posts = 0
        self.rate_limited_posts = 0
        self.start_time = time.time()
        
    def add_success(self, comment_count):
        self.successful_posts += 1
        self.total_posts_processed += 1
        self.total_comments_scraped += comment_count
        
    def add_failure(self, error_type=None):
        self.failed_posts += 1
        self.total_posts_processed += 1
        if error_type == "empty":
            self.empty_posts += 1
        elif error_type == "rate_limited":
            self.rate_limited_posts += 1
            
    def get_summary(self):
        elapsed = time.time() - self.start_time
        return {
            "total_posts": self.total_posts_processed,
            "successful_posts": self.successful_posts,
            "failed_posts": self.failed_posts,
            "success_rate": f"{(self.successful_posts / max(1, self.total_posts_processed)) * 100:.2f}%",
            "total_comments": self.total_comments_scraped,
            "avg_comments_per_post": f"{self.total_comments_scraped / max(1, self.successful_posts):.2f}",
            "empty_posts": self.empty_posts,
            "rate_limited_posts": self.rate_limited_posts,
            "elapsed_time": f"{elapsed / 60:.2f} minutes",
            "comments_per_minute": f"{self.total_comments_scraped / max(1, elapsed / 60):.2f}"
        }
    
    def print_summary(self):
        summary = self.get_summary()
        utils.logger.info("===== Comment Scraping Summary =====")
        for key, value in summary.items():
            utils.logger.info(f"{key}: {value}")
        utils.logger.info("====================================")


class EnhancedWeiboScraper:
    def __init__(self):
        self.mobile_index_url = "https://m.weibo.cn"
        self.user_agent = utils.get_mobile_user_agent()
        self.accounts = []
        self.current_account_index = 0
        self.ip_proxy_pool = None
        self.playwright_proxy = None
        self.httpx_proxy = None
        self.account_file = "weibo_accounts.json"
        self.proxy_file = "weibo_proxies.json"
        self.stats = CommentScrapingStats()
        self.processed_comments = set()  # Track comment IDs we've already processed
        self.active_proxies = []  # List of currently active proxies
        self.account_lock = asyncio.Lock()  # Lock for thread-safe account rotation
        
        # Configure retry settings
        self.max_retries = 3  # Maximum number of retries for any operation
        self.retry_delay = 2  # Base delay in seconds between retries
        self.jitter = 1.5    # Maximum random jitter added to retry delay
        
        # Configure rate limiting
        self.min_request_interval = 1.5  # Minimum seconds between requests
        self.max_request_interval = 4.0  # Maximum seconds between requests
        self.request_count_threshold = 100  # Number of requests before longer pause
        self.long_pause_min = 30  # Minimum seconds for long pause
        self.long_pause_max = 60  # Maximum seconds for long pause
        
        # Comment scraping settings
        self.error_threshold = 5  # Number of consecutive errors before cooldown
        self.comment_batch_size = 20  # Process comments in batches for large posts
        
        # Previously processed content and comments tracking
        self.scraped_content_ids = set()
        self.scraped_comment_ids = set()
        self._load_scraped_ids()

    def _load_scraped_ids(self):
        """Load already scraped content and comment IDs from files"""
        # Load content IDs
        try:
            if os.path.exists("data/weibo/search_contents.csv"):
                df = pd.read_csv("data/weibo/search_contents.csv", encoding="utf-8-sig")
                if 'note_id' in df.columns:
                    self.scraped_content_ids = set(df['note_id'].astype(str).tolist())
                    utils.logger.info(f"Loaded {len(self.scraped_content_ids)} previously scraped content IDs")
        except Exception as e:
            utils.logger.error(f"Error loading scraped content IDs: {e}")
            
        # Load comment IDs
        try:
            if os.path.exists("data/weibo/search_comments.csv"):
                df = pd.read_csv("data/weibo/search_comments.csv", encoding="utf-8-sig")
                if 'comment_id' in df.columns:
                    self.scraped_comment_ids = set(df['comment_id'].astype(str).tolist())
                    utils.logger.info(f"Loaded {len(self.scraped_comment_ids)} previously scraped comment IDs")
        except Exception as e:
            utils.logger.error(f"Error loading scraped comment IDs: {e}")

    def load_accounts_from_file(self):
        """Load saved accounts from file"""
        if os.path.exists(self.account_file):
            try:
                with open(self.account_file, 'r', encoding='utf-8') as f:
                    accounts_data = json.load(f)
                    for acc_data in accounts_data:
                        account = WeiboAccount(
                            username=acc_data.get("username", ""),
                            cookie_str=acc_data.get("cookie_str", ""),
                            login_type=acc_data.get("login_type", "qrcode")
                        )
                        self.accounts.append(account)
                utils.logger.info(f"Loaded {len(self.accounts)} accounts from file")
            except Exception as e:
                utils.logger.error(f"Error loading accounts: {e}")

    def save_accounts_to_file(self):
        """Save accounts to file"""
        try:
            accounts_data = [acc.to_dict() for acc in self.accounts]
            with open(self.account_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_data, f, ensure_ascii=False, indent=2)
            utils.logger.info(f"Saved {len(self.accounts)} accounts to file")
        except Exception as e:
            utils.logger.error(f"Error saving accounts: {e}")
            
    def save_proxies_to_file(self):
        """Save working proxies to file"""
        try:
            if not self.active_proxies:
                return
                
            with open(self.proxy_file, 'w', encoding='utf-8') as f:
                json.dump(self.active_proxies, f, ensure_ascii=False, indent=2)
            utils.logger.info(f"Saved {len(self.active_proxies)} proxies to file")
        except Exception as e:
            utils.logger.error(f"Error saving proxies: {e}")

    async def initialize(self, headless=True, enable_proxy=False, proxy_pool_size=3):
        """Initialize the enhanced Weibo scraper"""
        # Load saved accounts
        self.load_accounts_from_file()
        
        # If no accounts loaded, create empty ones
        if not self.accounts:
            # Create three empty accounts to be logged in
            for i in range(3):
                self.accounts.append(WeiboAccount(login_type="qrcode"))
        
        # Initialize proxy pool if enabled
        if enable_proxy:
            try:
                utils.logger.info(f"Initializing proxy pool with {proxy_pool_size} proxies")
                self.ip_proxy_pool = await create_ip_pool(proxy_pool_size, enable_validate_ip=True)
                
                # Try to get some valid proxies for our initial pool
                for _ in range(min(5, proxy_pool_size)):
                    try:
                        proxy_info = await self.ip_proxy_pool.get_proxy()
                        playwright_proxy, httpx_proxy = self.format_proxy_info(proxy_info)
                        
                        # Test the proxy
                        async with httpx.AsyncClient(proxies=httpx_proxy, timeout=10) as client:
                            response = await client.get("https://www.baidu.com")
                            if response.status_code == 200:
                                utils.logger.info(f"Proxy {proxy_info.ip}:{proxy_info.port} is working")
                                self.active_proxies.append({
                                    "ip": proxy_info.ip,
                                    "port": proxy_info.port,
                                    "user": proxy_info.user,
                                    "password": proxy_info.password,
                                    "protocol": proxy_info.protocol
                                })
                    except Exception as e:
                        utils.logger.error(f"Error testing proxy: {e}")
                
                self.save_proxies_to_file()
                
            except Exception as e:
                utils.logger.error(f"Error initializing proxy pool: {e}")
                utils.logger.warning("Continuing without proxy")
                enable_proxy = False
        
        # Login all accounts sequentially
        async with async_playwright() as playwright:
            chromium = playwright.chromium
            
            for i, account in enumerate(self.accounts):
                utils.logger.info(f"Initializing account {i+1}/{len(self.accounts)}")
                
                # Rotate proxy between accounts if proxy is enabled
                browser_proxy = None
                http_proxy = None
                if enable_proxy and self.ip_proxy_pool:
                    try:
                        proxy_info = await self.ip_proxy_pool.get_proxy()
                        browser_proxy, http_proxy = self.format_proxy_info(proxy_info)
                        utils.logger.info(f"Using proxy for account {i+1}: {proxy_info.ip}:{proxy_info.port}")
                    except Exception as e:
                        utils.logger.error(f"Error getting proxy for account {i+1}: {e}")
                        utils.logger.warning(f"Account {i+1} will not use a proxy")
                
                try:
                    # Launch browser for this account
                    user_data_dir = os.path.join(os.getcwd(), "browser_data", f"weibo_user_data_{i}")
                    account.browser_context = await chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        accept_downloads=True,
                        headless=headless,
                        proxy=browser_proxy,
                        viewport={"width": 1920, "height": 1080},
                        user_agent=self.user_agent
                    )
                    
                    # Add stealth.js to avoid detection
                    await account.browser_context.add_init_script(path="libs/stealth.min.js")
                    
                    account.context_page = await account.browser_context.new_page()
                    
                    # Try to navigate to Weibo with a timeout and fallback
                    try:
                        await account.context_page.goto(self.mobile_index_url, timeout=30000)
                    except Exception as e:
                        utils.logger.error(f"Error navigating to Weibo for account {i+1}: {e}")
                        if browser_proxy:
                            utils.logger.warning(f"Proxy might be blocked. Retrying without proxy for account {i+1}")
                            # Close the current context and try again without proxy
                            await account.browser_context.close()
                            account.browser_context = await chromium.launch_persistent_context(
                                user_data_dir=user_data_dir,
                                accept_downloads=True,
                                headless=headless,
                                # No proxy this time
                                viewport={"width": 1920, "height": 1080},
                                user_agent=self.user_agent
                            )
                            await account.browser_context.add_init_script(path="libs/stealth.min.js")
                            account.context_page = await account.browser_context.new_page()
                            await account.context_page.goto(self.mobile_index_url, timeout=30000)
                    
                    # Create Weibo client for this account
                    cookie_str, cookie_dict = utils.convert_cookies(await account.browser_context.cookies())
                    account.wb_client = WeiboClient(
                        proxies=http_proxy if browser_proxy else None,
                        headers={
                            "User-Agent": self.user_agent,
                            "Cookie": cookie_str,
                            "Origin": "https://m.weibo.cn",
                            "Referer": "https://m.weibo.cn",
                            "Content-Type": "application/json;charset=UTF-8"
                        },
                        playwright_page=account.context_page,
                        cookie_dict=cookie_dict,
                    )
                    
                    # Check if already logged in
                    is_logged_in = False
                    try:
                        is_logged_in = await account.wb_client.pong()
                    except Exception as e:
                        utils.logger.error(f"Error checking login status for account {i+1}: {e}")
                    
                    if not is_logged_in:
                        # Need to login
                        utils.logger.info(f"Account {i+1} not logged in, starting login process")
                        try:
                            login_obj = WeiboLogin(
                                login_type=account.login_type,
                                login_phone=account.username,
                                browser_context=account.browser_context,
                                context_page=account.context_page,
                                cookie_str=account.cookie_str
                            )
                            await login_obj.begin()
                            
                            # Redirect to mobile site and update cookies
                            await account.context_page.goto(self.mobile_index_url)
                            await asyncio.sleep(2)
                            await account.wb_client.update_cookies(browser_context=account.browser_context)
                            
                            # Update the cookie string in the account
                            cookie_str, _ = utils.convert_cookies(await account.browser_context.cookies())
                            account.cookie_str = cookie_str
                        except Exception as e:
                            utils.logger.error(f"Error logging in account {i+1}: {e}")
                    
                    # Check if login was successful
                    try:
                        account.is_logged_in = await account.wb_client.pong()
                        utils.logger.info(f"Account {i+1} login status: {'Success' if account.is_logged_in else 'Failed'}")
                        
                        # If we've successfully logged in, save the accounts
                        if account.is_logged_in:
                            self.save_accounts_to_file()
                    except Exception as e:
                        utils.logger.error(f"Error checking final login status for account {i+1}: {e}")
                        account.is_logged_in = False
                except Exception as e:
                    utils.logger.error(f"Error initializing account {i+1}: {e}")
                    # If the account's browser context exists, close it
                    if hasattr(account, 'browser_context') and account.browser_context:
                        await account.browser_context.close()
                    account.is_logged_in = False

    @staticmethod
    def format_proxy_info(ip_proxy_info: IpInfoModel) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Format proxy info for playwright and httpx"""
        playwright_proxy = {
            "server": f"{ip_proxy_info.protocol}{ip_proxy_info.ip}:{ip_proxy_info.port}",
            "username": ip_proxy_info.user,
            "password": ip_proxy_info.password,
        }
        httpx_proxy = {
            f"{ip_proxy_info.protocol}": f"http://{ip_proxy_info.user}:{ip_proxy_info.password}@{ip_proxy_info.ip}:{ip_proxy_info.port}"
        }
        return playwright_proxy, httpx_proxy

    async def rotate_account(self):
        """Rotate to the next account in the pool with advanced selection logic"""
        async with self.account_lock:  # Ensure thread safety
            active_accounts = [acc for acc in self.accounts if acc.is_logged_in and not acc.is_in_cooldown()]
            
            if not active_accounts:
                # All accounts in cooldown or not logged in
                # Wait for the account with the shortest cooldown to become available
                cooldown_accounts = [acc for acc in self.accounts if acc.is_logged_in and acc.is_in_cooldown()]
                if cooldown_accounts:
                    cooldown_accounts.sort(key=lambda acc: acc.cooldown_until)
                    next_available = cooldown_accounts[0]
                    wait_time = max(0, next_available.cooldown_until - time.time())
                    utils.logger.info(f"All accounts in cooldown. Waiting {wait_time:.1f} seconds for an account to become available")
                    await asyncio.sleep(wait_time + 1)  # Wait until cooldown expires plus 1 second buffer
                    return await self.rotate_account()  # Try again after waiting
                else:
                    utils.logger.error("No active accounts available!")
                    raise Exception("No active accounts available for rotation")
            
            # Advanced account selection logic:
            # 1. Prefer accounts with fewer errors
            # 2. For accounts with similar error counts, prefer the least recently used
            # 3. For accounts used at similar times, prefer those with fewer requests
            active_accounts.sort(key=lambda acc: (acc.error_count, acc.last_used_time, acc.request_count))
            account = active_accounts[0]
            
            # Update account stats
            account.last_used_time = utils.get_current_timestamp()
            account.request_count += 1
            
            utils.logger.info(f"Rotated to account {self.accounts.index(account) + 1} (errors: {account.error_count}, requests: {account.request_count})")
            
            return account

    async def rotate_proxy(self, force_new=False):
        """Rotate to a new proxy from the pool with improved error handling"""
        if not self.ip_proxy_pool:
            return None, None
            
        utils.logger.info("Rotating proxy...")
        
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                proxy_info = await self.ip_proxy_pool.get_proxy()
                playwright_proxy, httpx_proxy = self.format_proxy_info(proxy_info)
                
                # Test the proxy
                async with httpx.AsyncClient(proxies=httpx_proxy, timeout=10) as client:
                    response = await client.get("https://www.baidu.com")
                    if response.status_code == 200:
                        utils.logger.info(f"Rotated proxy to {proxy_info.ip}:{proxy_info.port}")
                        
                        # Add to our list of active proxies
                        self.active_proxies.append({
                            "ip": proxy_info.ip,
                            "port": proxy_info.port,
                            "user": proxy_info.user,
                            "password": proxy_info.password,
                            "protocol": proxy_info.protocol
                        })
                        self.save_proxies_to_file()
                        
                        return playwright_proxy, httpx_proxy
            except Exception as e:
                utils.logger.error(f"Error testing proxy (attempt {attempt+1}/{max_attempts}): {e}")
                await asyncio.sleep(1)
        
        utils.logger.warning("Failed to get a working proxy after multiple attempts")
        return None, None

    async def sleep_with_jitter(self, base_time):
        """Sleep with random jitter to avoid detection patterns"""
        jitter = random.uniform(0, self.jitter)
        sleep_time = base_time + jitter
        await asyncio.sleep(sleep_time)
        return sleep_time

    async def update_account_proxy(self, account):
        """Update an account's client with a new proxy"""
        if not self.ip_proxy_pool:
            return
            
        _, httpx_proxy = await self.rotate_proxy()
        if httpx_proxy:
            account.wb_client.proxies = httpx_proxy
            utils.logger.info(f"Updated account {self.accounts.index(account) + 1} with a new proxy")

    async def scrape_comments_for_existing_content(self, csv_path=None, limit=None, concurrency=3, 
                                         min_comments=5, prioritize_popular=True, 
                                         comment_limit_per_post=100, exclude_already_scraped=True):
        """
        Scrape comments for existing content from CSV file
        
        Args:
            csv_path: Path to the CSV file containing content
            limit: Maximum number of posts to process
            concurrency: Number of concurrent comment-scraping tasks
            min_comments: Only prioritize posts with at least this many comments
            prioritize_popular: Prioritize posts with more interactions
            comment_limit_per_post: Maximum number of comments to scrape per post
            exclude_already_scraped: Skip posts that already have comments in the comments CSV
        """
        if not csv_path:
            csv_path = "data/weibo/search_contents.csv"
            
        comment_csv_path = "data/weibo/search_comments.csv"    
        
        if not os.path.exists(csv_path):
            utils.logger.error(f"Content CSV file not found: {csv_path}")
            return
            
        try:
            # Read content from CSV
            content_df = pd.read_csv(csv_path, encoding="utf-8-sig")
            if 'note_id' not in content_df.columns:
                utils.logger.error("CSV file does not contain 'note_id' column")
                return
                
            # Load IDs that already have comments
            already_has_comments = set()
            if exclude_already_scraped and os.path.exists(comment_csv_path):
                try:
                    comment_df = pd.read_csv(comment_csv_path, encoding="utf-8-sig")
                    if 'note_id' in comment_df.columns:
                        # Count comments per post
                        comment_counts = comment_df['note_id'].value_counts().to_dict()
                        
                        # Only exclude posts that have at least min_comments
                        already_has_comments = {post_id for post_id, count in comment_counts.items() 
                                               if count >= min_comments}
                        
                        utils.logger.info(f"Found {len(already_has_comments)} posts that already have sufficient comments")
                except Exception as e:
                    utils.logger.error(f"Error reading comment CSV: {e}")
            
            # Filter out posts that already have comments
            if exclude_already_scraped:
                content_df = content_df[~content_df['note_id'].astype(str).isin(already_has_comments)]
                utils.logger.info(f"After excluding posts with existing comments: {len(content_df)} posts remaining")
            
            # Prioritize posts with more interactions
            if prioritize_popular and 'comments_count' in content_df.columns and 'liked_count' in content_df.columns:
                # Convert interaction columns to numeric
                for col in ['comments_count', 'liked_count']:
                    content_df[col] = pd.to_numeric(content_df[col], errors='coerce').fillna(0)
                
                # Create an engagement score (comments have higher weight than likes)
                content_df['engagement_score'] = (content_df['comments_count'] * 2) + content_df['liked_count']
                
                # Sort by engagement score descending
                content_df = content_df.sort_values('engagement_score', ascending=False)
                utils.logger.info("Sorted posts by engagement score (prioritizing posts with more interactions)")
            
            # Get filtered and sorted content IDs
            content_ids = content_df['note_id'].astype(str).tolist()
            
            # If limit is specified, take only that many
            if limit and isinstance(limit, int):
                content_ids = content_ids[:limit]
                
            utils.logger.info(f"Found {len(content_ids)} content items to scrape comments for")
            
            if not content_ids:
                utils.logger.info("No posts to process after filtering")
                return
                
            # Scrape comments for each content ID
            await self.batch_get_comments(content_ids, max_comments=comment_limit_per_post, concurrency=concurrency)
            
            # Print final statistics
            self.stats.print_summary()
            
        except Exception as e:
            utils.logger.error(f"Error scraping comments for existing content: {e}")
            traceback.print_exc()

    async def batch_get_comments(self, post_ids, max_comments=100, concurrency=3, with_retry=True):
        """Enhanced batch comment scraping with better error handling and retry logic"""
        if not post_ids:
            return []
            
        utils.logger.info(f"Getting comments for {len(post_ids)} posts with concurrency {concurrency}")
        all_comments = []
        
        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)
        
        async def fetch_comments(post_id):
            async with semaphore:
                # Skip posts we've already processed
                if post_id in self.processed_comments:
                    utils.logger.info(f"Skipping post {post_id} - already processed")
                    return []
                    
                retries = 0
                backoff = self.retry_delay
                
                while retries <= (self.max_retries if with_retry else 0):
                    try:
                        # Rotate to a different account for each comment batch
                        account = await self.rotate_account()
                        
                        if retries > 0:
                            utils.logger.info(f"Retry {retries}/{self.max_retries} for post {post_id}")
                        
                        utils.logger.info(f"Account {self.accounts.index(account) + 1} getting comments for post: {post_id}")
                        
                        # Random chance to rotate proxy
                        if self.ip_proxy_pool and random.random() < 0.3:  # 30% chance to rotate
                            await self.update_account_proxy(account)
                            
                        # Add a small delay before the request to simulate human behavior
                        await self.sleep_with_jitter(random.uniform(self.min_request_interval, self.max_request_interval))
                        
                        # Periodically add a longer pause to avoid rate limiting patterns
                        if account.request_count % self.request_count_threshold == 0:
                            pause_time = random.uniform(self.long_pause_min, self.long_pause_max)
                            utils.logger.info(f"Adding longer pause ({pause_time:.1f}s) after {self.request_count_threshold} requests")
                            await asyncio.sleep(pause_time)
                        
                        # Get comments with progressive batching
                        all_batch_comments = []
                        
                        try:
                            # Get first batch of comments to see how many there are
                            first_batch = await account.wb_client.get_note_all_comments(
                                note_id=post_id,
                                crawl_interval=random.uniform(1.5, 3),
                                callback=weibo_store.batch_update_weibo_note_comments,
                                max_count=min(self.comment_batch_size, max_comments)
                            )
                            
                            all_batch_comments.extend(first_batch)
                            
                            # If we got fewer comments than our batch size or reached max, we're done
                            if len(first_batch) < self.comment_batch_size or len(first_batch) >= max_comments:
                                comments = first_batch
                            else:
                                # We need more batches - add pauses between batches
                                remaining_batches = (max_comments - len(first_batch)) // self.comment_batch_size + 1
                                utils.logger.info(f"Post {post_id} has more comments. Getting {remaining_batches} more batches")
                                
                                # Wait longer between batches
                                await asyncio.sleep(random.uniform(3, 5))
                                
                                # Need a fresh account for next batch
                                account = await self.rotate_account()
                                
                                # Get the remaining comments
                                second_batch = await account.wb_client.get_note_all_comments(
                                    note_id=post_id,
                                    crawl_interval=random.uniform(2, 4),
                                    callback=weibo_store.batch_update_weibo_note_comments,
                                    max_count=max_comments - len(first_batch)
                                )
                                
                                all_batch_comments.extend(second_batch)
                                comments = all_batch_comments
                            
                            # Mark this post as processed
                            self.processed_comments.add(post_id)
                            
                            # Update statistics
                            self.stats.add_success(len(comments))
                            utils.logger.info(f"Successfully scraped {len(comments)} comments for post {post_id}")
                            
                            # Reset error count on successful request
                            account.error_count = 0
                            
                            return comments
                            
                        except Exception as batch_error:
                            error_msg = str(batch_error)
                            utils.logger.error(f"Error in batch comment fetching for post {post_id}: {error_msg}")
                            
                            # Check for specific error types
                            if "Expecting value" in error_msg or error_msg == "":
                                # Empty response - could be no comments or rate limiting
                                if retries == self.max_retries:
                                    self.stats.add_failure("empty")
                                    utils.logger.warning(f"Post {post_id} may have no comments or be inaccessible")
                                raise Exception("Empty response, possibly no comments or rate limited")
                            elif "412" in error_msg or "403" in error_msg:
                                # Definite rate limiting
                                account.error_count += 1
                                account.set_cooldown(minutes=20)
                                self.stats.add_failure("rate_limited")
                                raise Exception("Rate limited (412 status code)")
                            else:
                                account.error_count += 1
                                if account.error_count >= self.error_threshold:
                                    utils.logger.warning(f"Account {self.accounts.index(account) + 1} reached error threshold, putting in cooldown")
                                    account.set_cooldown(minutes=15)
                                
                                # For other errors, just raise to retry
                                raise batch_error
                                
                    except Exception as e:
                        retries += 1
                        account.error_count += 1
                        
                        if retries <= self.max_retries and with_retry:
                            # Exponential backoff with jitter
                            sleep_time = backoff + random.uniform(0, backoff * 0.5)
                            utils.logger.info(f"Retrying in {sleep_time:.2f}s (retry {retries}/{self.max_retries})")
                            await asyncio.sleep(sleep_time)
                            backoff *= 2  # Exponential backoff
                        else:
                            # Failed after all retries
                            utils.logger.error(f"Failed to get comments for post {post_id} after {retries} retries")
                            self.stats.add_failure()
                            return []


class MultiAccountWeiboScraper:
    def __init__(self):
        self.mobile_index_url = "https://m.weibo.cn"
        self.user_agent = utils.get_mobile_user_agent()
        self.accounts = []
        self.current_account_index = 0
        self.ip_proxy_pool = None
        self.playwright_proxy = None
        self.httpx_proxy = None
        self.account_file = "weibo_accounts.json"

    def load_accounts_from_file(self):
        """Load saved accounts from file"""
        if os.path.exists(self.account_file):
            try:
                with open(self.account_file, 'r', encoding='utf-8') as f:
                    accounts_data = json.load(f)
                    for acc_data in accounts_data:
                        account = WeiboAccount(
                            username=acc_data.get("username", ""),
                            cookie_str=acc_data.get("cookie_str", ""),
                            login_type=acc_data.get("login_type", "qrcode")
                        )
                        self.accounts.append(account)
                utils.logger.info(f"Loaded {len(self.accounts)} accounts from file")
            except Exception as e:
                utils.logger.error(f"Error loading accounts: {e}")

    def save_accounts_to_file(self):
        """Save accounts to file"""
        try:
            accounts_data = [acc.to_dict() for acc in self.accounts]
            with open(self.account_file, 'w', encoding='utf-8') as f:
                json.dump(accounts_data, f, ensure_ascii=False, indent=2)
            utils.logger.info(f"Saved {len(self.accounts)} accounts to file")
        except Exception as e:
            utils.logger.error(f"Error saving accounts: {e}")

    async def initialize(self, headless=True, enable_proxy=False, proxy_pool_size=3):
        """Initialize the multi-account Weibo scraper"""
        # Load saved accounts
        self.load_accounts_from_file()
        
        # If no accounts loaded, create empty ones
        if not self.accounts:
            # Create three empty accounts to be logged in
            for i in range(3):
                self.accounts.append(WeiboAccount(login_type="qrcode"))
        
        # Initialize proxy pool if enabled
        if enable_proxy:
            try:
                utils.logger.info(f"Initializing KuaiDaiLi proxy pool with {proxy_pool_size} proxies")
                # This will use the KuaiDaiLi credentials we set as environment variables
                self.ip_proxy_pool = await create_ip_pool(proxy_pool_size, enable_validate_ip=True)
                
                # Try to get a valid proxy, with retries
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        proxy_info = await self.ip_proxy_pool.get_proxy()
                        self.playwright_proxy, self.httpx_proxy = self.format_proxy_info(proxy_info)
                        utils.logger.info(f"Obtained proxy: {proxy_info.ip}:{proxy_info.port}")
                        
                        # Test the proxy with a simple request to make sure it works
                        async with httpx.AsyncClient(proxies=self.httpx_proxy, timeout=10) as client:
                            response = await client.get("https://www.baidu.com")
                            if response.status_code == 200:
                                utils.logger.info(f"Proxy {proxy_info.ip}:{proxy_info.port} is working")
                                break
                    except Exception as e:
                        utils.logger.error(f"Error testing proxy: {e}")
                        if attempt == max_retries - 1:
                            utils.logger.warning("Failed to get working proxy after multiple attempts. Continuing without proxy.")
                            self.playwright_proxy, self.httpx_proxy = None, None
                            enable_proxy = False
            except Exception as e:
                utils.logger.error(f"Error initializing proxy pool: {e}")
                utils.logger.warning("Continuing without proxy")
                enable_proxy = False
        
        # Login all accounts sequentially
        async with async_playwright() as playwright:
            chromium = playwright.chromium
            
            for i, account in enumerate(self.accounts):
                utils.logger.info(f"Initializing account {i+1}/{len(self.accounts)}")
                
                # Rotate proxy between accounts if proxy is enabled
                browser_proxy = None
                if enable_proxy and self.ip_proxy_pool:
                    try:
                        proxy_info = await self.ip_proxy_pool.get_proxy()
                        browser_proxy, http_proxy = self.format_proxy_info(proxy_info)
                        utils.logger.info(f"Using proxy for account {i+1}: {proxy_info.ip}:{proxy_info.port}")
                    except Exception as e:
                        utils.logger.error(f"Error getting proxy for account {i+1}: {e}")
                        utils.logger.warning(f"Account {i+1} will not use a proxy")
                
                try:
                    # Launch browser for this account
                    user_data_dir = os.path.join(os.getcwd(), "browser_data", f"weibo_user_data_{i}")
                    account.browser_context = await chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        accept_downloads=True,
                        headless=headless,
                        proxy=browser_proxy,
                        viewport={"width": 1920, "height": 1080},
                        user_agent=self.user_agent
                    )
                    
                    # Add stealth.js to avoid detection
                    await account.browser_context.add_init_script(path="libs/stealth.min.js")
                    
                    account.context_page = await account.browser_context.new_page()
                    
                    # Try to navigate to Weibo with a timeout and fallback
                    try:
                        await account.context_page.goto(self.mobile_index_url, timeout=30000)
                    except Exception as e:
                        utils.logger.error(f"Error navigating to Weibo for account {i+1}: {e}")
                        if browser_proxy:
                            utils.logger.warning(f"Proxy might be blocked. Retrying without proxy for account {i+1}")
                            # Close the current context and try again without proxy
                            await account.browser_context.close()
                            account.browser_context = await chromium.launch_persistent_context(
                                user_data_dir=user_data_dir,
                                accept_downloads=True,
                                headless=headless,
                                # No proxy this time
                                viewport={"width": 1920, "height": 1080},
                                user_agent=self.user_agent
                            )
                            await account.browser_context.add_init_script(path="libs/stealth.min.js")
                            account.context_page = await account.browser_context.new_page()
                            await account.context_page.goto(self.mobile_index_url, timeout=30000)
                    
                    # Create Weibo client for this account
                    cookie_str, cookie_dict = utils.convert_cookies(await account.browser_context.cookies())
                    account.wb_client = WeiboClient(
                        proxies=http_proxy if browser_proxy else None,
                        headers={
                            "User-Agent": self.user_agent,
                            "Cookie": cookie_str,
                            "Origin": "https://m.weibo.cn",
                            "Referer": "https://m.weibo.cn",
                            "Content-Type": "application/json;charset=UTF-8"
                        },
                        playwright_page=account.context_page,
                        cookie_dict=cookie_dict,
                    )
                    
                    # Check if already logged in
                    is_logged_in = False
                    try:
                        is_logged_in = await account.wb_client.pong()
                    except Exception as e:
                        utils.logger.error(f"Error checking login status for account {i+1}: {e}")
                    
                    if not is_logged_in:
                        # Need to login
                        utils.logger.info(f"Account {i+1} not logged in, starting login process")
                        try:
                            login_obj = WeiboLogin(
                                login_type=account.login_type,
                                login_phone=account.username,
                                browser_context=account.browser_context,
                                context_page=account.context_page,
                                cookie_str=account.cookie_str
                            )
                            await login_obj.begin()
                            
                            # Redirect to mobile site and update cookies
                            await account.context_page.goto(self.mobile_index_url)
                            await asyncio.sleep(2)
                            await account.wb_client.update_cookies(browser_context=account.browser_context)
                            
                            # Update the cookie string in the account
                            cookie_str, _ = utils.convert_cookies(await account.browser_context.cookies())
                            account.cookie_str = cookie_str
                        except Exception as e:
                            utils.logger.error(f"Error logging in account {i+1}: {e}")
                    
                    # Check if login was successful
                    try:
                        account.is_logged_in = await account.wb_client.pong()
                        utils.logger.info(f"Account {i+1} login status: {'Success' if account.is_logged_in else 'Failed'}")
                        
                        # If we've successfully logged in, save the accounts
                        if account.is_logged_in:
                            self.save_accounts_to_file()
                    except Exception as e:
                        utils.logger.error(f"Error checking final login status for account {i+1}: {e}")
                        account.is_logged_in = False
                except Exception as e:
                    utils.logger.error(f"Error initializing account {i+1}: {e}")
                    # If the account's browser context exists, close it
                    if hasattr(account, 'browser_context') and account.browser_context:
                        await account.browser_context.close()
                    account.is_logged_in = False

    @staticmethod
    def format_proxy_info(ip_proxy_info: IpInfoModel) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Format proxy info for playwright and httpx"""
        playwright_proxy = {
            "server": f"{ip_proxy_info.protocol}{ip_proxy_info.ip}:{ip_proxy_info.port}",
            "username": ip_proxy_info.user,
            "password": ip_proxy_info.password,
        }
        httpx_proxy = {
            f"{ip_proxy_info.protocol}": f"http://{ip_proxy_info.user}:{ip_proxy_info.password}@{ip_proxy_info.ip}:{ip_proxy_info.port}"
        }
        return playwright_proxy, httpx_proxy

    async def rotate_account(self):
        """Rotate to the next account in the pool"""
        active_accounts = [acc for acc in self.accounts if acc.is_logged_in]
        
        if not active_accounts:
            utils.logger.error("No active accounts available!")
            raise Exception("No active accounts available for rotation")
        
        # Find the least recently used account
        active_accounts.sort(key=lambda acc: acc.last_used_time)
        account = active_accounts[0]
        
        # Update last used time
        account.last_used_time = utils.get_current_timestamp()
        utils.logger.info(f"Rotated to account {self.accounts.index(account) + 1}")
        
        return account

    async def rotate_proxy(self):
        """Rotate to a new proxy from the pool"""
        if not self.ip_proxy_pool:
            return
            
        utils.logger.info("Rotating KuaiDaiLi proxy...")
        proxy_info = await self.ip_proxy_pool.get_proxy()
        self.playwright_proxy, self.httpx_proxy = self.format_proxy_info(proxy_info)
        
        # Update the current account's client with the new proxy
        account = await self.rotate_account()
        account.wb_client.proxies = self.httpx_proxy
        utils.logger.info(f"Proxy rotated to {proxy_info.ip}:{proxy_info.port}")

    async def search_by_keyword(self, keyword, max_pages=5, concurrency=3):
        """Search Weibo for posts by keyword with multi-account and concurrency"""
        utils.logger.info(f"Searching Weibo for keyword: {keyword}")
        source_keyword_var.set(keyword)
        crawler_type_var.set("search")
        
        weibo_limit_count = 10  # Weibo limit page fixed value
        start_page = 1
        all_notes = []
        
        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)
        
        async def fetch_page(page_num):
            async with semaphore:
                try:
                    # Rotate to a different account for each page
                    account = await self.rotate_account()
                    
                    utils.logger.info(f"Account {self.accounts.index(account) + 1} searching keyword: {keyword}, page: {page_num}")
                    
                    # Rotate proxy to avoid rate limiting (optional)
                    if self.ip_proxy_pool and random.random() < 0.3:  # 30% chance to rotate
                        await self.rotate_proxy()
                        
                    search_res = await account.wb_client.get_note_by_keyword(
                        keyword=keyword,
                        page=page_num,
                        search_type=SearchType.DEFAULT
                    )
                    
                    note_id_list = []
                    note_list = filter_search_result_card(search_res.get("cards", []))
                    page_notes = []
                    
                    for note_item in note_list:
                        if note_item:
                            mblog = note_item.get("mblog")
                            if mblog:
                                note_id_list.append(mblog.get("id"))
                                await weibo_store.update_weibo_note(note_item)
                                page_notes.append(note_item)
                    
                    # Get comments for each post
                    await self.batch_get_comments(note_id_list, max_comments=100, concurrency=2)
                    
                    return page_notes
                except Exception as e:
                    utils.logger.error(f"Error fetching page {page_num}: {e}")
                    return []
                finally:
                    # Add delay to avoid rate limiting
                    await asyncio.sleep(random.uniform(1, 3))
        
        # Create tasks for all pages to fetch concurrently
        tasks = [fetch_page(page) for page in range(start_page, start_page + max_pages)]
        results = await asyncio.gather(*tasks)
        
        # Flatten the results
        for page_notes in results:
            all_notes.extend(page_notes)
        
        return all_notes

    async def get_specific_posts(self, post_ids, concurrency=3):
        """Get specific posts by ID with multi-account"""
        utils.logger.info(f"Getting specific posts: {post_ids}")
        crawler_type_var.set("detail")
        posts = []
        
        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)
        
        async def fetch_post(post_id):
            async with semaphore:
                try:
                    # Rotate to a different account for each post
                    account = await self.rotate_account()
                    
                    utils.logger.info(f"Account {self.accounts.index(account) + 1} getting post: {post_id}")
                    
                    # Rotate proxy to avoid rate limiting (optional)
                    if self.ip_proxy_pool and random.random() < 0.5:  # 30% chance to rotate
                        await self.rotate_proxy()
                        
                    note_item = await account.wb_client.get_note_info_by_id(post_id)
                    if note_item:
                        await weibo_store.update_weibo_note(note_item)
                        return note_item
                except Exception as e:
                    utils.logger.error(f"Error getting post {post_id}: {e}")
                    return None
                finally:
                    # Add delay to avoid rate limiting
                    await asyncio.sleep(random.uniform(1, 3))
        
        # Create tasks for all posts to fetch concurrently
        tasks = [fetch_post(post_id) for post_id in post_ids]
        results = await asyncio.gather(*tasks)
        
        # Filter out None results
        posts = [post for post in results if post]
        
        # Get comments for all posts
        await self.batch_get_comments(post_ids, max_comments=100, concurrency=1)
        
        return posts

    async def get_user_info(self, user_id):
        """Get user information and posts with multi-account"""
        utils.logger.info(f"Getting information for user: {user_id}")
        crawler_type_var.set("creator")
        
        try:
            # Rotate to a different account
            account = await self.rotate_account()
            
            utils.logger.info(f"Account {self.accounts.index(account) + 1} getting user info: {user_id}")
            
            creator_info = await account.wb_client.get_creator_info_by_id(creator_id=user_id)
            if creator_info:
                creator_user_info = creator_info.get("userInfo", {})
                utils.logger.info(f"Found creator info: {creator_user_info}")
                await weibo_store.save_creator(user_id, user_info=creator_user_info)
                
                # Get all posts by the user
                all_notes = await account.wb_client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=creator_info.get("lfid_container_id"),
                    crawl_interval=1,
                    callback=weibo_store.batch_update_weibo_notes
                )
                
                # Get comments for all posts with concurrency
                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes if
                           note_item.get("mblog", {}).get("id")]
                await self.batch_get_comments(note_ids, max_comments=100, concurrency=1)
                
                return creator_info, all_notes
        except Exception as e:
            utils.logger.error(f"Error getting user info {user_id}: {e}")
        
        return None, []

    async def batch_get_comments(self, post_ids, max_comments=100, concurrency=3):
        """Get comments for a batch of posts with multi-account"""
        if not post_ids:
            return []
            
        utils.logger.info(f"Getting comments for {len(post_ids)} posts with concurrency {concurrency}")
        all_comments = []
        
        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)
        
        async def fetch_comments(post_id):
            async with semaphore:
                try:
                    # Rotate to a different account for each comment batch
                    account = await self.rotate_account()
                    
                    utils.logger.info(f"Account {self.accounts.index(account) + 1} getting comments for post: {post_id}")
                    
                    # Rotate proxy to avoid rate limiting (optional)
                    if self.ip_proxy_pool and random.random() < 0.5:  # 30% chance to rotate
                        await self.rotate_proxy()
                        
                    comments = await account.wb_client.get_note_all_comments(
                        note_id=post_id,
                        crawl_interval=random.uniform(1, 3),
                        callback=weibo_store.batch_update_weibo_note_comments,
                        max_count=max_comments
                    )
                    return comments
                except Exception as e:
                    utils.logger.error(f"Error getting comments for post {post_id}: {e}")
                    return []
                finally:
                    # Add delay to avoid rate limiting
                    await asyncio.sleep(random.uniform(1, 3))
        
        # Create tasks for all posts to fetch comments concurrently
        tasks = [fetch_comments(post_id) for post_id in post_ids]
        results = await asyncio.gather(*tasks)
        
        # Flatten the results
        for comments in results:
            all_comments.extend(comments)
        
        return all_comments
    

    async def search_multiple_keywords(self, keywords, max_pages_per_keyword=20, page_concurrency=3, keyword_concurrency=2):
        """Search Weibo for multiple keywords with multi-level concurrency"""
        utils.logger.info(f"Searching Weibo for {len(keywords)} keywords with keyword concurrency {keyword_concurrency}")
        all_notes = []
        
        # Create a semaphore to limit keyword concurrency
        keyword_semaphore = asyncio.Semaphore(keyword_concurrency)
        
        async def process_keyword(keyword):
            async with keyword_semaphore:
                utils.logger.info(f"Starting search for keyword: {keyword}")
                source_keyword_var.set(keyword)
                
                keyword_notes = await self.search_by_keyword(
                    keyword=keyword, 
                    max_pages=max_pages_per_keyword,
                    concurrency=page_concurrency
                )
                
                utils.logger.info(f"Completed search for keyword '{keyword}'. Found {len(keyword_notes)} notes.")
                return keyword_notes
        
        # Create tasks for all keywords to process concurrently
        tasks = [process_keyword(keyword) for keyword in keywords]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                utils.logger.error(f"Error processing keyword '{keywords[i]}': {result}")
            else:
                utils.logger.info(f"Adding {len(result)} notes from keyword '{keywords[i]}'")
                all_notes.extend(result)
        
        utils.logger.info(f"Completed all keywords. Total notes collected: {len(all_notes)}")
        return all_notes

    async def close(self):
        """Close all browser contexts"""
        for i, account in enumerate(self.accounts):
            if account.browser_context:
                utils.logger.info(f"Closing browser for account {i+1}")
                await account.browser_context.close()




async def main():
    # Initialize logger
    utils.logger.info("Starting Multi-Account Weibo scraper with KuaiDaiLi proxies")
    
    # Create and initialize multi-account scraper
    scraper = EnhancedWeiboScraper()
    try:
        # Initialize with proxy and headless mode
        # Set headless=False to see the browser window for QR code scanning
        # Set enable_proxy=True to use proxy
        await scraper.initialize(
            headless=False, 
            enable_proxy=True,
            proxy_pool_size=12  # Using 5 proxies from KuaiDaiLi
        )
        
        # Check if we have any logged-in accounts
        active_accounts = [acc for acc in scraper.accounts if acc.is_logged_in]
        if not active_accounts:
            utils.logger.error("No accounts successfully logged in. Cannot proceed.")
            return
        
        utils.logger.info(f"Successfully logged in {len(active_accounts)} accounts out of {len(scraper.accounts)}")
        
        # Your tasks here...
        # ...
        keywords = [
            # 题材应用关键词
            '云南蛊术', '校园霸凌', '被诅咒', '少女复仇', '因果报应', '离奇死亡',
            
            # 角色关键词-娜缇
            '宿命', '宿主', '童年不幸', '被霸凌', '复仇少女', '对抗邪恶',
            
            # 角色关键词-蛊婆
            '守墓人', '传承者', '母爱', '牺牲', '禁忌手段', '被反噬',
            
            # 角色关键词-张月梅
            '法医', '相信科学', '丧女之痛', '追查者', '救赎自己',
            
            # 角色关键词-魏婷婷
            '霸凌者', '富家女', '弑父', '疯癫', '恃强凌弱', '美貌',
            
            # 角色关键词-魏明轩
            '暴发户', '迷信', '贪婪', '资本家', '宠女儿',
            
            # 情节关键词
            '母亲难产', '驱邪仪式', '遭遇霸凌', '视为祸害', '直播死亡',
            '法医追凶', '早年丧女', '玄学治病', '揭露秘密', '化敌为友',
            '祖坟被毁', '母亲牺牲', '活人献祭', '主角黑化', '信念崩塌',
            '封印诅咒', '被爱唤醒', '牺牲自我', '开放结局',
            
            # 主题关键词
            '反对校园霸凌', '相信因果报应', '人性之恶的存在', '相信蛊术存在', '相信佛法力量'
            ]
        all_posts = []
        all_posts = await scraper.search_multiple_keywords(
            keywords=keywords,
            max_pages_per_keyword=20,
            page_concurrency=3,
            keyword_concurrency=1
            )
        utils.logger.info(f"Total posts found across all keywords: {len(all_posts)}")
        
        scraper.scrape_comments_for_existing_content(csv_path="data/weibo/search_contents.csv", limit=100, concurrency=3, min_comments=5, prioritize_popular=True, comment_limit_per_post=100, exclude_already_scraped=True)
        # for keyword in keywords:
        #     posts = await scraper.search_by_keyword(keyword, max_pages=20, concurrency=3)
        #     utils.logger.info(f"Found {len(posts)} posts for keyword '{keyword}'")
        #     all_posts.extend(posts)
        # utils.logger.info(f"Total posts found: {len(all_posts)}")
        
    except Exception as e:
        utils.logger.error(f"Error in main: {e}")
    finally:
        # Close all browsers
        if hasattr(scraper, 'accounts'):
            for i, account in enumerate(scraper.accounts):
                try:
                    if hasattr(account, 'browser_context') and account.browser_context:
                        utils.logger.info(f"Closing browser for account {i+1}")
                        await account.browser_context.close()
                except Exception as close_err:
                    utils.logger.error(f"Error closing browser for account {i+1}: {close_err}")
        
        utils.logger.info("Multi-Account Weibo scraper finished")



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit()
