# MediaCrawler SDK

A Python SDK for scraping Chinese social media platforms with multi-account and multi-IP acceleration.

## Features

- **Multi-Platform Support**: Scrape data from Weibo, Xiaohongshu, Tieba, Zhihu, and Bilibili
- **Multi-Account Acceleration**: Distribute tasks across multiple accounts to increase scraping capacity and reduce rate limiting
- **Multi-IP Proxy Management**: Integrate with Kuaidaili proxy service with automatic handling of short-lived IPs (1-5 minutes)
- **Concurrent Task Execution**: Allocate keywords to different account/proxy combinations for faster scraping
- **Standardized Data Models**: Consistent data models across platforms for easier integration
- **Error Handling**: Graceful handling of proxy failures, account issues, and rate limiting

## Requirements

- Python 3.8 or higher
- playwright
- httpx
- asyncio
- (All other dependencies from the MediaCrawler project)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/MediaCrawler.git
   cd MediaCrawler
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install Playwright browsers:
   ```bash
   playwright install
   ```

## Quick Start

Here's a simple example of how to use the SDK:

```python
from sdk import MediaCrawlerSDK

# Initialize the SDK with Kuaidaili credentials
sdk = MediaCrawlerSDK({
    'user_name': 'your_kuaidaili_username',
    'password': 'your_kuaidaili_password',
    'secret_id': 'your_kuaidaili_secret_id',
    'signature': 'your_kuaidaili_signature'
})

# Add accounts for each platform
sdk.add_account('weibo', 'weibo_username1', 'weibo_password1')
sdk.add_account('weibo', 'weibo_username2', 'weibo_password2')
sdk.add_account('xiaohongshu', 'xhs_username1', 'xhs_password1')

# Search for keywords on Weibo
weibo_results = sdk.search_by_keywords(
    platform='weibo',
    keywords=['AI技术', '机器学习', '人工智能'],
    max_results=50,
    concurrent_tasks=3
)

# Get post details from Bilibili
bilibili_posts = sdk.get_post_details(
    platform='bilibili',
    post_ids=['BV1GJ411x7h7', 'BV1GJ411x7h8'],
    include_comments=True
)

# Get posts from Zhihu users
zhihu_user_posts = sdk.get_user_posts(
    platform='zhihu',
    user_ids=['user1', 'user2'],
    max_posts=20
)
```

## API Reference

### MediaCrawlerSDK

The main class for interacting with the SDK.

#### Methods

- `__init__(kuaidaili_config, enable_proxy=True)`: Initialize the SDK
- `add_account(platform, username, password)`: Add an account for a platform
- `search_by_keywords(platform, keywords, max_results=100, concurrent_tasks=5)`: Search for keywords
- `get_post_details(platform, post_ids, include_comments=True)`: Get details of specific posts
- `get_user_posts(platform, user_ids, max_posts=50)`: Get posts from specific users

### Supported Platforms

- `weibo`: Sina Weibo
- `xiaohongshu`: Xiaohongshu (RED)
- `tieba`: Baidu Tieba
- `zhihu`: Zhihu
- `bilibili`: Bilibili

## Advanced Usage

### Handling Short-Lived Proxies

The SDK automatically handles Kuaidaili proxies that expire after 1-5 minutes:

1. The proxy manager tracks expiration times for each proxy
2. Proxies that are about to expire (less than 60 seconds remaining) are replaced
3. If a proxy expires during a task, the task gracefully handles the error and continues with a new proxy

### Task Distribution

The SDK distributes tasks across accounts and proxies using these strategies:

1. Keywords are chunked based on the number of concurrent tasks
2. Each chunk is assigned to an account and proxy
3. If there are more chunks than accounts, accounts are reused in a round-robin fashion
4. Least recently used accounts are prioritized to balance the load

## Extending the SDK

To add support for a new platform:

1. Create a new file in the `sdk/platforms` directory
2. Implement a platform handler class similar to existing platforms
3. Register the new platform in `sdk/platforms/__init__.py`

## License

This project is licensed under the same terms as the MediaCrawler project.

## Acknowledgements

- Based on the [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) project by NanmiCoder
- Uses [Kuaidaili](https://www.kuaidaili.com) for proxy services 