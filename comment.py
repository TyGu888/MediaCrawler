import asyncio
import json
import os
import random
import time
from typing import Dict, List, Optional, Set
import traceback

import httpx
from playwright.async_api import BrowserContext, Page

from tools import utils


class WeiboCommentScraper:
    """Enhanced Weibo comment scraper with robust error handling and rate limiting protection"""
    
    def __init__(self, multi_account_scraper):
        self.scraper = multi_account_scraper
        self.comment_cache = {}  # Cache to avoid re-scraping the same comments
        self.failed_post_ids = set()  # Track failed post IDs for retry
        self.success_post_ids = set()  # Track successfully scraped post IDs
        
        # Configure rate limiting and backoff
        self.min_delay = 3.0  # Minimum delay between requests in seconds
        self.max_delay = 12.0  # Maximum delay for exponential backoff
        self.jitter = 0.5  # Random jitter factor to add to delays
        
        # Create statistics for monitoring
        self.stats = {
            "total_posts_processed": 0,
            "successful_posts": 0,
            "failed_posts": 0,
            "total_comments_scraped": 0,
            "empty_comment_posts": 0,
            "retries": 0,
            "start_time": time.time(),
        }
        
        # Path for storing comment progress
        self.progress_file = "comment_scraping_progress.json"
        self.load_progress()
        
    def load_progress(self):
        """Load previously saved progress"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                    self.success_post_ids = set(progress.get("success_post_ids", []))
                    self.failed_post_ids = set(progress.get("failed_post_ids", []))
                    self.stats = progress.get("stats", self.stats)
                utils.logger.info(f"Loaded scraping progress: {len(self.success_post_ids)} successful posts, {len(self.failed_post_ids)} failed posts")
            except Exception as e:
                utils.logger.error(f"Error loading progress file: {e}")
    
    def save_progress(self):
        """Save current progress to file"""
        try:
            progress = {
                "success_post_ids": list(self.success_post_ids),
                "failed_post_ids": list(self.failed_post_ids),
                "stats": self.stats
            }
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            utils.logger.error(f"Error saving progress: {e}")
    
    async def scrape_comments_for_content_csv(self, content_csv_path, comment_batch_size=50, max_concurrent_batches=2):
        """Scrape comments for posts in a content CSV file that don't already have comments"""
        utils.logger.info(f"Starting to scrape comments for content in {content_csv_path}")
        
        # Extract post IDs from the content CSV
        post_ids = await self._extract_post_ids_from_csv(content_csv_path)
        utils.logger.info(f"Found {len(post_ids)} total posts in CSV")
        
        # Filter to get only posts that need comment scraping
        existing_comment_post_ids = await self._extract_existing_comment_post_ids()
        post_ids_to_scrape = list(set(post_ids) - set(existing_comment_post_ids) - self.success_post_ids)
        utils.logger.info(f"Filtering to {len(post_ids_to_scrape)} posts that need comment scraping")
        
        # Process them in batches with concurrency control
        return await self.scrape_comments_for_post_ids(
            post_ids_to_scrape, 
            batch_size=comment_batch_size,
            max_concurrent_batches=max_concurrent_batches
        )
    
    async def retry_failed_posts(self, max_retries=3, batch_size=30, max_concurrent_batches=2):
        """Retry scraping comments for previously failed posts"""
        if not self.failed_post_ids:
            utils.logger.info("No failed posts to retry")
            return []
            
        utils.logger.info(f"Retrying comment scraping for {len(self.failed_post_ids)} failed posts")
        post_ids_to_retry = list(self.failed_post_ids)
        self.failed_post_ids.clear()  # Clear so we don't retry the same posts again
        
        comments = []
        for retry in range(max_retries):
            if not post_ids_to_retry:
                break
                
            utils.logger.info(f"Retry attempt {retry+1}/{max_retries} for {len(post_ids_to_retry)} posts")
            
            # Use a longer delay for retries
            old_min_delay = self.min_delay
            old_max_delay = self.max_delay
            self.min_delay *= (retry + 1.5)  # Increase delay for each retry attempt
            self.max_delay *= (retry + 1.5)
            
            try:
                retry_comments = await self.scrape_comments_for_post_ids(
                    post_ids_to_retry,
                    batch_size=batch_size,
                    max_concurrent_batches=max_concurrent_batches
                )
                comments.extend(retry_comments)
                
                # Get the posts that still failed
                post_ids_to_retry = list(self.failed_post_ids)
                self.failed_post_ids.clear()
            finally:
                # Restore original delays
                self.min_delay = old_min_delay
                self.max_delay = old_max_delay
                
            # No need to continue if all retries were successful
            if not post_ids_to_retry:
                utils.logger.info("All retries successful")
                break
                
            # Wait longer between retry attempts
            await asyncio.sleep(random.uniform(5, 15))
        
        # Add any remaining failed posts back to the failed set
        self.failed_post_ids.update(post_ids_to_retry)
        self.save_progress()
        
        return comments
    
    async def scrape_comments_for_post_ids(self, post_ids, batch_size=50, max_concurrent_batches=2):
        """Scrape comments for a list of post IDs with improved error handling and rate limiting"""
        if not post_ids:
            utils.logger.info("No posts to scrape comments for")
            return []
            
        utils.logger.info(f"Scraping comments for {len(post_ids)} posts in batches of {batch_size}")
        all_comments = []
        batches = [post_ids[i:i+batch_size] for i in range(0, len(post_ids), batch_size)]
        
        # Create a semaphore to limit batch concurrency
        batch_semaphore = asyncio.Semaphore(max_concurrent_batches)
        
        # Display progress bar stats
        total_batches = len(batches)
        completed_batches = 0
        
        async def process_batch(batch_index, post_id_batch):
            nonlocal completed_batches
            
            async with batch_semaphore:
                utils.logger.info(f"Processing batch {batch_index+1}/{total_batches} with {len(post_id_batch)} posts")
                batch_comments = []
                
                # Process each post with individual error handling
                for post_id in post_id_batch:
                    try:
                        # Skip already processed posts
                        if post_id in self.success_post_ids:
                            continue
                            
                        # Use adaptive delay to avoid rate limiting
                        delay = self._calculate_delay()
                        await asyncio.sleep(delay)
                        
                        # Rotate to a different account for each post
                        account = await self.scraper.rotate_account()
                        account_index = self.scraper.accounts.index(account) + 1
                        
                        utils.logger.info(f"Account {account_index} getting comments for post: {post_id}")
                        
                        # Rotate proxy occasionally to avoid detection
                        if self.scraper.ip_proxy_pool and random.random() < 0.3:
                            await self.scraper.rotate_proxy()
                        
                        comments = await self._fetch_comments_with_retry(account, post_id)
                        
                        # Update statistics
                        self.stats["total_posts_processed"] += 1
                        
                        if comments:
                            batch_comments.extend(comments)
                            self.stats["total_comments_scraped"] += len(comments)
                            self.stats["successful_posts"] += 1
                            self.success_post_ids.add(post_id)
                        else:
                            self.stats["empty_comment_posts"] += 1
                            self.success_post_ids.add(post_id)  # Still mark as successful, just no comments
                            
                    except Exception as e:
                        error_message = str(e)
                        self.stats["failed_posts"] += 1
                        self.failed_post_ids.add(post_id)
                        # More detailed error logging
                        utils.logger.error(f"Error getting comments for post {post_id}: {error_message}")
                        if "Expecting value" in error_message:
                            utils.logger.warning(f"Received malformed JSON for post {post_id} - likely rate limited")
                        
                        # Optional: print traceback for debugging
                        trace = traceback.format_exc()
                        utils.logger.debug(f"Traceback: {trace}")
                
                completed_batches += 1
                self._print_progress(completed_batches, total_batches)
                
                # Save progress periodically
                if completed_batches % 5 == 0 or completed_batches == total_batches:
                    self.save_progress()
                
                return batch_comments
        
        # Create tasks for all batches
        batch_tasks = [process_batch(i, batch) for i, batch in enumerate(batches)]
        
        # Execute batches with concurrency control
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        
        # Process batch results
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                utils.logger.error(f"Error processing batch {i+1}: {result}")
            else:
                all_comments.extend(result)
        
        utils.logger.info(f"Completed comment scraping. Total comments collected: {len(all_comments)}")
        utils.logger.info(f"Stats: {self._format_stats()}")
        
        return all_comments
    
    async def _fetch_comments_with_retry(self, account, post_id, max_retries=3, max_comments=100):
        """Fetch comments for a post with retries and improved error handling"""
        for retry in range(max_retries):
            try:
                # Try to get comments with exponential backoff for retries
                if retry > 0:
                    self.stats["retries"] += 1
                    backoff_delay = min(self.max_delay, self.min_delay * (2 ** retry))
                    jitter_delay = backoff_delay * (1 + random.uniform(-self.jitter, self.jitter))
                    utils.logger.info(f"Retry {retry+1}/{max_retries} for post {post_id} after {jitter_delay:.2f}s delay")
                    await asyncio.sleep(jitter_delay)
                
                # Different approach for each retry to maximize success chance
                if retry == 0:
                    # First try: normal approach
                    comments = await account.wb_client.get_note_all_comments(
                        note_id=post_id,
                        crawl_interval=random.uniform(1.5, 3.0),  # Slightly increased delay
                        callback=None,  # Don't store on first attempt
                        max_count=max_comments
                    )
                elif retry == 1:
                    # Second try: use a different max_id strategy
                    comments = await self._fetch_comments_alternative(account, post_id, max_comments)
                else:
                    # Last try: try individual page fetching with longer delays
                    comments = await self._fetch_comments_paged(account, post_id, max_comments)
                
                return comments
                
            except Exception as e:
                error_message = str(e)
                
                # Handle different error types differently
                if "Expecting value" in error_message:
                    # Empty JSON usually means we're being rate limited - use longer backoff
                    utils.logger.warning(f"Possible rate limiting on retry {retry+1} for post {post_id}")
                    if retry < max_retries - 1:
                        await asyncio.sleep(random.uniform(5, 10))  # Longer wait for rate limits
                        
                elif "Connection" in error_message or "Timeout" in error_message:
                    # Network issues - wait a bit
                    utils.logger.warning(f"Network issue on retry {retry+1} for post {post_id}: {e}")
                    if retry < max_retries - 1:
                        await asyncio.sleep(random.uniform(2, 5))
                        
                else:
                    # Other errors
                    utils.logger.error(f"Error on retry {retry+1} for post {post_id}: {e}")
                    if retry == max_retries - 1:
                        raise  # Re-raise on last retry
                        
                # Reset the client for network issues
                if retry == 1:
                    try:
                        # Try refreshing cookies/session
                        await account.wb_client.update_cookies(browser_context=account.browser_context)
                    except Exception as cookie_error:
                        utils.logger.error(f"Error updating cookies: {cookie_error}")
                
        raise Exception(f"Failed to get comments after {max_retries} retries for post {post_id}")
    
    async def _fetch_comments_alternative(self, account, post_id, max_comments):
        """Alternative method for fetching comments using a different approach"""
        comments = []
        is_end = False
        max_id = 0  # Start with 0 instead of -1
        max_id_type = 0
        
        # Try a slightly different API pattern
        while not is_end and len(comments) < max_comments:
            try:
                # Slightly different params
                comments_res = await account.wb_client.get_note_comments(
                    mid_id=post_id,
                    max_id=max_id,
                    max_id_type=max_id_type
                )
                
                max_id = comments_res.get("max_id", 0)
                max_id_type = comments_res.get("max_id_type", 0)
                comment_list = comments_res.get("data", [])
                
                is_end = max_id == 0 or not comment_list
                
                if len(comments) + len(comment_list) > max_comments:
                    comment_list = comment_list[:max_comments - len(comments)]
                
                comments.extend(comment_list)
                
                # Slower crawl interval for this alternative method
                await asyncio.sleep(random.uniform(2.0, 4.0))
                
            except Exception as e:
                utils.logger.error(f"Error in alternative comment fetch for post {post_id}: {e}")
                break
                
        return comments
    
    async def _fetch_comments_paged(self, account, post_id, max_comments):
        """Fetch comments page by page with longer delays"""
        comments = []
        page = 1
        page_size = 20  # Typical Weibo page size
        max_pages = (max_comments + page_size - 1) // page_size
        
        while page <= max_pages and len(comments) < max_comments:
            try:
                # Directly construct the referer URL and headers for this request
                referer_url = f"https://m.weibo.cn/detail/{post_id}?page={page}"
                headers = dict(account.wb_client.headers)
                headers["Referer"] = referer_url
                
                # Use the direct API endpoint
                uri = "/comments/hotflow"
                params = {
                    "id": post_id,
                    "mid": post_id,
                    "max_id_type": 0,
                    "page": page,
                }
                
                response = await account.wb_client.get(uri, params, headers=headers)
                
                comment_list = response.get("data", [])
                if not comment_list:
                    break
                
                comments.extend(comment_list[:max_comments - len(comments)])
                page += 1
                
                # Even longer delay for this method
                await asyncio.sleep(random.uniform(3.0, 5.0))
                
            except Exception as e:
                utils.logger.error(f"Error in paged comment fetch for post {post_id}, page {page}: {e}")
                break
                
        return comments
    
    async def _extract_post_ids_from_csv(self, csv_path):
        """Extract post IDs from a content CSV file"""
        import csv
        
        post_ids = []
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Assuming the post ID column is named "note_id"
                    if 'note_id' in row and row['note_id']:
                        post_ids.append(row['note_id'])
        except Exception as e:
            utils.logger.error(f"Error reading content CSV: {e}")
            
        return post_ids
    
    async def _extract_existing_comment_post_ids(self, csv_path='data/weibo/search_comments.csv'):
        """Extract post IDs that already have comments"""
        import csv
        
        post_ids = set()
        try:
            if not os.path.exists(csv_path):
                return post_ids
                
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Assuming the post ID column in comments CSV is named "note_id"
                    if 'note_id' in row and row['note_id']:
                        post_ids.add(row['note_id'])
        except Exception as e:
            utils.logger.error(f"Error reading comments CSV: {e}")
            
        return post_ids
    
    def _calculate_delay(self):
        """Calculate an adaptive delay to avoid rate limiting"""
        # Base delay with jitter
        delay = random.uniform(self.min_delay, self.min_delay * 1.5)
        
        # Add jitter
        jittered_delay = delay * (1 + random.uniform(-self.jitter, self.jitter))
        
        return jittered_delay
    
    def _print_progress(self, completed, total):
        """Print a simple progress bar"""
        percent = (completed / total) * 100
        elapsed = time.time() - self.stats["start_time"]
        
        # Calculate estimated time remaining
        if completed > 0:
            eta = (elapsed / completed) * (total - completed)
            eta_str = f"ETA: {self._format_time(eta)}"
        else:
            eta_str = "ETA: calculating..."
            
        utils.logger.info(f"Progress: {completed}/{total} batches ({percent:.1f}%) - {eta_str}")
        utils.logger.info(f"Stats: Success: {self.stats['successful_posts']}, Failed: {len(self.failed_post_ids)}, Comments: {self.stats['total_comments_scraped']}")
    
    def _format_time(self, seconds):
        """Format seconds into a human-readable string"""
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def _format_stats(self):
        """Format stats into a readable string"""
        elapsed = time.time() - self.stats["start_time"]
        return (
            f"Total Posts: {self.stats['total_posts_processed']}, "
            f"Successful: {self.stats['successful_posts']}, "
            f"Failed: {self.stats['failed_posts']}, "
            f"Empty: {self.stats['empty_comment_posts']}, "
            f"Comments: {self.stats['total_comments_scraped']}, "
            f"Retries: {self.stats['retries']}, "
            f"Time: {self._format_time(elapsed)}"
        )


async def scrape_comments_for_existing_content():
    """Function to scrape comments for already scraped content"""
    from multiaccountweiboscraper import MultiAccountWeiboScraper
    
    # Initialize the main scraper
    scraper = MultiAccountWeiboScraper()
    try:
        # Initialize with proxy and headless mode
        await scraper.initialize(
            headless=True,  # Set to False to see browser windows
            enable_proxy=True,
            proxy_pool_size=10  # Using 10 proxies
        )
        
        # Check if we have any logged-in accounts
        active_accounts = [acc for acc in scraper.accounts if acc.is_logged_in]
        if not active_accounts:
            utils.logger.error("No accounts successfully logged in. Cannot proceed.")
            return
        
        utils.logger.info(f"Successfully logged in {len(active_accounts)} accounts out of {len(scraper.accounts)}")
        
        # Initialize the enhanced comment scraper
        comment_scraper = WeiboCommentScraper(scraper)
        
        # Scrape comments for existing content
        content_csv_path = "data/weibo/search_contents.csv"
        
        utils.logger.info("Starting comment scraping for existing content...")
        comments = await comment_scraper.scrape_comments_for_content_csv(
            content_csv_path=content_csv_path,
            comment_batch_size=30,  # Process 30 posts per batch
            max_concurrent_batches=3  # Run 3 batches in parallel
        )
        
        utils.logger.info(f"Initial comment scraping complete. Total comments: {len(comments)}")
        
        # Retry failed posts with longer delays
        utils.logger.info(f"Retrying {len(comment_scraper.failed_post_ids)} failed posts...")
        retry_comments = await comment_scraper.retry_failed_posts(
            max_retries=3,
            batch_size=20,  # Smaller batch size for retries
            max_concurrent_batches=2  # Less concurrency for retries
        )
        
        utils.logger.info(f"Retry comment scraping complete. Additional comments: {len(retry_comments)}")
        utils.logger.info(f"Total successful posts: {len(comment_scraper.success_post_ids)}")
        utils.logger.info(f"Total failed posts: {len(comment_scraper.failed_post_ids)}")
        
        # Save final progress
        comment_scraper.save_progress()
        
    except Exception as e:
        utils.logger.error(f"Error in comment scraping: {e}")
        import traceback
        utils.logger.error(traceback.format_exc())
    finally:
        # Close all browsers
        await scraper.close()
        utils.logger.info("Comment scraping finished")


if __name__ == "__main__":
    import asyncio
    asyncio.run(scrape_comments_for_existing_content())