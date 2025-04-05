from typing import Dict, List, Any, Optional
import time
import random
import sys
import os
from datetime import datetime

# Add project root to path to import existing Bilibili crawler code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    # Import existing Bilibili crawler code
    from media_platform.bilibili import BilibiliClient, BilibiliLogin
    from media_platform.bilibili.core import BilibiliCrawler
except ImportError as e:
    print(f"Warning: Could not import Bilibili modules: {e}")
    print("BilibiliPlatformHandler will have limited functionality.")
    
    # Define mocks for testing/fallback
    class BilibiliClient:
        def __init__(self, cookies=None):
            self.cookies = cookies
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
    
    class BilibiliLogin:
        def __init__(self):
            pass
            
        def set_proxy(self, proxy_url):
            self.proxy_url = proxy_url
            
        def login(self, username, password):
            print(f"Mock login for {username}")
            return {"mock": "cookies"}
    
    class BilibiliCrawler:
        def __init__(self, client):
            self.client = client
            
        def search_videos_by_keyword(self, keyword, max_count=100):
            return [{"id": f"mock_video_{i}", "content": f"Mock video for {keyword}"} for i in range(5)]
            
        def get_video_detail(self, video_id):
            return {"id": video_id, "content": f"Mock video detail for {video_id}"}
            
        def get_comments_by_id(self, video_id):
            return [{"id": f"comment_{i}", "content": f"Mock comment {i}"} for i in range(3)]
            
        def get_user_videos(self, user_id, max_count=50):
            return [{"id": f"user_video_{i}", "content": f"Mock user video {i}"} for i in range(5)]

from ..account_manager import Account
from ..common.models import User, Post, Comment, SearchResult
from ..common.utils import parse_datetime, clean_text

class BilibiliPlatformHandler:
    """Handler for Bilibili platform operations."""
    
    def __init__(self):
        """Initialize the Bilibili platform handler."""
        self._clients = {}  # Cache for logged-in clients
    
    def _get_client(self, account: Optional[Account], proxy_config: Optional[Dict] = None) -> BilibiliClient:
        """
        Get or create a client for the given account.
        
        Args:
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            Bilibili client
        """
        if not account:
            # Create a client without login
            client = BilibiliClient()
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
        login = BilibiliLogin()
        if proxy_config:
            login.set_proxy(proxy_config.get('proxy'))
            
        try:
            cookies = login.login(account.username, account.password)
            client = BilibiliClient(cookies)
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            self._clients[client_key] = client
            return client
        except Exception as e:
            print(f"Login error for account {account.username}: {e}")
            # Fallback to anonymous client
            client = BilibiliClient()
            if proxy_config:
                client.set_proxy(proxy_config.get('proxy'))
            return client
    
    def _convert_bilibili_user(self, bilibili_user: Dict[str, Any]) -> User:
        """
        Convert a Bilibili user to the standardized User model.
        
        Args:
            bilibili_user: Bilibili user data
            
        Returns:
            Standardized User object
        """
        return User(
            id=str(bilibili_user.get('mid', '')),
            username=bilibili_user.get('name', ''),
            nickname=bilibili_user.get('name', ''),
            avatar=bilibili_user.get('face', ''),
            followers_count=bilibili_user.get('follower', 0),
            following_count=bilibili_user.get('following', 0),
            description=bilibili_user.get('sign', ''),
            platform='bilibili'
        )
    
    def _convert_bilibili_comment(self, bilibili_comment: Dict[str, Any]) -> Comment:
        """
        Convert a Bilibili comment to the standardized Comment model.
        
        Args:
            bilibili_comment: Bilibili comment data
            
        Returns:
            Standardized Comment object
        """
        user = None
        if 'member' in bilibili_comment and bilibili_comment['member']:
            user = self._convert_bilibili_user(bilibili_comment['member'])
            
        created_at = None
        if 'ctime' in bilibili_comment:
            created_at = parse_datetime(str(bilibili_comment.get('ctime', '')))
            
        # Process replies if available
        replies = []
        if 'replies' in bilibili_comment and bilibili_comment['replies']:
            for reply in bilibili_comment['replies']:
                replies.append(self._convert_bilibili_comment(reply))
        
        return Comment(
            id=str(bilibili_comment.get('rpid', '')),
            content=clean_text(bilibili_comment.get('content', {}).get('message', '')),
            user=user,
            created_at=created_at,
            likes_count=bilibili_comment.get('like', 0),
            parent_id=str(bilibili_comment.get('parent', '')) if bilibili_comment.get('parent') else None,
            replies=replies,
            platform='bilibili'
        )
    
    def _convert_bilibili_video(self, bilibili_video: Dict[str, Any]) -> Post:
        """
        Convert a Bilibili video to the standardized Post model.
        
        Args:
            bilibili_video: Bilibili video data
            
        Returns:
            Standardized Post object
        """
        user = None
        if 'owner' in bilibili_video and bilibili_video['owner']:
            user = self._convert_bilibili_user(bilibili_video['owner'])
            
        created_at = None
        if 'pubdate' in bilibili_video:
            created_at = parse_datetime(str(bilibili_video.get('pubdate', '')))
            
        # Extract thumbnail URL
        media_urls = []
        if 'pic' in bilibili_video and bilibili_video['pic']:
            media_urls.append(bilibili_video['pic'])
        
        # Process comments if available
        comments = []
        if 'comments' in bilibili_video and bilibili_video['comments']:
            for comment in bilibili_video['comments']:
                comments.append(self._convert_bilibili_comment(comment))
        
        video_id = bilibili_video.get('bvid', '') or bilibili_video.get('aid', '')
        
        return Post(
            id=str(video_id),
            title=bilibili_video.get('title', ''),
            content=clean_text(bilibili_video.get('desc', '')),
            media_urls=media_urls,
            user=user,
            created_at=created_at,
            updated_at=None,
            likes_count=bilibili_video.get('like', 0),
            comments_count=bilibili_video.get('reply', 0),
            shares_count=bilibili_video.get('share', 0),
            views_count=bilibili_video.get('view', 0),
            url=f"https://www.bilibili.com/video/{video_id}" if video_id else '',
            comments=comments,
            platform='bilibili'
        )
    
    def search(self, keywords: List[str], max_results: int = 100, 
              account: Optional[Account] = None, 
              proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Search videos by keywords.
        
        Args:
            keywords: List of keywords to search
            max_results: Maximum results to return per keyword
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of search results
        """
        client = self._get_client(account, proxy_config)
        crawler = BilibiliCrawler(client)
        
        all_results = []
        for keyword in keywords:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping keyword: {keyword}")
                    continue
                    
                bilibili_videos = crawler.search_videos_by_keyword(keyword, max_count=max_results)
                
                if bilibili_videos:
                    for video in bilibili_videos:
                        standardized_post = self._convert_bilibili_video(video)
                        search_result = SearchResult(
                            keyword=keyword,
                            platform='bilibili',
                            post=standardized_post,
                            raw_data=video
                        )
                        all_results.append(search_result.to_dict())
            except Exception as e:
                print(f"Error searching for keyword '{keyword}' on Bilibili: {e}")
                continue
                
        return all_results
    
    def get_post_details(self, post_ids: List[str], include_comments: bool = True,
                        account: Optional[Account] = None,
                        proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get detailed information for specific videos.
        
        Args:
            post_ids: List of video IDs to fetch
            include_comments: Whether to include comments
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of video details
        """
        client = self._get_client(account, proxy_config)
        crawler = BilibiliCrawler(client)
        
        post_details = []
        for post_id in post_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping video: {post_id}")
                    continue
                
                bilibili_video = crawler.get_video_detail(post_id)
                
                if bilibili_video:
                    # Fetch comments if requested
                    if include_comments and not bilibili_video.get('comments'):
                        bilibili_video['comments'] = crawler.get_comments_by_id(post_id)
                        
                    standardized_post = self._convert_bilibili_video(bilibili_video)
                    post_details.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching video details for video '{post_id}' on Bilibili: {e}")
                continue
                
        return post_details
    
    def get_user_posts(self, user_ids: List[str], max_posts: int = 50,
                      account: Optional[Account] = None,
                      proxy_config: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Get videos from specific users.
        
        Args:
            user_ids: List of user IDs to fetch videos from
            max_posts: Maximum number of videos to fetch per user
            account: Account to use
            proxy_config: Proxy configuration
            
        Returns:
            List of videos
        """
        client = self._get_client(account, proxy_config)
        crawler = BilibiliCrawler(client)
        
        user_posts = []
        for user_id in user_ids:
            try:
                # Add jitter to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Check if proxy is about to expire, skip if it is
                if proxy_config and int(time.time()) >= proxy_config.get('expiry', 0) - 30:
                    print(f"Proxy is about to expire, skipping user: {user_id}")
                    continue
                
                bilibili_videos = crawler.get_user_videos(user_id, max_count=max_posts)
                
                if bilibili_videos:
                    for video in bilibili_videos:
                        standardized_post = self._convert_bilibili_video(video)
                        user_posts.append(standardized_post.to_dict())
            except Exception as e:
                print(f"Error fetching videos for user '{user_id}' on Bilibili: {e}")
                continue
                
        return user_posts 