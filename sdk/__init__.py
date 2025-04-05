from typing import List, Dict, Any, Optional
from .account_manager import AccountManager
from .proxy_manager import ProxyManager
from .task_scheduler import TaskScheduler
from .result_processor import ResultProcessor

class MediaCrawlerSDK:
    """
    Unified SDK for scraping Chinese social media platforms with multi-account
    and multi-IP acceleration through Kuaidaili proxies.
    """
    
    def __init__(self, kuaidaili_config: Dict[str, str], enable_proxy: bool = True):
        """
        Initialize the SDK with Kuaidaili credentials.
        
        Args:
            kuaidaili_config: Dict containing Kuaidaili credentials
                - user_name: Kuaidaili username
                - password: Kuaidaili password
                - secret_id: Kuaidaili secret ID
                - signature: Kuaidaili signature
            enable_proxy: Whether to use proxies (default: True)
        """
        self.account_manager = AccountManager()
        self.proxy_manager = ProxyManager(kuaidaili_config, enable_proxy)
        self.task_scheduler = TaskScheduler(self.account_manager, self.proxy_manager)
        self.result_processor = ResultProcessor()
    
    def add_account(self, platform: str, username: str, password: str) -> None:
        """
        Add an account for a specific platform.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            username: Account username
            password: Account password
        """
        self.account_manager.add_account(platform, username, password)
    
    def search_by_keywords(self, platform: str, keywords: List[str], 
                          max_results: int = 100, 
                          concurrent_tasks: int = 5) -> List[Dict[str, Any]]:
        """
        Search content from a platform based on keywords.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            keywords: List of keywords to search
            max_results: Maximum results to return per keyword
            concurrent_tasks: Number of concurrent tasks to run
            
        Returns:
            List of dictionaries containing search results
        """
        return self.task_scheduler.schedule_search_task(
            platform, keywords, max_results, concurrent_tasks)
    
    def get_post_details(self, platform: str, post_ids: List[str], 
                        include_comments: bool = True) -> List[Dict[str, Any]]:
        """
        Get details of specific posts by their IDs.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            post_ids: List of post IDs to fetch
            include_comments: Whether to include comments
            
        Returns:
            List of dictionaries containing post details
        """
        return self.task_scheduler.schedule_detail_task(
            platform, post_ids, include_comments)
    
    def get_user_posts(self, platform: str, user_ids: List[str], 
                      max_posts: int = 50) -> List[Dict[str, Any]]:
        """
        Get posts from specific users.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            user_ids: List of user IDs to fetch posts from
            max_posts: Maximum posts to fetch per user
            
        Returns:
            List of dictionaries containing user posts
        """
        return self.task_scheduler.schedule_user_task(
            platform, user_ids, max_posts) 