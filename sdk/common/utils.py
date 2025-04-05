import re
import json
import time
import random
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

def parse_datetime(datetime_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a datetime string into a datetime object.
    
    Args:
        datetime_str: Datetime string in various formats
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not datetime_str:
        return None
        
    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO format with microseconds
        "%Y-%m-%dT%H:%M:%SZ",     # ISO format
        "%Y-%m-%d %H:%M:%S",      # Standard format
        "%Y-%m-%d",               # Date only
        "%Y/%m/%d %H:%M:%S",      # Alternative format
        "%Y/%m/%d"                # Alternative date only
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(datetime_str, fmt)
        except ValueError:
            continue
    
    # Try to extract timestamp from string
    try:
        # Look for unix timestamp
        match = re.search(r'(\d{10})', datetime_str)
        if match:
            return datetime.fromtimestamp(int(match.group(1)))
    except Exception:
        pass
        
    return None

def retry_with_backoff(func, max_retries: int = 3, initial_backoff: float = 1.0, 
                     max_backoff: float = 60.0, backoff_factor: float = 2.0):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retries
        initial_backoff: Initial backoff time in seconds
        max_backoff: Maximum backoff time in seconds
        backoff_factor: Factor to increase backoff time by
        
    Returns:
        Result of the function call
    """
    retries = 0
    backoff = initial_backoff
    
    while True:
        try:
            return func()
        except Exception as e:
            retries += 1
            if retries > max_retries:
                raise e
                
            # Add jitter to avoid thundering herd
            jitter = random.uniform(0.8, 1.2)
            sleep_time = min(backoff * jitter, max_backoff)
            
            print(f"Retry {retries}/{max_retries} after error: {e}")
            print(f"Sleeping for {sleep_time:.2f} seconds")
            
            time.sleep(sleep_time)
            backoff = min(backoff * backoff_factor, max_backoff)

def convert_to_snake_case(camel_case: str) -> str:
    """
    Convert a camelCase or PascalCase string to snake_case.
    
    Args:
        camel_case: String in camelCase or PascalCase
        
    Returns:
        String in snake_case
    """
    # Insert underscore before uppercase letters and convert to lowercase
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', camel_case)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def convert_to_camel_case(snake_case: str) -> str:
    """
    Convert a snake_case string to camelCase.
    
    Args:
        snake_case: String in snake_case
        
    Returns:
        String in camelCase
    """
    # Split by underscore and join parts with first letter capitalized, except the first part
    parts = snake_case.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])

def clean_text(text: Optional[str]) -> str:
    """
    Clean text by removing extra whitespace, newlines, etc.
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
        
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text

def extract_user_id_from_url(url: str, platform: str) -> Optional[str]:
    """
    Extract user ID from a URL.
    
    Args:
        url: URL to extract from
        platform: Platform name
        
    Returns:
        User ID or None if extraction fails
    """
    if not url:
        return None
        
    patterns = {
        'weibo': r'weibo\.com/([^/?&]+)',
        'xiaohongshu': r'xiaohongshu\.com/user/profile/([^/?&]+)',
        'tieba': r'tieba\.baidu\.com/home/main\?id=([^/?&]+)',
        'zhihu': r'zhihu\.com/people/([^/?&]+)',
        'bilibili': r'space\.bilibili\.com/(\d+)'
    }
    
    if platform in patterns:
        match = re.search(patterns[platform], url)
        if match:
            return match.group(1)
    
    return None

def extract_post_id_from_url(url: str, platform: str) -> Optional[str]:
    """
    Extract post ID from a URL.
    
    Args:
        url: URL to extract from
        platform: Platform name
        
    Returns:
        Post ID or None if extraction fails
    """
    if not url:
        return None
        
    patterns = {
        'weibo': r'weibo\.com/\d+/([^/?&]+)',
        'xiaohongshu': r'xiaohongshu\.com/discovery/item/([^/?&]+)',
        'tieba': r'tieba\.baidu\.com/p/(\d+)',
        'zhihu': r'zhihu\.com/question/\d+/answer/(\d+)|zhihu\.com/question/(\d+)',
        'bilibili': r'bilibili\.com/video/([^/?&]+)'
    }
    
    if platform in patterns:
        match = re.search(patterns[platform], url)
        if match:
            for group in match.groups():
                if group:
                    return group
    
    return None 