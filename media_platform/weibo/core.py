# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：  
# 1. 不得用于任何商业用途。  
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。  
# 3. 不得进行大规模爬取或对平台造成运营干扰。  
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。   
# 5. 不得用于任何非法或不当的用途。
#   
# 详细许可条款请参阅项目根目录下的LICENSE文件。  
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。  


# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/23 15:41
# @Desc    : 微博爬虫主流程代码


import asyncio
import os
import random
import time
from asyncio import Task
from typing import Dict, List, Optional, Tuple

from playwright.async_api import (BrowserContext, BrowserType, Page,
                                  async_playwright)

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import weibo as weibo_store
from tools import utils
from var import crawler_type_var, source_keyword_var

from .client import WeiboClient
from .exception import DataFetchError
from .field import SearchType
from .help import filter_search_result_card
from .login import WeiboLogin

import sys
import httpx
from httpx import ReadTimeout, ConnectTimeout, ConnectError, RequestError


class WeiboCrawler(AbstractCrawler):
    context_page: Page
    wb_client: WeiboClient
    browser_context: BrowserContext

    def __init__(self):
        self.index_url = "https://www.weibo.com"
        self.mobile_index_url = "https://m.weibo.cn"
        self.user_agent = utils.get_user_agent()
        self.mobile_user_agent = utils.get_mobile_user_agent()

    async def start(self):
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = self.format_proxy_info(ip_proxy_info)

        async with async_playwright() as playwright:
            # Launch a browser context.
            chromium = playwright.chromium
            self.browser_context = await self.launch_browser(
                chromium,
                None,
                self.mobile_user_agent,
                headless=config.HEADLESS
            )
            # stealth.min.js is a js script to prevent the website from detecting the crawler.
            await self.browser_context.add_init_script(path="libs/stealth.min.js")
            self.context_page = await self.browser_context.new_page()
            await self.context_page.goto(self.mobile_index_url)

            # Create a client to interact with the xiaohongshu website.
            self.wb_client = await self.create_weibo_client(httpx_proxy_format)
            if not await self.wb_client.pong():
                login_obj = WeiboLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES
                )
                await login_obj.begin()

                # 登录成功后重定向到手机端的网站，再更新手机端登录成功的cookie
                utils.logger.info("[WeiboCrawler.start] redirect weibo mobile homepage and update cookies on mobile platform")
                await self.context_page.goto(self.mobile_index_url)
                await asyncio.sleep(2)
                await self.wb_client.update_cookies(browser_context=self.browser_context)

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for video and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass
            utils.logger.info("[WeiboCrawler.start] Weibo Crawler finished ...")

    async def search(self):
        """
        search weibo note with keywords
        :return:
        """
        utils.logger.info("[WeiboCrawler.search] Begin search weibo keywords")
        weibo_limit_count = 10  # weibo limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < weibo_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = weibo_limit_count
        start_page = config.START_PAGE
        empty_page_count = 0
        for keyword in config.KEYWORDS:
            source_keyword_var.set(keyword)
            utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}")
            page = 1
            while (page - start_page + 1) * weibo_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
                utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
                result = await self.wb_client.get_note_by_keyword(
                    keyword=keyword,
                    page=page,
                    search_type=SearchType.DEFAULT
                )
                
                if result.get("no_more_content", False):
                    empty_page_count += 1
                    if empty_page_count >= 2:  # Two consecutive empty pages
                        utils.logger.info(f"No more content for keyword '{keyword}' after {page} pages, moving to next keyword")
                        empty_page_count = 0
                        break
                else:
                    empty_page_count = 0  # Reset counter if we found content
                    
                    note_id_list: List[str] = []
                    note_list = filter_search_result_card(result.get("cards"))
                    for note_item in note_list:
                        if note_item:
                            mblog: Dict = note_item.get("mblog")
                            if mblog:
                                note_id = mblog.get("id")
                                await weibo_store.update_weibo_note(note_item)
                                await self.get_note_images(mblog)
                                
                                # Only add notes with comments to the list for comment crawling
                                comments_count = int(mblog.get("comments_count", 0))
                                if comments_count > 0:
                                    note_id_list.append(note_id)
                                else:
                                    utils.logger.info(f"[WeiboCrawler.search] Note {note_id} has no comments, skipping comment crawling")

                    page += 1
                    # Only fetch comments if there are notes with comments
                    if note_id_list:
                        await self.batch_get_notes_comments(note_id_list)
                    else:
                        utils.logger.info(f"[WeiboCrawler.search] No notes with comments found on page {page} for keyword '{keyword}'")

    async def get_keyword(self,keyword):
        start_page = config.START_PAGE
        source_keyword_var.set(keyword)
        weibo_limit_count = 10 
        utils.logger.info(f"[WeiboCrawler.search] Current search keyword: {keyword}")
        page = 1
        while (page - start_page + 1) * weibo_limit_count <= config.CRAWLER_MAX_NOTES_COUNT:
            if page < start_page:
                utils.logger.info(f"[WeiboCrawler.search] Skip page: {page}")
                page += 1
                continue
            utils.logger.info(f"[WeiboCrawler.search] search weibo keyword: {keyword}, page: {page}")
            search_res = await self.wb_client.get_note_by_keyword(
                keyword=keyword,
                page=page,
                search_type=SearchType.DEFAULT
            )
            note_id_list: List[str] = []
            note_list = filter_search_result_card(search_res.get("cards"))
            for note_item in note_list:
                if note_item:
                    mblog: Dict = note_item.get("mblog")
                    if mblog:
                        note_id_list.append(mblog.get("id"))
                        await weibo_store.update_weibo_note(note_item)
                        await self.get_note_images(mblog)

            page += 1
            await self.batch_get_notes_comments(note_id_list)


    async def get_specified_notes(self):
        """
        get specified notes info
        :return:
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_info_task(note_id=note_id, semaphore=semaphore) for note_id in
            config.WEIBO_SPECIFIED_ID_LIST
        ]
        video_details = await asyncio.gather(*task_list)
        for note_item in video_details:
            if note_item:
                await weibo_store.update_weibo_note(note_item)
        await self.batch_get_notes_comments(config.WEIBO_SPECIFIED_ID_LIST)

    async def get_note_info_task(self, note_id: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """
        Get note detail task
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                result = await self.wb_client.get_note_info_by_id(note_id)
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_info_task] Get note detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(
                    f"[WeiboCrawler.get_note_info_task] have not fund note detail note_id:{note_id}, err: {ex}")
                return None

    async def batch_get_notes_comments(self, note_id_list: List[str]):
        """
        batch get notes comments
        :param note_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[WeiboCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[WeiboCrawler.batch_get_notes_comments] note ids:{note_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for note_id in note_id_list:
            task = asyncio.create_task(self.get_note_comments(note_id, semaphore), name=note_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_note_comments(self, note_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for note id
        :param note_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                utils.logger.info(f"[WeiboCrawler.get_note_comments] begin get note_id: {note_id} comments ...")
                await self.wb_client.get_note_all_comments(
                    note_id=note_id,
                    crawl_interval=random.randint(1,3), # 微博对API的限流比较严重，所以延时提高一些
                    callback=weibo_store.batch_update_weibo_note_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
                )
            except DataFetchError as ex:
                utils.logger.error(f"[WeiboCrawler.get_note_comments] get note_id: {note_id} comment error: {ex}")
                # 简单的重试逻辑
                time.sleep(5)
            except (ReadTimeout, ConnectTimeout, ConnectError) as e:
                # 专门处理网络连接和超时错误
                utils.logger.warning(f"[WeiboCrawler] Network/timeout error: {e}")
                
                # 递增重试时间策略
                self.timeout_count = getattr(self, 'timeout_count', 0) + 1
                retry_seconds = min(10 * self.timeout_count, 120)  # 从10秒开始，最多到2分钟
                
                utils.logger.info(f"Connection issue occurred. Waiting {retry_seconds} seconds before retrying...")
                time.sleep(retry_seconds)
                
                # 重置成功后的超时计数器
                if hasattr(self, 'success_after_timeout'):
                    self.success_after_timeout += 1
                    if self.success_after_timeout >= 3:  # 连续成功3次后重置超时计数
                        self.timeout_count = 0
                else:
                    self.success_after_timeout = 0
                
                # 检查是否应该退出
                if self.timeout_count >= 15:  # 如果15次连续超时，可能存在严重网络问题
                    utils.logger.error("Too many network errors. Consider checking your network or trying later.")
                    # 选择1: 休息较长时间后继续
                    utils.logger.info("Taking a 10 minute break before continuing...")
                    time.sleep(300)
                    self.timeout_count = self.timeout_count // 2  # 减少计数而不是完全重置
                    # 选择2: 如果希望直接退出，取消注释下面两行
                    # utils.logger.error("Exiting due to persistent network issues.")
                    # sys.exit(1)
            except Exception as e:
                # 处理所有其他异常，包括可能的block和其他未预见的错误
                error_str = str(e).lower()
                
                # 检测block相关指标
                block_indicators = [
                    "expecting value: line 1 column 1 (char 0)",
                    "访问频率过高", "请求过于频繁", "need login", "访问受限",
                    "请求被拒绝", "操作太频繁", "无权限", "请登录", "412", "403",
                    "empty response", "invalid json"
                ]
                
                is_block = any(indicator.lower() in error_str for indicator in block_indicators)
                
                if is_block:
                    # 处理block情况...
                    utils.logger.error(f"[WeiboCrawler] Likely blocked: {e}")
                    self.block_count = getattr(self, 'block_count', 0) + 1
                    
                    # 根据block次数决定休息时间和是否退出
                    if self.block_count >= 6:
                        utils.logger.error("Multiple blocks detected. Exiting.")
                        sys.exit(1)
                    else:
                        sleep_time = 60   # 指数增长
                        utils.logger.warning(f"Sleeping for {sleep_time} seconds...")
                        time.sleep(sleep_time)
                else:
                    # 其他未知错误
                    utils.logger.error(f"[WeiboCrawler] Unexpected error: {e}")
                    utils.logger.info("Continuing with next task after brief pause...")
                    time.sleep(2)  # 短暂暂停后继续

    async def get_note_images(self, mblog: Dict):
        """
        get note images
        :param mblog:
        :return:
        """
        if not config.ENABLE_GET_IMAGES:
            utils.logger.info(f"[WeiboCrawler.get_note_images] Crawling image mode is not enabled")
            return
        
        pics: Dict = mblog.get("pics")
        if not pics:
            return
        for pic in pics:
            url = pic.get("url")
            if not url:
                continue
            content = await self.wb_client.get_note_image(url)
            if content != None:
                extension_file_name = url.split(".")[-1]
                await weibo_store.update_weibo_note_image(pic["pid"], content, extension_file_name)


    async def get_creators_and_notes(self) -> None:
        """
        Get creator's information and their notes and comments
        Returns:

        """
        utils.logger.info("[WeiboCrawler.get_creators_and_notes] Begin get weibo creators")
        for user_id in config.WEIBO_CREATOR_ID_LIST:
            createor_info_res: Dict = await self.wb_client.get_creator_info_by_id(creator_id=user_id)
            if createor_info_res:
                createor_info: Dict = createor_info_res.get("userInfo", {})
                utils.logger.info(f"[WeiboCrawler.get_creators_and_notes] creator info: {createor_info}")
                if not createor_info:
                    raise DataFetchError("Get creator info error")
                await weibo_store.save_creator(user_id, user_info=createor_info)

                # Get all note information of the creator
                all_notes_list = await self.wb_client.get_all_notes_by_creator_id(
                    creator_id=user_id,
                    container_id=createor_info_res.get("lfid_container_id"),
                    crawl_interval=0,
                    callback=weibo_store.batch_update_weibo_notes
                )

                note_ids = [note_item.get("mblog", {}).get("id") for note_item in all_notes_list if
                            note_item.get("mblog", {}).get("id")]
                await self.batch_get_notes_comments(note_ids)

            else:
                utils.logger.error(
                    f"[WeiboCrawler.get_creators_and_notes] get creator info error, creator_id:{user_id}")



    async def create_weibo_client(self, httpx_proxy: Optional[str]) -> WeiboClient:
        """Create xhs client"""
        utils.logger.info("[WeiboCrawler.create_weibo_client] Begin create weibo API client ...")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        weibo_client_obj = WeiboClient(
            proxies=httpx_proxy,
            headers={
                "User-Agent": utils.get_mobile_user_agent(),
                "Cookie": cookie_str,
                "Origin": "https://m.weibo.cn",
                "Referer": "https://m.weibo.cn",
                "Content-Type": "application/json;charset=UTF-8"
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
        )
        return weibo_client_obj

    @staticmethod
    def format_proxy_info(ip_proxy_info: IpInfoModel) -> Tuple[Optional[Dict], Optional[Dict]]:
        """format proxy info for playwright and httpx"""
        playwright_proxy = {
            "server": f"{ip_proxy_info.protocol}{ip_proxy_info.ip}:{ip_proxy_info.port}",
            "username": ip_proxy_info.user,
            "password": ip_proxy_info.password,
        }
        httpx_proxy = {
            f"{ip_proxy_info.protocol}": f"http://{ip_proxy_info.user}:{ip_proxy_info.password}@{ip_proxy_info.ip}:{ip_proxy_info.port}"
        }
        return playwright_proxy, httpx_proxy

    async def launch_browser(
            self,
            chromium: BrowserType,
            playwright_proxy: Optional[Dict],
            user_agent: Optional[str],
            headless: bool = True
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[WeiboCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.getcwd(), "browser_data",
                                         config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=user_agent
            )
            return browser_context
