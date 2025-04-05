#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Example usage of the MediaCrawler SDK.
This script demonstrates how to use the SDK to scrape content from multiple Chinese social media platforms.
"""

import os
import sys
import json
from typing import Dict, List, Any

# Add parent directory to path to import the SDK
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sdk import MediaCrawlerSDK

def save_results(results: List[Dict[str, Any]], filename: str):
    """
    Save results to a JSON file.
    
    Args:
        results: Results to save
        filename: Filename to save to
    """
    os.makedirs('results', exist_ok=True)
    with open(f'results/{filename}.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(results)} results to results/{filename}.json")

def main():
    """Main function to demonstrate SDK usage."""
    # Initialize the SDK with Kuaidaili credentials
    sdk = MediaCrawlerSDK({
        'user_name': 'd3930139509',  # Replace with your Kuaidaili username
        'password': 'drur7qnt',     # Replace with your Kuaidaili password
        'secret_id': 'odevwetx66kh01tm4ofs',  # Replace with your Kuaidaili secret ID
        'signature': 'iptnktcp4h72r8hetrdwn88everl13d1'  # Replace with your Kuaidaili signature
    })
    
    # Add multiple accounts for each platform to enable multi-account scraping
    # Weibo accounts
    sdk.add_account('weibo', 'weibo_username1', 'weibo_password1')
    sdk.add_account('weibo', 'weibo_username2', 'weibo_password2')
    
    # Xiaohongshu accounts
    sdk.add_account('xiaohongshu', 'xhs_username1', 'xhs_password1')
    sdk.add_account('xiaohongshu', 'xhs_username2', 'xhs_password2')
    
    # Tieba accounts
    sdk.add_account('tieba', 'tieba_username1', 'tieba_password1')
    
    # Zhihu accounts
    sdk.add_account('zhihu', 'zhihu_username1', 'zhihu_password1')
    
    # Bilibili accounts
    sdk.add_account('bilibili', 'bili_username1', 'bili_password1')
    
    # Example 1: Search for keywords on Weibo
    print("\n=== Example 1: Search for keywords on Weibo ===")
    weibo_results = sdk.search_by_keywords(
        platform='weibo',
        keywords=['AI技术', '机器学习', '人工智能', '深度学习', 'ChatGPT'],
        max_results=50,
        concurrent_tasks=3  # Number of concurrent tasks (limited by available accounts)
    )
    
    # Print results
    print(f"Found {len(weibo_results)} search results from Weibo")
    for i, result in enumerate(weibo_results[:2]):  # Print first 2 results
        print(f"Result {i+1}: Keyword '{result.get('keyword')}' - {result.get('total_count')} posts")
        for j, post in enumerate(result.get('posts', [])[:2]):  # Print first 2 posts
            print(f"  Post {j+1}: {post.get('content', '')[:50]}...")
    
    # Save results
    save_results(weibo_results, 'weibo_search_results')
    
    # Example 2: Search Xiaohongshu with different keywords
    print("\n=== Example 2: Search for keywords on Xiaohongshu ===")
    xhs_results = sdk.search_by_keywords(
        platform='xiaohongshu',
        keywords=['旅游', '美食', '时尚'],
        max_results=30,
        concurrent_tasks=2
    )
    
    # Print results
    print(f"Found {len(xhs_results)} search results from Xiaohongshu")
    for i, result in enumerate(xhs_results[:2]):  # Print first 2 results
        print(f"Result {i+1}: Keyword '{result.get('keyword')}' - {result.get('total_count')} posts")
        for j, post in enumerate(result.get('posts', [])[:2]):  # Print first 2 posts
            print(f"  Post {j+1}: {post.get('title', '')} - {post.get('content', '')[:50]}...")
    
    # Save results
    save_results(xhs_results, 'xiaohongshu_search_results')
    
    # Example 3: Get specific post details from Bilibili
    print("\n=== Example 3: Get specific post details from Bilibili ===")
    bilibili_posts = sdk.get_post_details(
        platform='bilibili',
        post_ids=['BV1GJ411x7h7', 'BV1GJ411x7h8'],
        include_comments=True
    )
    
    # Print results
    print(f"Found {len(bilibili_posts)} post details from Bilibili")
    for i, post in enumerate(bilibili_posts):
        print(f"Post {i+1}: {post.get('title', '')} - {len(post.get('comments', []))} comments")
    
    # Save results
    save_results(bilibili_posts, 'bilibili_post_details')
    
    # Example 4: Get posts from specific Zhihu users
    print("\n=== Example 4: Get posts from specific Zhihu users ===")
    zhihu_user_posts = sdk.get_user_posts(
        platform='zhihu',
        user_ids=['user1', 'user2'],
        max_posts=20
    )
    
    # Print results
    print(f"Found {len(zhihu_user_posts)} user posts from Zhihu")
    for i, post in enumerate(zhihu_user_posts[:3]):  # Print first 3 posts
        print(f"Post {i+1}: {post.get('title', '')} - {post.get('content', '')[:50]}...")
    
    # Save results
    save_results(zhihu_user_posts, 'zhihu_user_posts')
    
    print("\nAll examples completed!")

if __name__ == "__main__":
    main() 