import asyncio
from typing import Dict, List, Any, Optional, Tuple
import random
from concurrent.futures import ThreadPoolExecutor

from .account_manager import AccountManager, Account
from .proxy_manager import ProxyManager, ProxyInfo
from .platforms import get_platform_handler

class Task:
    """Class representing a task to be executed."""
    
    def __init__(self, task_type: str, platform: str, data: Any, 
                account: Optional[Account], proxy: Optional[ProxyInfo]):
        """
        Initialize a task.
        
        Args:
            task_type: Type of task ('search', 'detail', 'user')
            platform: Platform name
            data: Task-specific data
            account: Account to use for the task
            proxy: Proxy to use for the task
        """
        self.task_type = task_type  # 'search', 'detail', 'user'
        self.platform = platform
        self.data = data  # keywords for search, post_ids for detail, user_ids for user
        self.account = account
        self.proxy = proxy
        self.result = None
        self.error = None

class TaskScheduler:
    """Class for scheduling and executing tasks across multiple accounts and proxies."""
    
    def __init__(self, account_manager: AccountManager, proxy_manager: ProxyManager):
        """
        Initialize the task scheduler.
        
        Args:
            account_manager: Account manager instance
            proxy_manager: Proxy manager instance
        """
        self.account_manager = account_manager
        self.proxy_manager = proxy_manager
        self.executor = ThreadPoolExecutor(max_workers=20)
    
    def schedule_search_task(self, platform: str, keywords: List[str], 
                           max_results: int = 100, concurrent_tasks: int = 5) -> List[Dict[str, Any]]:
        """
        Schedule a search task for multiple keywords.
        
        Args:
            platform: Platform name
            keywords: List of keywords to search
            max_results: Maximum results to return per keyword
            concurrent_tasks: Number of concurrent tasks to run
            
        Returns:
            List of search results
        """
        # Initialize proxy pool
        asyncio.run(self.proxy_manager.initialize_pool())
        
        # Distribute keywords to tasks
        tasks = []
        chunk_size = max(1, len(keywords) // concurrent_tasks)
        keyword_chunks = [keywords[i:i+chunk_size] for i in range(0, len(keywords), chunk_size)]
        
        # Get accounts and proxies for concurrent execution
        accounts = self.account_manager.get_accounts_for_concurrent_tasks(platform, len(keyword_chunks))
        proxies = asyncio.run(self.proxy_manager.get_proxies_for_concurrent_tasks(len(keyword_chunks)))
        
        # Create tasks
        for i, keyword_chunk in enumerate(keyword_chunks):
            account = accounts[i % len(accounts)] if accounts else None
            proxy = proxies[i % len(proxies)] if proxies else None
            
            task = Task('search', platform, {
                'keywords': keyword_chunk,
                'max_results': max_results
            }, account, proxy)
            tasks.append(task)
        
        # Execute tasks
        results = self._execute_tasks(tasks)
        return results
    
    def schedule_detail_task(self, platform: str, post_ids: List[str], 
                           include_comments: bool = True) -> List[Dict[str, Any]]:
        """
        Schedule a task to get details of specific posts.
        
        Args:
            platform: Platform name
            post_ids: List of post IDs to fetch
            include_comments: Whether to include comments
            
        Returns:
            List of post details
        """
        # Initialize proxy pool
        asyncio.run(self.proxy_manager.initialize_pool())
        
        # Distribute post IDs to tasks
        tasks = []
        max_ids_per_task = 10  # Adjust based on rate limits
        id_chunks = [post_ids[i:i+max_ids_per_task] for i in range(0, len(post_ids), max_ids_per_task)]
        
        # Get accounts and proxies for concurrent execution
        accounts = self.account_manager.get_accounts_for_concurrent_tasks(platform, len(id_chunks))
        proxies = asyncio.run(self.proxy_manager.get_proxies_for_concurrent_tasks(len(id_chunks)))
        
        # Create tasks
        for i, id_chunk in enumerate(id_chunks):
            account = accounts[i % len(accounts)] if accounts else None
            proxy = proxies[i % len(proxies)] if proxies else None
            
            task = Task('detail', platform, {
                'post_ids': id_chunk,
                'include_comments': include_comments
            }, account, proxy)
            tasks.append(task)
        
        # Execute tasks
        results = self._execute_tasks(tasks)
        return results
    
    def schedule_user_task(self, platform: str, user_ids: List[str], 
                          max_posts: int = 50) -> List[Dict[str, Any]]:
        """
        Schedule a task to get posts from specific users.
        
        Args:
            platform: Platform name
            user_ids: List of user IDs to fetch posts from
            max_posts: Maximum posts to fetch per user
            
        Returns:
            List of user posts
        """
        # Initialize proxy pool
        asyncio.run(self.proxy_manager.initialize_pool())
        
        # Distribute user IDs to tasks
        tasks = []
        max_ids_per_task = 5  # Adjust based on rate limits
        id_chunks = [user_ids[i:i+max_ids_per_task] for i in range(0, len(user_ids), max_ids_per_task)]
        
        # Get accounts and proxies for concurrent execution
        accounts = self.account_manager.get_accounts_for_concurrent_tasks(platform, len(id_chunks))
        proxies = asyncio.run(self.proxy_manager.get_proxies_for_concurrent_tasks(len(id_chunks)))
        
        # Create tasks
        for i, id_chunk in enumerate(id_chunks):
            account = accounts[i % len(accounts)] if accounts else None
            proxy = proxies[i % len(proxies)] if proxies else None
            
            task = Task('user', platform, {
                'user_ids': id_chunk,
                'max_posts': max_posts
            }, account, proxy)
            tasks.append(task)
        
        # Execute tasks
        results = self._execute_tasks(tasks)
        return results
    
    def _execute_tasks(self, tasks: List[Task]) -> List[Dict[str, Any]]:
        """
        Execute multiple tasks concurrently.
        
        Args:
            tasks: List of tasks to execute
            
        Returns:
            Combined results from all tasks
        """
        futures = []
        for task in tasks:
            future = self.executor.submit(self._execute_single_task, task)
            futures.append(future)
        
        # Collect results
        all_results = []
        for future in futures:
            try:
                results = future.result()
                if results:
                    all_results.extend(results)
            except Exception as e:
                print(f"Task execution error: {e}")
        
        return all_results
    
    def _execute_single_task(self, task: Task) -> List[Dict[str, Any]]:
        """
        Execute a single task.
        
        Args:
            task: Task to execute
            
        Returns:
            Task results
        """
        try:
            platform_handler = get_platform_handler(task.platform)
            if not platform_handler:
                raise ValueError(f"Unsupported platform: {task.platform}")
            
            # Build proxy configuration if proxy is provided
            proxy_config = None
            if task.proxy:
                ip_info = task.proxy.ip_info
                proxy_config = {
                    'proxy': f"http://{ip_info.user}:{ip_info.password}@{ip_info.ip}:{ip_info.port}",
                    'expiry': ip_info.expired_time_ts
                }
            
            # Execute the appropriate task type
            if task.task_type == 'search':
                return platform_handler.search(
                    task.data['keywords'],
                    max_results=task.data['max_results'],
                    account=task.account,
                    proxy_config=proxy_config
                )
            elif task.task_type == 'detail':
                return platform_handler.get_post_details(
                    task.data['post_ids'],
                    include_comments=task.data['include_comments'],
                    account=task.account,
                    proxy_config=proxy_config
                )
            elif task.task_type == 'user':
                return platform_handler.get_user_posts(
                    task.data['user_ids'],
                    max_posts=task.data['max_posts'],
                    account=task.account,
                    proxy_config=proxy_config
                )
            else:
                raise ValueError(f"Unsupported task type: {task.task_type}")
        except Exception as e:
            print(f"Error executing task: {e}")
            task.error = str(e)
            return [] 