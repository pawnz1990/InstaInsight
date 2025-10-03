# InstaInsight

InstaInsight is a powerful, asynchronous Instagram scraper designed to collect profile information, bios, emails, followers, posts, and engagement metrics. Perfect for social media analysts, marketers, and data enthusiasts looking to gather insights efficiently.  

---

## Features

- Profile Scraping: Automatically scrape Instagram profiles from a CSV list.  
- Engagement Metrics: Collect likes, comments, and total engagement for recent posts.  
- Bio & Email Extraction: Extract bio info and detect emails in profiles.  
- Resume Capability: Resume scraping where it left off using a progress file.  
- Duplicate Prevention: Skips already processed profiles or duplicate usernames.  
- Headless & Proxy Support: Supports headless browser mode and optional proxy usage.  
- Customizable Logging: Logs info and errors to both console and file for easy monitoring.  
- Error Handling: Detects login issues, blocks, and handles unexpected errors gracefully.  

---

## Installation

1. **Clone the repository**  

```bash
git clone https://github.com/ScrapiqCBett/AmazonBot.git
cd InstaInsight
```

2. Create a virtual environment 

```bash
python -m venv .venv
```

3. Activate the virtual environment 

- Windows (PowerShell):  

```powershell
& .venv\Scripts\Activate.ps1
```

- Mac/Linux:  

```bash
source .venv/bin/activate
```

4. Install dependencies  

```bash
pip install -r requirements.txt
```

5. Create `.env` file with your Instagram credentials:  

```env
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
PROXY_SERVER=http://proxy:port  
HEADLESS=true                    
```

6. Prepare `profiles.csv` with a column `profile` listing Instagram usernames (or profile URLs) to scrape.

---

## Configuration

- `config.json` contains configurable settings like viewport, locale, and log level.  
- `scraper_progress.json` stores progress to resume scraping in case of interruptions.  

Example `config.json` snippet:

```json
{
  "user_data_dir": "user_data",
  "viewport": {"width": 1280, "height": 720},
  "timezone_id": "UTC",
  "log_level": "INFO"
}
```

---

## Usage

Run the scraper:

```bash
python instagram_scraper.py
```

- The scraper will navigate to Instagram, handle login, and scrape profiles listed in `profiles.csv`.  
- Scraped data will be saved in a CSV file named like `instagram_profiles_YYYYMMDD_HHMMSS.csv`.  
- Progress is saved automatically, so you can resume scraping anytime.  

---

## Output

Each profile CSV row contains:

| Field | Description |
|-------|-------------|
| full_name | Full name of the profile |
| username | Instagram username |
| post_count | Number of posts |
| followers | Number of followers |
| following | Number of accounts followed |
| bio | Profile bio |
| email | Extracted email if available |
| post_1_engagement | Engagement (likes+comments) on latest post |
| post_2_engagement | Engagement on second latest post |
| total_engagement | Sum of the two posts' engagement |
| instagram_link | Direct link to profile |

---

## Features in Action

- Randomized delays simulate human behavior  
- Handles private accounts and skips them automatically  
- Detects blocks and pauses to avoid restrictions  
- Logs all actions for monitoring and debugging  

---

## Tips

- Use a proxy for large-scale scraping to avoid blocks.  
- Run  headless=false for debugging and visually checking the scraping process.  
- Keep `profiles.csv` updated with new accounts for continuous scraping.  

---

## Requirements

- Python 3.11+  
- Playwright (`pip install playwright`)  
- python-dotenv  
- asyncio, logging, csv, json  

---

## Disclaimer

- Use responsibly! Respect Instagram’s terms of service.  
- Avoid scraping private accounts or abusing the data.  

---

## Contact

For questions, issues, or feature requests, reach out via GitHub Issues or DM.  

---

Made by ScrapiqCBett
