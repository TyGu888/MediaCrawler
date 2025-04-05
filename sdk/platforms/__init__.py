from typing import Dict, Any, Optional

# Import platform handlers
try:
    from .weibo import WeiboPlatformHandler
except ImportError as e:
    print(f"Warning: Could not import Weibo platform handler: {e}")
    WeiboPlatformHandler = None

try:
    from .xiaohongshu import XiaohongshuPlatformHandler
except ImportError as e:
    print(f"Warning: Could not import Xiaohongshu platform handler: {e}")
    XiaohongshuPlatformHandler = None

try:
    from .tieba import TiebaPlatformHandler
except ImportError as e:
    print(f"Warning: Could not import Tieba platform handler: {e}")
    TiebaPlatformHandler = None

try:
    from .zhihu import ZhihuPlatformHandler
except ImportError as e:
    print(f"Warning: Could not import Zhihu platform handler: {e}")
    ZhihuPlatformHandler = None

try:
    from .bilibili import BilibiliPlatformHandler
except ImportError as e:
    print(f"Warning: Could not import Bilibili platform handler: {e}")
    BilibiliPlatformHandler = None

# Platform handler registry
_PLATFORM_HANDLERS = {}

# Add available platform handlers to registry
if WeiboPlatformHandler:
    _PLATFORM_HANDLERS['weibo'] = WeiboPlatformHandler

if XiaohongshuPlatformHandler:
    _PLATFORM_HANDLERS['xiaohongshu'] = XiaohongshuPlatformHandler

if TiebaPlatformHandler:
    _PLATFORM_HANDLERS['tieba'] = TiebaPlatformHandler

if ZhihuPlatformHandler:
    _PLATFORM_HANDLERS['zhihu'] = ZhihuPlatformHandler

if BilibiliPlatformHandler:
    _PLATFORM_HANDLERS['bilibili'] = BilibiliPlatformHandler

# Singleton instances of platform handlers
_PLATFORM_INSTANCES = {}

def get_platform_handler(platform_name: str) -> Optional[Any]:
    """
    Get a handler for the specified platform.
    
    Args:
        platform_name: Name of the platform ('weibo', 'xiaohongshu', 'tieba', 'zhihu', 'bilibili')
        
    Returns:
        Platform handler instance or None if platform is not supported
    """
    if platform_name not in _PLATFORM_HANDLERS:
        return None
        
    # Create and cache instance if it doesn't exist
    if platform_name not in _PLATFORM_INSTANCES:
        try:
            _PLATFORM_INSTANCES[platform_name] = _PLATFORM_HANDLERS[platform_name]()
        except Exception as e:
            print(f"Error initializing platform handler for {platform_name}: {e}")
            return None
            
    return _PLATFORM_INSTANCES[platform_name]
    
def get_supported_platforms() -> list:
    """
    Get a list of all supported platform names.
    
    Returns:
        List of supported platform names
    """
    return list(_PLATFORM_HANDLERS.keys()) 