import asyncio
import csv
import json
import logging
import os
import random
import re
import signal
import sys
from datetime import datetime
from typing import TextIO, Set, List, Optional, Dict
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Page
from dotenv import load_dotenv
import unicodedata

load_dotenv()

# Set up logging
def setup_logging(log_level: str) -> logging.Logger:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    file_handler = logging.FileHandler('instagram_scraper.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger = logging.getLogger(__name__)
    logger.setLevel(numeric_level)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

# Load config.json
with open('config.json', 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

logger = setup_logging(CONFIG.get('log_level', 'INFO'))

class InstagramScraper:
    def __init__(self):
        self.config = CONFIG
        self.user_data_dir = os.path.join(os.getcwd(), self.config['user_data_dir'])
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.username = os.getenv('INSTAGRAM_USERNAME')
        self.password = os.getenv('INSTAGRAM_PASSWORD')
        self.proxy_server = os.getenv('PROXY_SERVER')
        self.headless = os.getenv('HEADLESS', 'true').lower() == 'true'
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        ]
        self.progress_file = 'scraper_progress.json'
        self.load_progress()
        self.shutdown = False
        self.page = None

    def load_progress(self) -> None:
        try:
            if os.path.exists(self.progress_file):
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    self.progress = json.load(f)
                    self.progress['processed_profiles'] = list(set(self.progress.get('processed_profiles', [])))  # Ensure uniqueness
            else:
                self.progress = {'processed_profiles': [], 'csv_file': None, 'last_processed': None}
        except Exception as e:
            logger.error(f"Error loading progress: {e}")
            self.progress = {'processed_profiles': [], 'csv_file': None, 'last_processed': None}

    def save_progress(self, last_processed: Optional[str] = None) -> None:
        try:
            self.progress['last_processed'] = last_processed or self.progress.get('last_processed')
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving progress: {e}")

    def load_existing_usernames(self, csv_filename: str) -> Set[str]:
        existing_usernames = set()
        if os.path.exists(csv_filename):
            try:
                with open(csv_filename, mode='r', encoding='utf-8') as file:
                    reader = csv.DictReader(file)
                    for row in reader:
                        if row.get('username'):
                            existing_usernames.add(row['username'])
            except Exception as e:
                logger.error(f"Error reading existing CSV {csv_filename}: {e}")
        return existing_usernames

    def load_profiles_from_csv(self, csv_filename: str = 'profiles.csv') -> List[str]:
        profiles = []
        try:
            with open(csv_filename, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    profile = row.get('profile', '').strip()
                    if profile:
                        profiles.append(profile)
            logger.info(f"Loaded {len(profiles)} profiles from {csv_filename}")
        except FileNotFoundError:
            logger.error(f"CSV file {csv_filename} not found. Please create it with a 'profile' column.")
        except Exception as e:
            logger.error(f"Error loading profiles from CSV: {e}")
        return profiles

    def setup_shutdown_handler(self, browser):
        async def close_browser():
            self.save_progress()
            try:
                await browser.close()
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {e}")

        def signal_handler(sig, frame):
            logger.info("Shutdown signal received, saving progress...")
            self.shutdown = True
            asyncio.create_task(close_browser())
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def random_delay(self, min_delay: float = 1, max_delay: float = 3) -> None:
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)

    async def is_logged_in(self, page: Page) -> bool:
        try:
            logged_in_selectors = [
                'nav[role="navigation"]',
                'svg[aria-label="Home"]',
                'svg[aria-label="Explore"]',
                'a[href*="/direct/inbox/"]'
            ]
            for selector in logged_in_selectors:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return True
            login_form_selectors = [
                'input[name="username"]',
                'input[name="password"]',
                'button:has-text("Log in")'
            ]
            for selector in login_form_selectors:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return False
            return False
        except Exception as e:
            logger.error(f"Error checking login status: {e}")
            return False

    async def handle_login(self, page: Page) -> bool:
        try:
            if await self.is_logged_in(page):
                logger.info("Already logged in")
                return True
            logger.info("Attempting login...")
            for attempt in range(3):
                try:
                    await page.goto("https://www.instagram.com/accounts/login/", timeout=60000)
                    await page.wait_for_selector('input[name="username"]', timeout=30000)
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"Failed to load login page after 3 attempts: {e}")
                        return False
                    await self.random_delay(5, 10)
            if not self.username or not self.password:
                logger.error("Instagram credentials not found in .env")
                return False
            await page.locator('input[name="username"]').fill(self.username)
            await self.random_delay(1, 2)
            await page.locator('input[name="password"]').fill(self.password)
            await self.random_delay(1, 2)
            await page.locator('button[type="submit"]').click()
            await self.random_delay(3, 5)
            try:
                await page.wait_for_selector('nav[role="navigation"], div[role="dialog"]', timeout=30000)
            except:
                if await page.query_selector('xpath=//*[contains(text(), "Suspicious Login Attempt")]'):
                    logger.error("Suspicious login attempt detected")
                    return False
                if await page.query_selector('xpath=//*[contains(text(), "Verify Your Account")]'):
                    logger.error("Account verification required")
                    return False
            dismiss_selectors = [
                'button:has-text("Not Now")',
                'button:has-text("Save Info")',
                'button:has-text("Later")'
            ]
            for selector in dismiss_selectors:
                try:
                    button = await page.wait_for_selector(selector, timeout=5000)
                    if button and await button.is_visible():
                        await button.click()
                        await self.random_delay(2, 4)
                except:
                    continue
            if await self.is_logged_in(page):
                logger.info("Login successful")
                return True
            logger.error("Login failed")
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def check_for_block(self, page: Page) -> bool:
        block_indicators = [
            'text="Log in to continue"',
            'text="Suspicious activity"',
            'text="Your account has been temporarily blocked"',
            'text="We detected unusual activity"',
            'iframe[src*="captcha"]',
            'text="Try Again Later"',
            'text="Please wait a few minutes"',
            'text="Something went wrong"',
            'text="Please wait a few minutes before you try again"',
            'text="Rate limit exceeded"',
            'text="Challenge required"'
        ]
        for selector in block_indicators:
            if await page.query_selector(selector):
                logger.error(f"Detected block: {selector}")
                await asyncio.sleep(random.uniform(60, 120))
                return True
        return False

    async def count_comments(self, page: Page) -> int:
        try:
            comment_selectors = [
                'ul._a9ym',
                'div._a9zo li',
                'div[class*="x1qjc9v5"] li[class*="x1y1aw1k"]',
                'div[class*="x9f619"] ul li'
            ]
            for selector in comment_selectors:
                for attempt in range(3):
                    try:
                        await page.wait_for_selector(selector, state='visible', timeout=10000)
                        comments = await page.query_selector_all(selector)
                        if comments:
                            count = len([c for c in comments if await c.is_visible()])
                            return count
                        await asyncio.sleep(2 ** attempt)
                    except Exception as e:
                        if attempt == 2:
                            comment_section = await page.query_selector('div._a9zo') or await page.query_selector('ul._a9ym')
                            if comment_section:
                                html = await comment_section.inner_html()
            comment_button = await page.query_selector('div[role="button"] svg[aria-label="Comment"]')
            if comment_button:
                parent = await page.query_selector('xpath=./ancestor::div[contains(@class, "x1i10hfl")]')
                if parent:
                    count_element = await parent.query_selector('span.x1lliihq')
                    if count_element:
                        count_text = await count_element.inner_text()
                        count = self.normalize_number(count_text)
                        return count
            return 0
        except Exception as e:
            logger.error(f"Error counting comments: {e}")
            return 0

    async def get_likes(self, page: Page) -> int:
        try:
            likes_selectors = [
                'span.x193iq5w:has-text("likes")',
                'span.x1vvkbs:has-text("likes")',
                'div[class*="x9f619"] span.x193iq5w:has-text("likes")',
                'div[class*="x9f619"] span.x1vvkbs:has-text("likes")',
            ]
            for selector in likes_selectors:
                for attempt in range(3):
                    try:
                        await page.wait_for_selector(selector, state='visible', timeout=10000)
                        elements = await page.query_selector_all(selector)
                        for element in elements:
                            if not await element.is_visible():
                                continue
                            likes_text = await element.inner_text()
                            if re.search(r'\d+', likes_text) and 'likes' in likes_text.lower():
                                likes = self.normalize_number(likes_text)
                                return likes
                        await asyncio.sleep(2 ** attempt)
                    except:
                        if attempt == 2:
                            engagement_section = await page.query_selector('section.x1qjc9v5') or \
                                            await page.query_selector('div[class*="x9f619"][class*="x78zum5"]')
                            if engagement_section:
                                html = await engagement_section.inner_html()
            return 0
        except Exception as e:
            logger.error(f"Error getting likes: {e}")
            return 0

    async def get_text(self, selector: str, context: Optional[Page] = None, default: str = 'N/A') -> str:
        if selector == 'span._aohg':
            return default
        context = context or self.page
        for attempt in range(3):
            try:
                await context.wait_for_selector(selector, state='visible', timeout=15000)
                element = await context.query_selector(selector)
                if element and await element.is_visible():
                    text = await element.inner_text()
                    return text.strip() if text else default
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for selector {selector}: {e}")
                if attempt == 2:
                    return default

    async def get_attr(self, selector: str, attr: str, context: Optional[Page] = None, default: str = 'N/A') -> str:
        try:
            context = context or self.page
            await context.wait_for_selector(selector, state='visible', timeout=10000)
            element = await context.query_selector(selector)
            if element and await element.is_visible():
                value = await element.get_attribute(attr)
                return value if value else default
            return default
        except Exception as e:
            return default

    def extract_email(self, text: str) -> str:
        if not text or text == 'N/A':
            return 'N/A'
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?'
        matches = re.findall(email_pattern, text, re.IGNORECASE)
        return matches[0] if matches else 'N/A'

    def normalize_unicode(self, text: str) -> str:
        return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII') if text else text

    async def navigate_to_profile(self, page: Page, username: str) -> bool:
        logger.info(f"Navigating to profile: {username}")
        for attempt in range(3):
            try:
                profile_url = f"https://www.instagram.com/{username}/"
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('header[class*="xrvj5dj"], section[class*="xc3tme8"]', state='visible', timeout=30000)
                await page.wait_for_timeout(5000)
                await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                header = await page.query_selector('header[class*="xrvj5dj"]')
                if header or await page.query_selector('section[class*="xc3tme8"]'):
                    return True
                raise Exception("Profile page header or section not found")
            except Exception as e:
                logger.warning(f"Navigation attempt {attempt + 1} failed: {str(e)}")
                if attempt < 2:
                    await self.random_delay()
                    continue
                logger.error(f"Failed to navigate to profile: {username}")
                return False

    async def wait_for_posts(self, page: Page, selector: str = 'a[href*="/p/"], a[href*="/reel/"], article', timeout: int = 60000) -> List:
        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout)
            return await page.query_selector_all(selector)
        except Exception as e:
            logger.error(f"Error waiting for posts with selector '{selector}': {e}")
            return []

    async def close_post(self, page: Page) -> None:
        try:
            close_selectors = [
                'button[aria-label="Close"]',
                'svg[aria-label="Close"]',
                'div[role="dialog"] button'
            ]
            for selector in close_selectors:
                try:
                    close_button = await page.wait_for_selector(selector, timeout=5000)
                    if close_button and await close_button.is_visible():
                        await close_button.click()
                        await self.random_delay()
                        return
                except:
                    continue
            await page.keyboard.press("Escape")
            await self.random_delay()
        except Exception as e:
            logger.warning(f"Error closing post: {e}")

    async def get_highlights(self, page: Page) -> List[str]:
        highlights = []
        try:
            await page.wait_for_selector('div.xqy66fx', state='visible', timeout=10000)
            highlight_elements = await page.query_selector_all('div.xqy66fx span.x1lliihq')
            for element in highlight_elements:
                if await element.is_visible():
                    text = await element.inner_text()
                    highlights.append(text.strip())
        except Exception as e:
            logger.warning(f"Error getting highlights: {e}")
        return highlights[:5]

    async def scrape_profile(self, page: Page, profile: str, writer: csv.DictWriter, csv_file: TextIO,
                            existing_usernames: Set[str]) -> Optional[dict]:
        username = profile.strip('@') if not profile.startswith('http') else profile.split('/')[-2]
        if username in self.progress['processed_profiles']:
            logger.info(f"Skipping already processed profile: {username}")
            return None
        if username in existing_usernames:
            logger.info(f"Skipping duplicate username: {username}")
            return None

        logger.info(f"Scraping profile: {username}")
        if not await self.navigate_to_profile(page, username):
            logger.error(f"Failed to navigate to profile: {username}")
            self.progress['processed_profiles'].append(username)
            self.save_progress(username)
            return None

        try:
            await page.wait_for_timeout(5000)
            header = await page.query_selector('header')
            if not header:
                logger.error(f"Profile header not found for {username}")
                return None
            private_indicator = await page.query_selector('text="This account is private"')
            no_posts_indicator = await page.query_selector('text="No Posts Yet"')
            if private_indicator or no_posts_indicator:
                logger.info(f"Skipping {username}: {'Private account' if private_indicator else 'No posts'}")
                self.progress['processed_profiles'].append(username)
                self.save_progress(username)
                return None

            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(2000)

            name_selectors = [
                'section.xc3tme8 div.x7a106z span.x1lliihq:not([class*="xdj266r"])',
                'h1[class*="x1lliihq"]',
                'span[class*="x1plvlek"]'
            ]
            full_name = 'N/A'
            for selector in name_selectors:
                name_text = await self.get_text(selector)
                if name_text != 'N/A' and not re.search(r'^\d+ posts$', name_text.strip()):
                    full_name = self.normalize_unicode(name_text)
                    break

            stat_selectors = [
                ('posts', 'ul.xieb3on li:nth-child(1) span'),
                ('followers', 'ul.xieb3on li:nth-child(2) span'),
                ('following', 'ul.xieb3on li:nth-child(3) span')
            ]
            stats = {'posts': 0, 'followers': 0, 'following': 0}
            for key, selector in stat_selectors:
                try:
                    text = await self.get_text(selector)
                    stats[key] = self.normalize_number(text)
                except Exception as e:
                    stats[key] = 0

            bio_selectors = [
                'span._ap3a',
                'div[class*="x1nhvcw1"] span._ap3a',
                'span[class*="xdj266r"]'
            ]
            bio = 'N/A'
            more_button_selectors = [
                'span._ap3a span div[role="button"]:has-text("more")',
                'div[class*="x1nhvcw1"] span._ap3a span div[role="button"]:has-text("more")',
                'div[class*="x9f619"] span._ap3a span div[role="button"]:has-text("more")'
            ]
            for selector in more_button_selectors:
                more_button = await page.query_selector(selector)
                if more_button and await more_button.is_visible():
                    logger.debug(f"Clicked 'more' for {username} with selector {selector}")
                    await more_button.click()
                    await page.wait_for_timeout(2000)
                    break

            for selector in bio_selectors:
                bio_text = await self.get_text(selector)
                if bio_text != 'N/A' and bio_text.strip():
                    bio = re.sub(r'\s*\|\s*', ' | ', bio_text.replace('\n', ' | ')).strip()
                    break

            email = self.extract_email(bio)

            post_data = []
            post_selectors = [
                'div.x1lliihq.x1n2onr6.xh8yej3',
                'a[href*="/p/"]',
                'a[href*="/reel/"]',
                'article',
                'div[class*="x1qjc9v5"]'
            ]
            recent_posts = []
            for selector in post_selectors:
                posts = await self.wait_for_posts(page, selector=selector, timeout=30000)
                if posts:
                    recent_posts = posts[:2]
                    break
            if not recent_posts:
                post_data = [{'likes': 0, 'comments': 0, 'engagement': 0}] * 2

            for i, post in enumerate(recent_posts):
                try:
                    for hover_attempt in range(3):
                        try:
                            await post.scroll_into_view_if_needed()
                            await post.hover()
                            await page.wait_for_timeout(1000)
                            popup_selector = 'ul.x6s0dn4'
                            await page.wait_for_selector(popup_selector, state='visible', timeout=5000)
                            popup = await page.query_selector(popup_selector)
                            if popup:
                                likes_element = await popup.query_selector('li:nth-child(1) span.x1lliihq span.html-span')
                                comments_element = await popup.query_selector('li:nth-child(2) span.x1lliihq span.html-span')
                                likes = self.normalize_number(await likes_element.inner_text()) if likes_element else 0
                                comments = self.normalize_number(await comments_element.inner_text()) if comments_element else 0
                                engagement = likes + comments
                            else:
                                likes = 0
                                comments = 0
                                engagement = 0
                            post_data.append({'likes': likes, 'comments': comments, 'engagement': engagement})
                            await page.wait_for_timeout(500)
                            break
                        except Exception as e:
                            if hover_attempt < 2:
                                await self.random_delay(1, 2)
                                continue
                            post_data.append({'likes': 0, 'comments': 0, 'engagement': 0})
                            break
                except Exception as e:
                    logger.error(f"Error processing post {i + 1} for {username}: {e}")
                    post_data.append({'likes': 0, 'comments': 0, 'engagement': 0})

            while len(post_data) < 2:
                post_data.append({'likes': 0, 'comments': 0, 'engagement': 0})

            total_engagement = post_data[0]['engagement'] + post_data[1]['engagement']

            profile_data = {
                'full_name': full_name,
                'username': username,
                'post_count': stats['posts'],
                'followers': stats['followers'],
                'following': stats['following'],
                'bio': bio,
                'email': email,
                'post_1_engagement': post_data[0]['engagement'],
                'post_2_engagement': post_data[1]['engagement'],
                'total_engagement': total_engagement,
                'instagram_link': f"https://www.instagram.com/{username}/"
            }

            writer.writerow(profile_data)
            csv_file.flush()
            existing_usernames.add(username)
            self.progress['processed_profiles'].append(username)
            self.save_progress(username)
            logger.info(f"Saved profile data for {username} with total engagement: {total_engagement}")
            return profile_data

        except Exception as e:
            logger.error(f"Error scraping profile {username}: {e}")
            return None

    async def run(self) -> None:
        profiles = self.load_profiles_from_csv()
        if not profiles:
            logger.error("No profiles loaded from CSV. Exiting...")
            return

        async with async_playwright() as p:
            browser_args = [
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
            if self.proxy_server:
                browser_args.append(f'--proxy-server={self.proxy_server}')
            browser = await p.chromium.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                viewport=self.config['viewport'],
                locale=self.config.get('locale', 'en-US'),
                timezone_id=self.config['timezone_id'],
                user_agent=random.choice(self.user_agents),
                args=browser_args,
                ignore_https_errors=True
            )
            try:
                self.setup_shutdown_handler(browser)
                self.page = await browser.new_page()
                await self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.navigator.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)
                await self.page.context.grant_permissions(['geolocation'])
                await self.page.evaluate("""
                    () => {
                        navigator.geolocation.getCurrentPosition = function(success, error, options) {
                            if (typeof success === 'function') {
                                success({
                                    coords: {
                                        latitude: 48.8566,
                                        longitude: 2.3522,
                                        accuracy: 1000
                                    },
                                    timestamp: Date.now()
                                });
                            }
                            else if (typeof error === 'function') {
                                error(new Error('Geolocation success callback is not a function'));
                            }
                        };
                    }
                """)
                logger.info("Navigating to Instagram...")
                await self.page.goto("https://www.instagram.com/", timeout=60000)
                if not await self.handle_login(self.page):
                    logger.error("Login failed. Exiting...")
                    await browser.close()
                    return

                csv_filename = self.progress.get('csv_file')
                if not csv_filename or not os.path.exists(csv_filename):
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    csv_filename = f'instagram_profiles_{timestamp}.csv'
                    self.progress['csv_file'] = csv_filename
                    self.save_progress()

                existing_usernames = self.load_existing_usernames(csv_filename)
                with open(csv_filename, mode='a', newline='', encoding='utf-8') as csv_file:
                    fieldnames = [
                        'full_name', 'username', 'post_count', 'followers', 'following', 'bio', 'email',
                        'post_1_engagement', 'post_2_engagement', 'total_engagement', 'instagram_link'
                    ]
                    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                    if csv_file.tell() == 0:
                        writer.writeheader()

                    last_processed = self.progress.get('last_processed')
                    start_processing = False if last_processed else True
                    profile_count = 0
                    skip_count = 0
                    for profile in profiles:
                        if self.shutdown:
                            logger.info("Shutdown detected, stopping...")
                            break
                        if await self.check_for_block(self.page):
                            logger.error("Instagram block detected, stopping...")
                            break
                        username = profile.strip('@') if not profile.startswith('http') else profile.split('/')[-2]
                        if not start_processing and username == last_processed:
                            start_processing = True
                            if skip_count > 0:
                                logger.info(f"Skipped {skip_count} profiles until last processed: {last_processed}")
                            continue
                        if not start_processing:
                            skip_count += 1
                            continue
                        if username in self.progress['processed_profiles']:
                            logger.info(f"Skipping already processed profile: {username}")
                            continue
                        if username in existing_usernames:
                            logger.info(f"Skipping duplicate username: {username}")
                            continue
                        await self.scrape_profile(self.page, profile, writer, csv_file, existing_usernames)
                        profile_count += 1
                        if profile_count % 10 == 0:  # Save every 10 profiles
                            self.save_progress(username)
                        await self.random_delay(5, 10)
                    if skip_count > 0 and not start_processing:  # Handle case where last_processed is last profile
                        logger.info(f"Skipped {skip_count} profiles until last processed: {last_processed}")
                    self.save_progress(username)  # Final save
                logger.info(f"Scraping complete. Total profiles processed: {len(self.progress['processed_profiles'])}")
            except Exception as e:
                logger.error(f"Error during scraping: {e}")
            finally:
                await browser.close()
                logger.info("Browser closed successfully")

    def normalize_number(self, text: str) -> int:
        if not text or text == 'N/A':
            return 0
        text = re.sub(r'\s*likes\s*', '', text, flags=re.IGNORECASE).strip()
        text = re.sub(r'[^\d.km]', '', text.lower(), flags=re.IGNORECASE).strip()
        if not text:
            return 0
        try:
            if text.endswith('k'):
                return int(float(text[:-1]) * 1000)
            elif text.endswith('m'):
                return int(float(text[:-1]) * 1000000)
            else:
                return int(float(text))
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to normalize number: {text}, error: {str(e)}")
            return 0

if __name__ == "__main__":
    logger.info("Starting Instagram scraper")
    scraper = InstagramScraper()
    asyncio.run(scraper.run())