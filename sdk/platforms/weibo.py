from typing import Dict, List, Any, Optional
import time
import random
import sys
import os
import re
from datetime import datetime

# Add project root to path to import existing weibo crawler code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    # Import existing weibo crawler code
    from media_platform.weibo import WeiboClient, WeiboLogin
    from media_platform.weibo.core import WeiboCrawler
except ImportError as e:
    print(f"Warning: Could not import Weibo modules: {e}")
    print("WeiboPlatformHandler will have limited functionality.")
    
    # Define mocks for testing/fallback
    class WeiboClient:
        def __init__(self, cookies=None):
            self.cookies = cookies
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
    
    class WeiboLogin:
        def __init__(self):
            pass
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
            
        def login(self, username, password):
            print(f"Mock login for {username}")
            return {"mock": "cookies"}
    
    class WeiboCrawler:
        def __init__(self, client):
            self.client = client
            
        def search_posts_by_keyword(self, keyword, max_count=100):
            return [{"id": f"mock_post_{i}", "content": f"Mock post for {keyword}"} for i in range(5)]
            
        def get_post_detail(self, post_id):
            return {"id": post_id, "content": f"Mock post detail for {post_id}"}
            
        def get_comments_by_id(self, post_id):
            return [{"id": f"comment_{i}", "content": f"Mock comment {i}"} for i in range(3)]
            
        def get_user_posts(self, user_id, max_count=50):
            return [{"id": f"user_post_{i}", "content": f"Mock user post {i}"} for i in range(5)]

from ..account_manager import Account
from ..common.models import User, Post, Comment, SearchResult
from ..common.utils import parse_datetime, clean_text

class WeiboPlatformHandler:
    """Handler for Weibo platform operations."""
    
    def __init__(self):
        """Initialize the Weibo platform handler."""
        self._clients = {}  # Cache for logged-in clients
    
    def _get_client(self, account: Optional[Account], proxy_config: Optional[Dict] = None) -> WeiboClient:
        """
        Get or create a client for the given account.
        
        Args:
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            Weibo client
        """
        if not account:
            # Create a client without login
            client = WeiboClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
            
        # Check if we have a cached client for this account
        client_key = f"{account.username}_{account.password}"
        if client_key in self._clients:
            client = self._clients[client_key]
            # Update proxy if needed
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
            
        # Create and login a new client
        login = WeiboLogin()
        if proxy_config:
            login.set_proxy(proxy_config.get('proxy'))
            
        try:
            cookies = login.login(account.username, account.password)
            client = WeiboClient(cookies)
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            self._clients[client_key] = client
            return client
        except Exception as e:
            print(f"Login error for account {account.username}: {e}")
            # Fallback to anonymous client
            client = WeiboClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
    
    def _convert_weibo_user(self, weibo_user: Dict[str, Any]) -> User:
        """
        Convert a Weibo user to the standardized User model.
        
        Args:
            weibo_user: Weibo user data
            
        Returns:
            Standardized User object
        """
        return User(
            id=str(weibo_user.get('id', '')),
            username=weibo_user.get('screen_name', ''),
            nickname=weibo_user.get('name', ''),
            avatar=weibo_user.get('avatar_hd', ''),
            followers_count=weibo_user.get('followers_count', 0),
            following_count=weibo_user.get('follow_count', 0),
            description=weibo_user.get('description', ''),
            platform='weibo'
        )
    
    def _convert_weibo_comment(self, weibo_comment: Dict[str, Any]) -> Comment:
        """
        Convert a Weibo comment to the standardized Comment model.
        
        Args:
            weibo_comment: Weibo comment data
            
        Returns:
            Standardized Comment object
        """
        user = None
        if 'user' in weibo_comment and weibo_comment['user']:
            user = self._convert_weibo_user(weibo_comment['user'])
            
        created_at = None
        if 'created_at' in weibo_comment:
            created_at = parse_datetime(weibo_comment.get('created_at', ''))
            
        # Process replies if available
        replies = []
        if 'comments' in weibo_comment and weibo_comment['comments']:
            for reply in weibo_comment['comments']:
                replies.append(self._convert_weibo_comment(reply))
        
        return Comment(
            id=str(weibo_comment.get('id', '')),
            content=clean_text(weibo_comment.get('text', '')),
            user=user,
            created_at=created_at,
            likes_count=weibo_comment.get('like_counts', 0),
            parent_id=str(weibo_comment.get('reply_id', '')) if weibo_comment.get('reply_id') else None,
            replies=replies,
            platform='weibo'
        )
    
    def _convert_weibo_post(self, weibo_post: Dict[str, Any]) -> Post:
        """
        Convert a Weibo post to the standardized Post model.
        
        Args:
            weibo_post: Weibo post data
            
        Returns:
            Standardized Post object
        """
        user = None
        if 'user' in weibo_post and weibo_post['user']:
            user = self._convert_weibo_user(weibo_post['user'])
            
        created_at = None
        if 'created_at' in weibo_post:
            created_at = parse_datetime(weibo_post.get('created_at', ''))
            
        # Extract media URLs
        media_urls = []
        if 'pic_ids' in weibo_post and weibo_post['pic_ids']:
            for pic_id in weibo_post['pic_ids']:
                if 'pic_infos' in weibo_post and pic_id in weibo_post['pic_infos']:
                    pic_info = weibo_post['pic_infos'][pic_id]
                    if 'original' in pic_info and 'url' in pic_info['original']:
                        media_urls.append(pic_info['original']['url'])
        
        # Process comments if available
        comments = []
        if 'comments' in weibo_post and weibo_post['comments']:
            for comment in weibo_post['comments']:
                comments.append(self._convert_weibo_comment(comment))
        
        return Post(
            id=str(weibo_post.get('id', '')),
            title='',  # Weibo doesn't have titles
            content=clean_text(weibo_post.get('text', '')),
            media_urls=media_urls,
            user=user,
            created_at=created_at,
            updated_at=None,
            likes_count=weibo_post.get('attitudes_count', 0),
            comments_count=weibo_post.get('comments_count', 0),
            shares_count=weibo_post.get('reposts_count', 0),
            views_count=0,  # Weibo doesn't expose view counts
            url=f"https://weibo.com/{weibo_post.get('user', {}).get('id', '')}/{weibo_post.get('id', '')}",
            comments=comments,
            platform='weibo'
        )
    
    def search(self, keywords: List[str], max_results: int = 100, 
              account: Optional[Account] = None, 
              proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Search posts by keywords.
        
        Args:
            keywords: List of keywords to search
            max_results: Maximum results to return per keyword
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of search results
        """
        client = self._get_client(account, proxy_config)
        crawler = WeiboCrawler(client)
        
        all_results = []
        for keyword in keywords:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping keyword: {keyword}")
                    continue
                    
                weibo_posts = crawler.search_posts_by_keyword(keyword, max_count=max_results)
                
                if weibo_posts:
                    # Convert to our standardized model
                    posts = [self._convert_weibo_post(post) for post in weibo_posts]
                    
                    # Create a search result
                    search_result = SearchResult(
                        keyword=keyword,
                        posts=posts,
                        total_count=len(posts),
                        platform='weibo'
                    )
                    
                    all_results.append(search_result.to_dict())
            except Exception as e:
                print(f"Error searching keyword '{keyword}': {e}")
                
        return all_results
    
    def get_post_details(self, post_ids: List[str], include_comments: bool = True,
                        account: Optional[Account] = None,
                        proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get details of specific posts.
        
        Args:
            post_ids: List of post IDs to fetch
            include_comments: Whether to include comments
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of post details
        """
        client = self._get_client(account, proxy_config)
        crawler = WeiboCrawler(client)
        
        all_results = []
        for post_id in post_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping post: {post_id}")
                    continue
                    
                weibo_post = crawler.get_post_detail(post_id)
                
                if include_comments:
                    comments = crawler.get_comments_by_id(post_id)
                    if weibo_post:
                        weibo_post['comments'] = comments
                
                if weibo_post:
                    post = self._convert_weibo_post(weibo_post)
                    all_results.append(post.to_dict())
            except Exception as e:
                print(f"Error getting post details for '{post_id}': {e}")
                
        return all_results
    
    def get_user_posts(self, user_ids: List[str], max_posts: int = 50,
                      account: Optional[Account] = None,
                      proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get posts from specific users.
        
        Args:
            user_ids: List of user IDs to fetch posts from
            max_posts: Maximum posts to fetch per user
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of user posts
        """
        client = self._get_client(account, proxy_config)
        crawler = WeiboCrawler(client)
        
        all_results = []
        for user_id in user_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping user: {user_id}")
                    continue
                    
                weibo_posts = crawler.get_user_posts(user_id, max_count=max_posts)
                
                if weibo_posts:
                    # Convert to our standardized model
                    for weibo_post in weibo_posts:
                        post = self._convert_weibo_post(weibo_post)
                        all_results.append(post.to_dict())
            except Exception as e:
                print(f"Error getting posts for user '{user_id}': {e}")
                
        return all_results 