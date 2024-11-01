import re
import os
import csv
import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# List of user agents to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
]

def setup_driver():
    """Setup and return Chrome WebDriver with rotating user agent"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument(f'user-agent={random.choice(USER_AGENTS)}')
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def wait_with_backoff(attempt, max_wait=300):
    """Implement exponential backoff"""
    wait_time = min(max_wait, 5 * (2 ** attempt) + random.uniform(0, 1))
    print(f"Rate limit encountered. Waiting {wait_time:.1f} seconds before retry...")
    time.sleep(wait_time)

def get_image_url_from_tweet(driver, tweet_url, max_retries=3):
    """Extract image URL from tweet page with retry logic"""
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1} of {max_retries} for tweet: {tweet_url}")
            driver.get(tweet_url)
            
            selectors = [
                'img[alt="Image"]',
                'div[data-testid="tweetPhoto"] img',
                'div[data-testid="tweet"] img',
                'article img',
                'div[role="article"] img'
            ]
            
            wait = WebDriverWait(driver, 10)
            for selector in selectors:
                try:
                    elements = wait.until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                    )
                    
                    valid_images = []
                    for element in elements:
                        src = element.get_attribute('src')
                        if src and ('profile' not in src.lower() and 'avatar' not in src.lower()):
                            try:
                                width = int(element.get_attribute('width') or 0)
                                height = int(element.get_attribute('height') or 0)
                                if width * height > 10000:
                                    valid_images.append(src)
                            except ValueError:
                                valid_images.append(src)
                    
                    if valid_images:
                        image_url = valid_images[0]
                        if '?format=' in image_url:
                            image_url = image_url.split('?format=')[0] + '?format=jpg&name=large'
                        return image_url
                except:
                    continue
            
            if attempt < max_retries - 1:
                wait_with_backoff(attempt)
            
        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_with_backoff(attempt)
    
    return None

def download_image(image_url, save_path, max_retries=3):
    """Download image with retry logic"""
    for attempt in range(max_retries):
        try:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Referer': 'https://twitter.com/'
            }
            response = requests.get(image_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                return True
            elif response.status_code == 429:  # Rate limit
                if attempt < max_retries - 1:
                    wait_with_backoff(attempt)
                continue
            
            return False
        except Exception as e:
            print(f"Error downloading image on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                wait_with_backoff(attempt)
    
    return False

def process_twitter_data(code_file, output_csv, images_dir, start_from=1):
    """Main function to process Twitter data with resume capability"""
    os.makedirs(images_dir, exist_ok=True)
    
    # Load existing progress if any
    processed_ids = set()
    if os.path.exists(output_csv):
        with open(output_csv, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            processed_ids = {int(row[0]) for row in reader if row}
    
    driver = None
    try:
        driver = setup_driver()
        data = extract_data_from_code(code_file)
        
        # Filter out already processed entries
        data = [(id_num, url, caption) for id_num, url, caption in data 
               if id_num >= start_from and id_num not in processed_ids]
        
        print(f"Starting from ID {start_from}, {len(data)} entries to process")
        
        mode = 'a' if os.path.exists(output_csv) else 'w'
        with open(output_csv, mode, newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if mode == 'w':
                writer.writerow(['ID', 'Twitter URL', 'Local Image Path', 'Reply Text'])
            
            for index, (id_num, url, caption) in enumerate(data, 1):
                print(f"\nProcessing entry {id_num} ({index}/{len(data)})...")
                
                try:
                    image_url = get_image_url_from_tweet(driver, url)
                    
                    if image_url:
                        tweet_id = url.split('status/')[1].split('/')[0]
                        save_path = os.path.join(images_dir, f"twitter_{tweet_id}.jpg")
                        
                        if download_image(image_url, save_path):
                            writer.writerow([id_num, url, save_path, caption])
                            csvfile.flush()  # Ensure data is written immediately
                        else:
                            writer.writerow([id_num, url, "Failed to download", caption])
                    else:
                        writer.writerow([id_num, url, "No image found", caption])
                    
                    # Random delay between requests
                    time.sleep(random.uniform(2, 5))
                
                except Exception as e:
                    print(f"Error processing entry {id_num}: {str(e)}")
                    writer.writerow([id_num, url, f"Error: {str(e)}", caption])
                    continue
    
    finally:
        if driver:
            driver.quit()

def extract_data_from_code(code_file):
    with open(code_file, 'r') as f:
        content = f.read()
    
    pattern = r'elif\s*\(x\s*==\s*(\d+)\):\s*mediaLink\s*=\s*"([^"]+)"\s*reply_text\s*=\s*"([^"]+)"'
    matches = re.finditer(pattern, content)
    
    data = [(int(m.group(1)), m.group(2).strip(), m.group(3)) for m in matches]
    data.sort(key=lambda x: x[0])
    
    return data

if __name__ == "__main__":
    CODE_FILE = "twitter_data.py"
    OUTPUT_CSV = "twitter_data.csv"
    IMAGES_DIR = "downloaded_images"
    
    # You can change this to resume from a specific ID
    START_FROM_ID = 410
    
    print("Starting Twitter image processing...")
    process_twitter_data(CODE_FILE, OUTPUT_CSV, IMAGES_DIR, START_FROM_ID)
    print(f"\nProcessing complete. Results saved to {OUTPUT_CSV}")