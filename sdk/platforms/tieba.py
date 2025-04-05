from typing import Dict, List, Any, Optional
import time
import random
import sys
import os
from datetime import datetime

# Add project root to path to import existing tieba crawler code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    # Import existing tieba crawler code
    from media_platform.tieba import TiebaClient, TiebaLogin
    from media_platform.tieba.core import TiebaCrawler
except ImportError as e:
    print(f"Warning: Could not import Tieba modules: {e}")
    print("TiebaPlatformHandler will have limited functionality.")
    
    # Define mocks for testing/fallback
    class TiebaClient:
        def __init__(self, cookies=None):
            self.cookies = cookies
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
    
    class TiebaLogin:
        def __init__(self):
            pass
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
            
        def login(self, username, password):
            print(f"Mock login for {username}")
            return {"mock": "cookies"}
    
    class TiebaCrawler:
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

class TiebaPlatformHandler:
    """Handler for Tieba platform operations."""
    
    def __init__(self):
        """Initialize the Tieba platform handler."""
        self._clients = {}  # Cache for logged-in clients
    
    def _get_client(self, account: Optional[Account], proxy_config: Optional[Dict] = None) -> TiebaClient:
        """
        Get or create a client for the given account.
        
        Args:
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            Tieba client
        """
        if not account:
            # Create a client without login
            client = TiebaClient()
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
        login = TiebaLogin()
        if proxy_config:
            login.set_proxy(proxy_config.get('proxy'))
            
        try:
            cookies = login.login(account.username, account.password)
            client = TiebaClient(cookies)
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            self._clients[client_key] = client
            return client
        except Exception as e:
            print(f"Login error for account {account.username}: {e}")
            # Fallback to anonymous client
            client = TiebaClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
    
    def _convert_tieba_user(self, tieba_user: Dict[str, Any]) -> User:
        """
        Convert a Tieba user to the standardized User model.
        
        Args:
            tieba_user: Tieba user data
            
        Returns:
            Standardized User object
        """
        return User(
            id=str(tieba_user.get('id', '')),
            username=tieba_user.get('name', ''),
            nickname=tieba_user.get('name', ''),
            avatar=tieba_user.get('portrait', ''),
            followers_count=tieba_user.get('followers_count', 0),
            following_count=tieba_user.get('following_count', 0),
            description=tieba_user.get('description', ''),
            platform='tieba'
        )
    
    def _convert_tieba_comment(self, tieba_comment: Dict[str, Any]) -> Comment:
        """
        Convert a Tieba comment to the standardized Comment model.
        
        Args:
            tieba_comment: Tieba comment data
            
        Returns:
            Standardized Comment object
        """
        user = None
        if 'author' in tieba_comment and tieba_comment['author']:
            user = self._convert_tieba_user(tieba_comment['author'])
            
        created_at = None
        if 'create_time' in tieba_comment:
            created_at = parse_datetime(tieba_comment.get('create_time', ''))
            
        # Process replies if available
        replies = []
        if 'sub_post_list' in tieba_comment and tieba_comment['sub_post_list']:
            for reply in tieba_comment['sub_post_list']:
                replies.append(self._convert_tieba_comment(reply))
        
        return Comment(
            id=str(tieba_comment.get('id', '')),
            content=clean_text(tieba_comment.get('content', '')),
            user=user,
            created_at=created_at,
            likes_count=tieba_comment.get('agree', {}).get('agree_num', 0),
            parent_id=str(tieba_comment.get('quote_pid', '')) if tieba_comment.get('quote_pid') else None,
            replies=replies,
            platform='tieba'
        )
    
    def _convert_tieba_post(self, tieba_post: Dict[str, Any]) -> Post:
        """
        Convert a Tieba post to the standardized Post model.
        
        Args:
            tieba_post: Tieba post data
            
        Returns:
            Standardized Post object
        """
        user = None
        if 'author' in tieba_post and tieba_post['author']:
            user = self._convert_tieba_user(tieba_post['author'])
            
        created_at = None
        if 'create_time' in tieba_post:
            created_at = parse_datetime(tieba_post.get('create_time', ''))
            
        # Extract media URLs
        media_urls = []
        if 'media' in tieba_post and tieba_post['media']:
            for media_item in tieba_post['media']:
                if 'url' in media_item:
                    media_urls.append(media_item['url'])
        
        # Process comments if available
        comments = []
        if 'comments' in tieba_post and tieba_post['comments']:
            for comment in tieba_post['comments']:
                comments.append(self._convert_tieba_comment(comment))
        
        forum_name = tieba_post.get('forum', {}).get('name', '')
        post_id = tieba_post.get('id', '')
        
        return Post(
            id=str(post_id),
            title=tieba_post.get('title', ''),
            content=clean_text(tieba_post.get('content', '')),
            media_urls=media_urls,
            user=user,
            created_at=created_at,
            updated_at=None,
            likes_count=tieba_post.get('agree', {}).get('agree_num', 0),
            comments_count=tieba_post.get('comment_num', 0),
            shares_count=0,  # Tieba doesn't expose share counts
            views_count=tieba_post.get('view_num', 0),
            url=f"https://tieba.baidu.com/p/{post_id}" if post_id else '',
            comments=comments,
            platform='tieba'
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
        crawler = TiebaCrawler(client)
        
        all_results = []
        for keyword in keywords:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping keyword: {keyword}")
                    continue
                    
                tieba_posts = crawler.search_posts_by_keyword(keyword, max_count=max_results)
                
                if tieba_posts:
                    for post in tieba_posts:
                        standardized_post = self._convert_tieba_post(post)
                        search_result = SearchResult(
                            keyword=keyword,
                            platform='tieba',
                            post=standardized_post,
                            raw_data=post
                        )
                        all_results.append(search_result.to_dict())
            except Exception as e:
                print(f"Error searching for keyword '{keyword}' on Tieba: {e}")
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
        crawler = TiebaCrawler(client)
        
        post_details = []
        for post_id in post_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping post: {post_id}")
                    continue
                
                tieba_post = crawler.get_post_detail(post_id)
                
                if tieba_post:
                    # Fetch comments if requested
                    if include_comments and not tieba_post.get('comments'):
                        tieba_post['comments'] = crawler.get_comments_by_id(post_id)
                        
                    standardized_post = self._convert_tieba_post(tieba_post)
                    post_details.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching post details for post '{post_id}' on Tieba: {e}")
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
        crawler = TiebaCrawler(client)
        
        user_posts = []
        for user_id in user_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping user: {user_id}")
                    continue
                
                tieba_posts = crawler.get_user_posts(user_id, max_count=max_posts)
                
                if tieba_posts:
                    for post in tieba_posts:
                        standardized_post = self._convert_tieba_post(post)
                        user_posts.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching posts for user '{user_id}' on Tieba: {e}")
                continue
                
        return user_posts 