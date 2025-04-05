from typing import Dict, List, Any, Optional
import time
import random
import sys
import os
from datetime import datetime

# Add project root to path to import existing Xiaohongshu crawler code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    # Import existing Xiaohongshu crawler code
    from media_platform.xhs import XHSClient, XHSLogin
    from media_platform.xhs.core import XHSCrawler
except ImportError as e:
    print(f"Warning: Could not import Xiaohongshu modules: {e}")
    print("XiaohongshuPlatformHandler will have limited functionality.")
    
    # Define mocks for testing/fallback
    class XHSClient:
        def __init__(self, cookies=None):
            self.cookies = cookies
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
    
    class XHSLogin:
        def __init__(self):
            pass
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
            
        def login(self, username, password):
            print(f"Mock login for {username}")
            return {"mock": "cookies"}
    
    class XHSCrawler:
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

class XiaohongshuPlatformHandler:
    """Handler for Xiaohongshu platform operations."""
    
    def __init__(self):
        """Initialize the Xiaohongshu platform handler."""
        self._clients = {}  # Cache for logged-in clients
    
    def _get_client(self, account: Optional[Account], proxy_config: Optional[Dict] = None) -> XHSClient:
        """
        Get or create a client for the given account.
        
        Args:
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            Xiaohongshu client
        """
        if not account:
            # Create a client without login
            client = XHSClient()
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
        login = XHSLogin()
        if proxy_config:
            login.set_proxy(proxy_config.get('proxy'))
            
        try:
            cookies = login.login(account.username, account.password)
            client = XHSClient(cookies)
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            self._clients[client_key] = client
            return client
        except Exception as e:
            print(f"Login error for account {account.username}: {e}")
            # Fallback to anonymous client
            client = XHSClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
    
    def _convert_xhs_user(self, xhs_user: Dict[str, Any]) -> User:
        """
        Convert a Xiaohongshu user to the standardized User model.
        
        Args:
            xhs_user: Xiaohongshu user data
            
        Returns:
            Standardized User object
        """
        return User(
            id=str(xhs_user.get('user_id', '')),
            username=xhs_user.get('nickname', ''),
            nickname=xhs_user.get('nickname', ''),
            avatar=xhs_user.get('avatar', ''),
            followers_count=xhs_user.get('fans', 0),
            following_count=xhs_user.get('follows', 0),
            description=xhs_user.get('desc', ''),
            platform='xiaohongshu'
        )
    
    def _convert_xhs_comment(self, xhs_comment: Dict[str, Any]) -> Comment:
        """
        Convert a Xiaohongshu comment to the standardized Comment model.
        
        Args:
            xhs_comment: Xiaohongshu comment data
            
        Returns:
            Standardized Comment object
        """
        user = None
        if 'user_info' in xhs_comment and xhs_comment['user_info']:
            user = self._convert_xhs_user(xhs_comment['user_info'])
            
        created_at = None
        if 'time' in xhs_comment:
            created_at = parse_datetime(xhs_comment.get('time', ''))
            
        # Process replies if available
        replies = []
        if 'sub_comments' in xhs_comment and xhs_comment['sub_comments']:
            for reply in xhs_comment['sub_comments']:
                replies.append(self._convert_xhs_comment(reply))
        
        return Comment(
            id=str(xhs_comment.get('id', '')),
            content=clean_text(xhs_comment.get('content', '')),
            user=user,
            created_at=created_at,
            likes_count=xhs_comment.get('like_count', 0),
            parent_id=str(xhs_comment.get('target_comment_id', '')) if xhs_comment.get('target_comment_id') else None,
            replies=replies,
            platform='xiaohongshu'
        )
    
    def _convert_xhs_post(self, xhs_post: Dict[str, Any]) -> Post:
        """
        Convert a Xiaohongshu post to the standardized Post model.
        
        Args:
            xhs_post: Xiaohongshu post data
            
        Returns:
            Standardized Post object
        """
        user = None
        if 'user' in xhs_post and xhs_post['user']:
            user = self._convert_xhs_user(xhs_post['user'])
            
        created_at = None
        if 'time' in xhs_post:
            created_at = parse_datetime(xhs_post.get('time', ''))
            
        # Extract media URLs
        media_urls = []
        if 'images' in xhs_post and xhs_post['images']:
            for image in xhs_post['images']:
                if isinstance(image, str):
                    media_urls.append(image)
                elif isinstance(image, dict) and 'url' in image:
                    media_urls.append(image['url'])
        
        # Process comments if available
        comments = []
        if 'comments' in xhs_post and xhs_post['comments']:
            for comment in xhs_post['comments']:
                comments.append(self._convert_xhs_comment(comment))
        
        post_id = xhs_post.get('id', '')
        
        return Post(
            id=str(post_id),
            title=xhs_post.get('title', ''),
            content=clean_text(xhs_post.get('desc', '')),
            media_urls=media_urls,
            user=user,
            created_at=created_at,
            updated_at=None,
            likes_count=xhs_post.get('liked_count', 0),
            comments_count=xhs_post.get('comment_count', 0),
            shares_count=xhs_post.get('shared_count', 0),
            views_count=xhs_post.get('views', 0),
            url=f"https://www.xiaohongshu.com/discovery/item/{post_id}" if post_id else '',
            comments=comments,
            platform='xiaohongshu'
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
        crawler = XHSCrawler(client)
        
        all_results = []
        for keyword in keywords:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping keyword: {keyword}")
                    continue
                    
                xhs_posts = crawler.search_posts_by_keyword(keyword, max_count=max_results)
                
                if xhs_posts:
                    for post in xhs_posts:
                        standardized_post = self._convert_xhs_post(post)
                        search_result = SearchResult(
                            keyword=keyword,
                            platform='xiaohongshu',
                            post=standardized_post,
                            raw_data=post
                        )
                        all_results.append(search_result.to_dict())
            except Exception as e:
                print(f"Error searching for keyword '{keyword}' on Xiaohongshu: {e}")
                continue
                
        return all_results
    
    def get_post_details(self, post_ids: List[str], include_comments: bool = True,
                        account: Optional[Account] = None,
                        proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get detailed information for specific posts.
        
        Args:
            post_ids: List of post IDs to fetch
            include_comments: Whether to include comments
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of post details
        """
        client = self._get_client(account, proxy_config)
        crawler = XHSCrawler(client)
        
        post_details = []
        for post_id in post_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping post: {post_id}")
                    continue
                
                xhs_post = crawler.get_post_detail(post_id)
                
                if xhs_post:
                    # Fetch comments if requested
                    if include_comments and not xhs_post.get('comments'):
                        xhs_post['comments'] = crawler.get_comments_by_id(post_id)
                        
                    standardized_post = self._convert_xhs_post(xhs_post)
                    post_details.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching post details for post '{post_id}' on Xiaohongshu: {e}")
                continue
                
        return post_details
    
    def get_user_posts(self, user_ids: List[str], max_posts: int = 50,
                      account: Optional[Account] = None,
                      proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get posts from specific users.
        
        Args:
            user_ids: List of user IDs to fetch posts from
            max_posts: Maximum number of posts to fetch per user
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of posts
        """
        client = self._get_client(account, proxy_config)
        crawler = XHSCrawler(client)
        
        user_posts = []
        for user_id in user_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping user: {user_id}")
                    continue
                
                xhs_posts = crawler.get_user_posts(user_id, max_count=max_posts)
                
                if xhs_posts:
                    for post in xhs_posts:
                        standardized_post = self._convert_xhs_post(post)
                        user_posts.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching posts for user '{user_id}' on Xiaohongshu: {e}")
                continue
                
        return user_posts 