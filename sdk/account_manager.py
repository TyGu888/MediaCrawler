from typing import Dict, List, Optional, Tuple
import time
import random

class Account:
    """Class representing a platform account."""
    
    def __init__(self, platform: str, username: str, password: str):
        """
        Initialize an account.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            username: Account username
            password: Account password
        """
        self.platform = platform
        self.username = username
        self.password = password
        self.cookies = None
        self.login_time = None
        self.is_logged_in = False
        self.last_used = 0
        self.task_count = 0
        
    def mark_used(self):
        """Mark the account as used, updating usage statistics."""
        self.last_used = time.time()
        self.task_count += 1

class AccountManager:
    """Class for managing multiple accounts across different platforms."""
    
    def __init__(self):
        """Initialize the account manager."""
        self.accounts: Dict[str, List[Account]] = {}
        
    def add_account(self, platform: str, username: str, password: str) -> None:
        """
        Add an account for a specific platform.
        
        Args:
            platform: Platform name ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
            username: Account username
            password: Account password
        """
        if platform not in self.accounts:
            self.accounts[platform] = []
            
        account = Account(platform, username, password)
        self.accounts[platform].append(account)
        
    def get_available_account(self, platform: str) -> Optional[Account]:
        """
        Get an available account for a specific platform using round-robin selection.
        
        Args:
            platform: Platform name
            
        Returns:
            An available account or None if no accounts are available
        """
        if platform not in self.accounts or not self.accounts[platform]:
            return None
            
        # Get the least recently used account
        platform_accounts = self.accounts[platform]
        platform_accounts.sort(key=lambda x: (x.last_used, x.task_count))
        account = platform_accounts[0]
        account.mark_used()
        return account
        
    def get_accounts_for_concurrent_tasks(self, platform: str, count: int) -> List[Account]:
        """
        Get multiple accounts for concurrent tasks.
        
        Args:
            platform: Platform name
            count: Number of accounts needed
            
        Returns:
            List of available accounts, may be empty if no accounts are available
        """
        available_accounts = []
        if platform not in self.accounts or not self.accounts[platform]:
            return available_accounts
        
        # If we have fewer accounts than requested, we'll reuse accounts
        platform_accounts = self.accounts[platform]
        
        # Sort by last used time and task count to balance the load
        platform_accounts.sort(key=lambda x: (x.last_used, x.task_count))
        
        # Get the required number of accounts
        for i in range(min(count, len(platform_accounts))):
            account = platform_accounts[i]
            account.mark_used()
            available_accounts.append(account)
            
        # If we need more accounts than available, reuse the existing ones
        while len(available_accounts) < count:
            # Clone account references for reuse
            account = random.choice(platform_accounts)
            account.mark_used()
            available_accounts.append(account)
            
        return available_accounts 