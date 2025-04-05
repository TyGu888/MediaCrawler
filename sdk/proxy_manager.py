import asyncio
import time
from typing import Dict, List, Optional, Set, Tuple
import random
from datetime import datetime
import sys
import os

# Add project root to path to import existing proxy handling code
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Import existing proxy handling code
    from proxy.providers.kuaidl_proxy import KuaiDaiLiProxy
    from proxy.types import IpInfoModel
except ImportError as e:
    print(f"Warning: Could not import proxy modules: {e}")
    print("ProxyManager will have limited functionality.")
    
    # Define fallback classes if imports fail
    class IpInfoModel:
        def __init__(self, ip="", port=0, user="", password="", expired_time_ts=0, protocol="http"):
            self.ip = ip
            self.port = port
            self.user = user
            self.password = password
            self.expired_time_ts = expired_time_ts
            self.protocol = protocol
            
    class KuaiDaiLiProxy:
        def __init__(self, kdl_user_name="", kdl_user_pwd="", kdl_secret_id="", kdl_signature=""):
            self.kdl_user_name = kdl_user_name
            self.kdl_user_pwd = kdl_user_pwd
            self.secret_id = kdl_secret_id
            self.signature = kdl_signature
            
        async def get_proxies(self, num):
            print("Warning: Using mock proxy implementation!")
            # Return mock proxies
            return [
                IpInfoModel(
                    ip=f"192.168.0.{i}", 
                    port=8080+i, 
                    user="mockuser", 
                    password="mockpass", 
                    expired_time_ts=int(time.time()) + 300,
                    protocol="http"
                ) for i in range(num)
            ]

class ProxyInfo:
    """Class representing a proxy with usage tracking."""
    
    def __init__(self, ip_info: IpInfoModel):
        """
        Initialize a proxy info object.
        
        Args:
            ip_info: IP information from the proxy provider
        """
        self.ip_info = ip_info
        self.last_used = 0
        self.assigned_to = None  # Account it's assigned to
        self.is_valid = True
        self.task_count = 0
        
    def mark_used(self):
        """Mark the proxy as used, updating usage statistics."""
        self.last_used = time.time()
        self.task_count += 1
        
    def is_expired(self) -> bool:
        """
        Check if the proxy has expired.
        
        Returns:
            True if expired, False otherwise
        """
        current_time = int(time.time())
        return current_time >= self.ip_info.expired_time_ts
    
    def time_until_expiry(self) -> int:
        """
        Get the time in seconds until the proxy expires.
        
        Returns:
            Time in seconds until expiry
        """
        current_time = int(time.time())
        return max(0, self.ip_info.expired_time_ts - current_time)
        
    def get_proxy_url(self) -> str:
        """
        Get the proxy URL for use with HTTP clients.
        
        Returns:
            Proxy URL string
        """
        return f"http://{self.ip_info.user}:{self.ip_info.password}@{self.ip_info.ip}:{self.ip_info.port}"

class ProxyManager:
    """Class for managing Kuaidaili proxies with automatic replacement."""
    
    def __init__(self, kuaidaili_config: Dict[str, str], enable_proxy: bool = True):
        """
        Initialize the proxy manager with Kuaidaili credentials.
        
        Args:
            kuaidaili_config: Dict containing Kuaidaili credentials
            enable_proxy: Whether to use proxies
        """
        self.enable_proxy = enable_proxy
        self.kuaidaili_config = kuaidaili_config
        self.kuaidaili_client = KuaiDaiLiProxy(
            kdl_user_name=kuaidaili_config.get('user_name', ''),
            kdl_user_pwd=kuaidaili_config.get('password', ''),
            kdl_secret_id=kuaidaili_config.get('secret_id', ''),
            kdl_signature=kuaidaili_config.get('signature', '')
        )
        self.proxies: List[ProxyInfo] = []
        self.min_pool_size = 10
        self.proxy_replacement_threshold = 60  # Replace proxy if less than 60 seconds until expiry
        self.lock = asyncio.Lock()
    
    async def initialize_pool(self, initial_size: int = 20) -> None:
        """
        Initialize the proxy pool with a given number of proxies.
        
        Args:
            initial_size: Initial number of proxies to fetch
        """
        if not self.enable_proxy:
            return
            
        async with self.lock:
            try:
                ip_info_list = await self.kuaidaili_client.get_proxies(initial_size)
                self.proxies = [ProxyInfo(ip_info) for ip_info in ip_info_list]
                print(f"Initialized proxy pool with {len(self.proxies)} proxies")
            except Exception as e:
                print(f"Error initializing proxy pool: {e}")
    
    async def get_proxy(self) -> Optional[ProxyInfo]:
        """
        Get an available proxy from the pool.
        
        Returns:
            A proxy info object or None if proxies are disabled or unavailable
        """
        if not self.enable_proxy:
            return None
            
        async with self.lock:
            # Remove expired proxies
            self._remove_expired_proxies()
            
            # Check if we need to replenish the pool
            await self._replenish_pool_if_needed()
            
            if not self.proxies:
                return None
                
            # Get the least recently used proxy that's not about to expire
            valid_proxies = [p for p in self.proxies if 
                            p.time_until_expiry() > self.proxy_replacement_threshold]
            
            if not valid_proxies:
                # All proxies are about to expire, get fresh ones
                await self._replenish_pool_if_needed(force=True)
                valid_proxies = [p for p in self.proxies if 
                                p.time_until_expiry() > self.proxy_replacement_threshold]
            
            if not valid_proxies:
                # Still no valid proxies, use any available
                valid_proxies = self.proxies
            
            # Sort by last used time to implement round-robin selection
            valid_proxies.sort(key=lambda x: (x.last_used, x.task_count))
            proxy = valid_proxies[0]
            proxy.mark_used()
            return proxy
    
    async def get_proxies_for_concurrent_tasks(self, count: int) -> List[Optional[ProxyInfo]]:
        """
        Get multiple proxies for concurrent tasks.
        
        Args:
            count: Number of proxies needed
            
        Returns:
            List of proxy info objects, may contain None values if proxies are disabled or unavailable
        """
        if not self.enable_proxy:
            return [None] * count
            
        async with self.lock:
            # Remove expired proxies
            self._remove_expired_proxies()
            
            # Ensure we have enough proxies
            needed = max(0, count - len(self.proxies))
            if needed > 0:
                await self._replenish_pool_if_needed(needed)
            
            # Get proxies that aren't about to expire
            valid_proxies = [p for p in self.proxies if 
                            p.time_until_expiry() > self.proxy_replacement_threshold]
            
            if len(valid_proxies) < count:
                # Not enough valid proxies, get fresh ones
                await self._replenish_pool_if_needed(count - len(valid_proxies), force=True)
                valid_proxies = [p for p in self.proxies if 
                                p.time_until_expiry() > self.proxy_replacement_threshold]
            
            if len(valid_proxies) < count:
                # Still not enough, use whatever we have
                valid_proxies = self.proxies
            
            # Sort by last used time and task count
            valid_proxies.sort(key=lambda x: (x.last_used, x.task_count))
            
            # Get the required number of proxies
            selected_proxies = []
            for i in range(min(count, len(valid_proxies))):
                proxy = valid_proxies[i]
                proxy.mark_used()
                selected_proxies.append(proxy)
                
            # If we need more proxies than available, return None for the rest
            while len(selected_proxies) < count:
                selected_proxies.append(None)
                
            return selected_proxies
    
    def _remove_expired_proxies(self) -> None:
        """Remove expired proxies from the pool."""
        before_count = len(self.proxies)
        self.proxies = [p for p in self.proxies if not p.is_expired()]
        removed_count = before_count - len(self.proxies)
        if removed_count > 0:
            print(f"Removed {removed_count} expired proxies, {len(self.proxies)} remaining")
    
    async def _replenish_pool_if_needed(self, needed: int = None, force: bool = False) -> None:
        """
        Replenish the proxy pool if it's below the minimum size or if forced.
        
        Args:
            needed: Number of proxies needed (defaults to minimum pool size)
            force: Whether to force replenishment regardless of current pool size
        """
        if force or len(self.proxies) < self.min_pool_size:
            count_to_fetch = needed if needed is not None else max(self.min_pool_size - len(self.proxies), 5)
            try:
                new_proxies = await self.kuaidaili_client.get_proxies(count_to_fetch)
                self.proxies.extend([ProxyInfo(ip) for ip in new_proxies])
                print(f"Replenished proxy pool with {len(new_proxies)} new proxies, total: {len(self.proxies)}")
            except Exception as e:
                print(f"Error replenishing proxy pool: {e}") 