from typing import Dict, List, Any, Optional
import time
import random
import sys
import os
from datetime import datetime

# Add project root to path to import existing Zhihu crawler code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    # Import existing Zhihu crawler code
    from media_platform.zhihu import ZhihuClient, ZhihuLogin
    from media_platform.zhihu.core import ZhihuCrawler
except ImportError as e:
    print(f"Warning: Could not import Zhihu modules: {e}")
    print("ZhihuPlatformHandler will have limited functionality.")
    
    # Define mocks for testing/fallback
    class ZhihuClient:
        def __init__(self, cookies=None):
            self.cookies = cookies
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
    
    class ZhihuLogin:
        def __init__(self):
            pass
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
            
        def login(self, username, password):
            print(f"Mock login for {username}")
            return {"mock": "cookies"}
    
    class ZhihuCrawler:
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

class ZhihuPlatformHandler:
    """Handler for Zhihu platform operations."""
    
    def __init__(self):
        """Initialize the Zhihu platform handler."""
        self._clients = {}  # Cache for logged-in clients
    
    def _get_client(self, account: Optional[Account], proxy_config: Optional[Dict] = None) -> ZhihuClient:
        """
        Get or create a client for the given account.
        
        Args:
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            Zhihu client
        """
        if not account:
            # Create a client without login
            client = ZhihuClient()
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
        login = ZhihuLogin()
        if proxy_config:
            login.set_proxy(proxy_config.get('proxy'))
            
        try:
            cookies = login.login(account.username, account.password)
            client = ZhihuClient(cookies)
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            self._clients[client_key] = client
            return client
        except Exception as e:
            print(f"Login error for account {account.username}: {e}")
            # Fallback to anonymous client
            client = ZhihuClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
    
    def _convert_zhihu_user(self, zhihu_user: Dict[str, Any]) -> User:
        """
        Convert a Zhihu user to the standardized User model.
        
        Args:
            zhihu_user: Zhihu user data
            
        Returns:
            Standardized User object
        """
        return User(
            id=str(zhihu_user.get('id', '')),
            username=zhihu_user.get('url_token', ''),
            nickname=zhihu_user.get('name', ''),
            avatar=zhihu_user.get('avatar_url', ''),
            followers_count=zhihu_user.get('follower_count', 0),
            following_count=zhihu_user.get('following_count', 0),
            description=zhihu_user.get('headline', ''),
            platform='zhihu'
        )
    
    def _convert_zhihu_comment(self, zhihu_comment: Dict[str, Any]) -> Comment:
        """
        Convert a Zhihu comment to the standardized Comment model.
        
        Args:
            zhihu_comment: Zhihu comment data
            
        Returns:
            Standardized Comment object
        """
        user = None
        if 'author' in zhihu_comment and zhihu_comment['author']:
            user = self._convert_zhihu_user(zhihu_comment['author'])
            
        created_at = None
        if 'created_time' in zhihu_comment:
            created_at = parse_datetime(zhihu_comment.get('created_time', ''))
            
        # Process replies if available
        replies = []
        if 'child_comments' in zhihu_comment and zhihu_comment['child_comments']:
            for reply in zhihu_comment['child_comments']:
                replies.append(self._convert_zhihu_comment(reply))
        
        return Comment(
            id=str(zhihu_comment.get('id', '')),
            content=clean_text(zhihu_comment.get('content', '')),
            user=user,
            created_at=created_at,
            likes_count=zhihu_comment.get('vote_count', 0),
            parent_id=str(zhihu_comment.get('reply_to_id', '')) if zhihu_comment.get('reply_to_id') else None,
            replies=replies,
            platform='zhihu'
        )
    
    def _convert_zhihu_post(self, zhihu_post: Dict[str, Any]) -> Post:
        """
        Convert a Zhihu post to the standardized Post model.
        
        Args:
            zhihu_post: Zhihu post data
            
        Returns:
            Standardized Post object
        """
        user = None
        if 'author' in zhihu_post and zhihu_post['author']:
            user = self._convert_zhihu_user(zhihu_post['author'])
            
        created_at = None
        if 'created_time' in zhihu_post:
            created_at = parse_datetime(zhihu_post.get('created_time', ''))
            
        updated_at = None
        if 'updated_time' in zhihu_post:
            updated_at = parse_datetime(zhihu_post.get('updated_time', ''))
            
        # Extract media URLs
        media_urls = []
        if 'images' in zhihu_post and zhihu_post['images']:
            for image_url in zhihu_post['images']:
                media_urls.append(image_url)
        
        # Process comments if available
        comments = []
        if 'comments' in zhihu_post and zhihu_post['comments']:
            for comment in zhihu_post['comments']:
                comments.append(self._convert_zhihu_comment(comment))
        
        post_id = zhihu_post.get('id', '')
        
        # Determine post URL based on type
        post_url = ''
        if 'type' in zhihu_post:
            if zhihu_post['type'] == 'answer':
                question_id = zhihu_post.get('question', {}).get('id', '')
                post_url = f"https://www.zhihu.com/question/{question_id}/answer/{post_id}"
            elif zhihu_post['type'] == 'article':
                post_url = f"https://zhuanlan.zhihu.com/p/{post_id}"
            elif zhihu_post['type'] == 'question':
                post_url = f"https://www.zhihu.com/question/{post_id}"
                
        return Post(
            id=str(post_id),
            title=zhihu_post.get('title', '') or zhihu_post.get('question', {}).get('title', ''),
            content=clean_text(zhihu_post.get('content', '')),
            media_urls=media_urls,
            user=user,
            created_at=created_at,
            updated_at=updated_at,
            likes_count=zhihu_post.get('voteup_count', 0),
            comments_count=zhihu_post.get('comment_count', 0),
            shares_count=0,  # Zhihu doesn't expose share counts
            views_count=zhihu_post.get('view_count', 0),
            url=post_url,
            comments=comments,
            platform='zhihu'
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
        crawler = ZhihuCrawler(client)
        
        all_results = []
        for keyword in keywords:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping keyword: {keyword}")
                    continue
                    
                zhihu_posts = crawler.search_posts_by_keyword(keyword, max_count=max_results)
                
                if zhihu_posts:
                    for post in zhihu_posts:
                        standardized_post = self._convert_zhihu_post(post)
                        search_result = SearchResult(
                            keyword=keyword,
                            platform='zhihu',
                            post=standardized_post,
                            raw_data=post
                        )
                        all_results.append(search_result.to_dict())
            except Exception as e:
                print(f"Error searching for keyword '{keyword}' on Zhihu: {e}")
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
        crawler = ZhihuCrawler(client)
        
        post_details = []
        for post_id in post_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping post: {post_id}")
                    continue
                
                zhihu_post = crawler.get_post_detail(post_id)
                
                if zhihu_post:
                    # Fetch comments if requested
                    if include_comments and not zhihu_post.get('comments'):
                        zhihu_post['comments'] = crawler.get_comments_by_id(post_id)
                        
                    standardized_post = self._convert_zhihu_post(zhihu_post)
                    post_details.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching post details for post '{post_id}' on Zhihu: {e}")
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
        crawler = ZhihuCrawler(client)
        
        user_posts = []
        for user_id in user_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping user: {user_id}")
                    continue
                
                zhihu_posts = crawler.get_user_posts(user_id, max_count=max_posts)
                
                if zhihu_posts:
                    for post in zhihu_posts:
                        standardized_post = self._convert_zhihu_post(post)
                        user_posts.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching posts for user '{user_id}' on Zhihu: {e}")
                continue
                
        return user_posts 